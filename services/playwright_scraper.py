"""
Playwright/httpx scraper for downloading invoice XML from provider portals.
Sync wrapper for Flask. Supports Firestore-based provider config.
"""
import re
import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/xml,text/xml,*/*;q=0.8',
}

# Hardcoded fallback transforms (used when no Firestore config)
_FALLBACK_TRANSFORMS = {
    'VNPT':        {'find': '/Email/EmailInvoiceView?', 'replace': '/Email/XmlDownload?'},
    'VIN_HOADON':  {'find': '/tracuuhoadon/thongtinchung?', 'replace': '/File/TaiXmlLinkTraCuu?'},
    'FASTINVOICE': {'find': 'type=1', 'replace': 'type=2'},
    'EINVOICE':    {'find': '/ViewFromEmail?', 'replace': '/DownloadInvXml?'},
    'ASIAINVOICE': {'find': '/EinvoiceView?', 'replace': '/EinvoiceXml?'},
}

_FALLBACK_XML_SELECTORS = [
    'a:has-text("Tải XML")', 'a:has-text("Download XML")',
    'button:has-text("Tải XML")', 'button:has-text("XML")',
    'a[href$=".xml"]', 'a[href*="XmlDownload" i]', 'a[href*="DownloadXml" i]',
    'a[href*="tai-xml" i]', '[class*="btn-xml" i]', '[id*="btnXml" i]',
]

_FALLBACK_TAX_SELECTORS    = ['input[name*="taxCode" i]', 'input[placeholder*="mã số thuế" i]',
                               'input[id*="taxCode" i]']
_FALLBACK_SECRET_SELECTORS = ['input[name*="secret" i]', 'input[placeholder*="bí mật" i]',
                               'input[placeholder*="bảo mật" i]', 'input[type="password"]']
_FALLBACK_SUBMIT_SELECTORS = ['button[type="submit"]', 'button:has-text("Tra cứu")',
                               'button:has-text("Tìm kiếm")', 'input[type="submit"]']


# ── Firestore config cache ──────────────────────────────────────────
_config_cache: dict = {}
_config_cache_time: float = 0
_CONFIG_TTL = 300  # 5 minutes


def load_provider_configs(db) -> dict:
    """Load all portal_scraper_config docs from Firestore. Cached 5 min."""
    global _config_cache, _config_cache_time
    now = time.time()
    if _config_cache and now - _config_cache_time < _CONFIG_TTL:
        return _config_cache
    try:
        docs = db.collection('portal_scraper_config').stream()
        _config_cache = {doc.id: doc.to_dict() for doc in docs}
        _config_cache_time = now
        logger.info(f"[scraper] Loaded {len(_config_cache)} provider configs from Firestore")
    except Exception as e:
        logger.warning(f"[scraper] Failed to load Firestore config: {e}")
    return _config_cache


def get_provider_config(db, provider: str) -> dict | None:
    """Get config for one provider."""
    configs = load_provider_configs(db)
    return configs.get(provider)


# ── Core scraping logic ─────────────────────────────────────────────

def _is_xml(content: bytes) -> bool:
    return b'<?xml' in content[:100] or b'<HDon' in content[:300] or b'<invoiceData' in content[:300]


async def _try_direct_http(xml_url: str) -> Optional[bytes]:
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(xml_url, headers=_HEADERS)
            ct = r.headers.get('content-type', '')
            if r.status_code == 200 and ('xml' in ct.lower() or _is_xml(r.content)):
                logger.info(f"[scraper] Direct HTTP OK ({len(r.content)}B): {xml_url[:80]}")
                return r.content
            logger.warning(f"[scraper] Direct HTTP failed: status={r.status_code} ct={ct[:60]}")
    except Exception as e:
        logger.warning(f"[scraper] Direct HTTP error: {e}")
    return None


async def _playwright_scrape(url: str, credentials: dict | None,
                              xml_selectors: list, cred_config: dict | None) -> Optional[bytes]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("[scraper] playwright not installed. Run: pip install playwright && playwright install chromium")
        return None

    xml_bytes: Optional[bytes] = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=_HEADERS['User-Agent'], accept_downloads=True)
            page = await context.new_page()

            async def on_response(response):
                nonlocal xml_bytes
                if xml_bytes:
                    return
                ct = response.headers.get('content-type', '')
                if 'xml' in ct.lower() or response.url.lower().endswith('.xml'):
                    try:
                        body = await response.body()
                        if _is_xml(body):
                            xml_bytes = body
                    except Exception:
                        pass

            page.on('response', on_response)
            await page.goto(url, timeout=30000, wait_until='networkidle')

            # Group B: fill credentials
            if credentials and cred_config:
                await _fill_credentials(page, credentials, cred_config)
                await page.wait_for_load_state('networkidle', timeout=15000)

            if not xml_bytes:
                for sel in xml_selectors:
                    try:
                        el = page.locator(sel).first
                        if await el.count() == 0:
                            continue
                        try:
                            async with page.expect_download(timeout=8000) as dl_info:
                                await el.click()
                            dl = await dl_info.value
                            path = await dl.path()
                            if path:
                                with open(path, 'rb') as f:
                                    xml_bytes = f.read()
                                break
                        except Exception:
                            await el.click()
                            await page.wait_for_timeout(2000)
                            if xml_bytes:
                                break
                    except Exception:
                        continue

            await browser.close()
    except Exception as e:
        logger.error(f"[scraper] Playwright error for {url}: {e}")
    return xml_bytes


async def _fill_credentials(page, credentials: dict, cred_config: dict):
    """Fill credential fields using Firestore-configured selectors."""
    tax_code = credentials.get('taxCode', '')
    secret_code = credentials.get('secretCode', '')

    tax_selectors = cred_config.get('taxCode', _FALLBACK_TAX_SELECTORS)
    if isinstance(tax_selectors, str):
        tax_selectors = [tax_selectors]
    secret_selectors = cred_config.get('secretCode', _FALLBACK_SECRET_SELECTORS)
    if isinstance(secret_selectors, str):
        secret_selectors = [secret_selectors]
    submit_sel = cred_config.get('submit', '')

    if tax_code:
        for sel in tax_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.fill(tax_code)
                    break
            except Exception:
                continue

    if secret_code:
        for sel in secret_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.fill(secret_code)
                    break
            except Exception:
                continue

    submit_selectors = [submit_sel] if submit_sel else _FALLBACK_SUBMIT_SELECTORS
    for sel in submit_selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                break
        except Exception:
            continue


async def _scrape_xml_async(portal_url: str, provider: str,
                             credentials: dict | None = None,
                             provider_config: dict | None = None) -> Optional[bytes]:
    if not portal_url:
        return None

    # 1. Direct HTTP transform
    transform = None
    if provider_config and provider_config.get('directXmlTransform'):
        transform = provider_config['directXmlTransform']
    elif provider in _FALLBACK_TRANSFORMS:
        transform = _FALLBACK_TRANSFORMS[provider]

    if transform:
        xml_url = portal_url.replace(transform['find'], transform['replace'])
        result = await _try_direct_http(xml_url)
        if result:
            return result

    # 2. Playwright scrape
    xml_selectors = (provider_config or {}).get('xmlClickSelectors', _FALLBACK_XML_SELECTORS)
    cred_config = (provider_config or {}).get('credentialFields')
    return await _playwright_scrape(portal_url, credentials, xml_selectors, cred_config)


def scrape_xml_sync(portal_url: str, provider: str,
                     credentials: dict | None = None,
                     provider_config: dict | None = None) -> Optional[bytes]:
    """Sync wrapper for Flask — calls async scraper via asyncio.run()."""
    try:
        return asyncio.run(_scrape_xml_async(portal_url, provider, credentials, provider_config))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_scrape_xml_async(portal_url, provider, credentials, provider_config))
        finally:
            loop.close()
