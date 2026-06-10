"""
EmailBodyParser — Extract portal URL from invoice email HTML body.

Parses email HTML to extract:
- Portal URL for viewing/downloading the original invoice
- Invoice provider identification (11 providers, 3 groups)
- Credentials for Group B providers (tax code, secret code, etc.)

Groups:
  A — Direct URL (href contains full params)
  B — URL + Credentials (URL has no params, credentials in email text)
  C — AWS Tracking Wrapper (unwrap awstrack.me -> actual URL)
"""

import re
import logging
from typing import Dict, Optional
from urllib.parse import unquote

logger = logging.getLogger(__name__)

# Try importing BeautifulSoup, fallback to regex-only parsing
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    logger.warning("beautifulsoup4 not installed. EmailBodyParser will use regex-only parsing.")


PROVIDER_PATTERNS = {
    # -- GROUP A: Direct URL extract --
    'VIN_HOADON': {
        'group': 'A',
        'url_contains': ['vin-hoadon.com'],
        'href_pattern': r'https?://tracuu\.vin-hoadon\.com/tracuuhoadon/thongtinchung\?[^"\'>\s]+',
        'pdf_href_pattern': r'https?://tracuu\.vin-hoadon\.com/File/TaiPdfLinkTraCuu\?[^"\'>\s]+',
    },
    'MISA': {
        'group': 'A',
        'url_contains': ['meinvoice.vn'],
        'href_pattern': r'https?://www\.meinvoice\.vn/tra-cuu/\?sc=[^"\'>\s]+',
    },
    'VNPT': {
        'group': 'A',
        'url_contains': ['vnpt-invoice.com.vn'],
        'href_pattern': r'https?://[a-z0-9-]+\.vnpt-invoice\.com\.vn/Email/EmailInvoiceView\?token=[^"\'>\s]+',
        'pdf_href_pattern': r'https?://[a-z0-9-]+\.vnpt-invoice\.com\.vn/Email/PdfDownload\?token=[^"\'>\s]+',
    },
    'ASIAINVOICE': {
        'group': 'A',
        'url_contains': ['asiainvoice.vn'],
        'href_pattern': r'https?://[a-z0-9]+\.asiainvoice\.vn/EinvoiceView\?token=[^"\'>\s]+',
    },
    'KIOTVIET': {
        'group': 'A',
        'url_contains': ['kiotviet.vn'],
        'href_pattern': r'https?://tracuuhoadon\.kiotviet\.vn/\?shd=[^"\'>\s]+',
    },
    'EHOADON': {
        'group': 'A',
        'url_contains': ['ehoadon.vn'],
        'href_pattern': r'https?://tracuu\.ehoadon\.vn/[A-Z0-9]+',
    },

    # -- GROUP B: URL + Credentials extract --
    'MOBIFONE': {
        'group': 'B',
        'url_contains': ['mobifoneinvoice.vn'],
        'href_pattern': r'https?://tracuuhoadon\.mobifoneinvoice\.vn/?',
        'portal_url': 'http://tracuuhoadon.mobifoneinvoice.vn/',
        'credential_patterns': {
            'taxCode': r'Mã đơn vị[:\s]*<strong>([^<]+)</strong>',
            'secretCode': r'Mã bảo mật[:\s]*<strong>\s*([^<]+)</strong>',
        },
    },
    'VIETTEL': {
        'group': 'B',
        'url_contains': ['vinvoice.viettel.vn', 'sinvoice.viettel.vn'],
        'href_pattern': r'https?://(?:vinvoice|sinvoice)\.viettel\.vn/(?:utilities/invoice-search|tracuuhoadon)',
        'portal_url': None,  # Use matched URL from email
        'credential_patterns': {
            'secretCode': r'mã\s*số\s*bí\s*mật\s+([A-Z0-9]+)',
        },
    },
    'MINVOICE': {
        'group': 'B',
        'url_contains': ['minvoice.vn', 'minvoice.com.vn'],
        'href_pattern': r'https?://tracuuhoadon\.minvoice\.(?:vn|com\.vn)/?',
        'portal_url': 'http://tracuuhoadon.minvoice.com.vn/tra-cuu-hoa-don',
        'credential_patterns': {
            'taxCode': r'Bước 2[^<]*<strong>(\d{10,13})</strong>',
            'secretCode': r'Bước 3[^<]*<strong>\s*([A-Z0-9]+)</strong>',
        },
    },
    'EINVOICE': {
        'group': 'B',
        'url_contains': ['einvoice.vn'],
        'href_pattern': r'https?://(?:[^/]*\.)?einvoice\.vn/tra-cuu',
        'portal_url': 'https://einvoice.vn/tra-cuu',
        'credential_patterns': {
            'lookupCode': r'Mã tra cứu hóa đơn[:\s]*</?[^>]*>\s*([A-Z0-9]+)',
        },
    },

    # -- GROUP C: AWS Tracking Wrapper (unwrap) --
    'WININVOICE': {
        'group': 'C',
        'url_contains': ['wininvoice.vn'],
        'awstrack_pattern': r'https?://[^/]+\.awstrack\.me/L0/(https?:%2F%2Ftracuu\.wininvoice\.vn[^"\'>\s]*)/\d+/',
        'href_pattern': r'https?://tracuu\.wininvoice\.vn[^"\'>\s]*',
    },
}


class EmailBodyParser:
    """Parse email HTML body to extract portal URL for invoice lookup."""

    def extract_portal_url(self, email_html: str) -> Dict:
        """
        Parse HTML -> extract portal URL.

        Returns:
            {
                'portalUrl': str,
                'provider': str,
                'portalPdfUrl': str (if available),
                'credentials': dict (Group B only),
            }
        """
        if not email_html:
            return {}

        # Extract all href URLs from HTML
        hrefs = self._extract_hrefs(email_html)

        # Try each provider
        for provider_key, config in PROVIDER_PATTERNS.items():
            group = config['group']

            # Check if any href matches this provider
            matched_href = None
            for href in hrefs:
                for domain in config['url_contains']:
                    if domain in href.lower():
                        matched_href = href
                        break
                if matched_href:
                    break

            if not matched_href:
                # Group C: also check for awstrack wrapper
                if group == 'C' and 'awstrack_pattern' in config:
                    for href in hrefs:
                        if 'awstrack.me' in href.lower():
                            unwrapped = self._unwrap_awstrack_from_href(href, config)
                            if unwrapped:
                                matched_href = unwrapped
                                break
                if not matched_href:
                    continue

            result = {'provider': provider_key}

            if group == 'A':
                # Extract full URL with params
                portal_url = self._extract_pattern(email_html, config['href_pattern'])
                result['portalUrl'] = portal_url or matched_href

                # Check for bonus PDF URL
                if 'pdf_href_pattern' in config:
                    pdf_url = self._extract_pattern(email_html, config['pdf_href_pattern'])
                    if pdf_url:
                        result['portalPdfUrl'] = pdf_url

            elif group == 'B':
                result['portalUrl'] = config.get('portal_url') or matched_href
                credentials = self._extract_credentials(email_html, config)
                if credentials:
                    result['credentials'] = credentials

            elif group == 'C':
                # Try awstrack unwrap first
                if 'awstrack_pattern' in config:
                    unwrapped = self._extract_awstrack_url(email_html, config['awstrack_pattern'])
                    if unwrapped:
                        result['portalUrl'] = unwrapped
                    else:
                        result['portalUrl'] = matched_href
                else:
                    result['portalUrl'] = matched_href

            if result.get('portalUrl'):
                logger.info(f"Extracted portal URL for {provider_key}: {result['portalUrl'][:80]}...")
                return result

        return {}

    def detect_provider(self, email_html: str, from_address: str = '') -> str:
        """Detect invoice provider from email content + sender domain."""
        if not email_html:
            return ''

        hrefs = self._extract_hrefs(email_html)

        for provider_key, config in PROVIDER_PATTERNS.items():
            for href in hrefs:
                for domain in config['url_contains']:
                    if domain in href.lower():
                        return provider_key

            # Group C: check awstrack
            if config['group'] == 'C':
                for href in hrefs:
                    if 'awstrack.me' in href.lower():
                        for domain in config['url_contains']:
                            if domain in href.lower():
                                return provider_key

        # Fallback: check from_address domain
        if from_address:
            from_domain = from_address.split('@')[-1].lower() if '@' in from_address else ''
            for provider_key, config in PROVIDER_PATTERNS.items():
                for domain in config['url_contains']:
                    if domain in from_domain:
                        return provider_key

        return ''

    def _extract_hrefs(self, html: str) -> list:
        """Extract all href URLs from HTML."""
        if HAS_BS4:
            try:
                soup = BeautifulSoup(html, 'html.parser')
                hrefs = []
                for a_tag in soup.find_all('a', href=True):
                    hrefs.append(a_tag['href'])
                return hrefs
            except Exception:
                pass

        # Fallback: regex extraction
        return re.findall(r'href=["\']([^"\']+)["\']', html)

    def _extract_pattern(self, html: str, pattern: str) -> Optional[str]:
        """Extract first match of regex pattern from HTML."""
        match = re.search(pattern, html, re.IGNORECASE)
        return match.group(0) if match else None

    def _extract_credentials(self, html: str, config: dict) -> Dict:
        """Extract credentials from email body for Group B providers."""
        credentials = {}
        patterns = config.get('credential_patterns', {})

        for key, pattern in patterns.items():
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                credentials[key] = match.group(1).strip()

        return credentials

    def _extract_awstrack_url(self, html: str, pattern: str) -> Optional[str]:
        """Extract and decode awstrack.me wrapped URL."""
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            encoded_url = match.group(1)
            return self._decode_awstrack(encoded_url)
        return None

    def _unwrap_awstrack_from_href(self, href: str, config: dict) -> Optional[str]:
        """Try to unwrap awstrack URL from a single href."""
        if 'awstrack_pattern' not in config:
            return None

        match = re.search(config['awstrack_pattern'], href, re.IGNORECASE)
        if match:
            return self._decode_awstrack(match.group(1))

        # Fallback: find url_contains domain in encoded href
        for domain in config['url_contains']:
            encoded_domain = domain.replace('.', '%2E')
            if encoded_domain in href or domain in href:
                # Try to extract the actual URL after /L0/
                l0_match = re.search(r'/L0/(https?[^/\s]+)', href)
                if l0_match:
                    return self._decode_awstrack(l0_match.group(1))
        return None

    @staticmethod
    def _decode_awstrack(encoded_url: str) -> str:
        """URL-decode awstrack.me wrapper -> actual portal URL."""
        decoded = unquote(encoded_url)
        # Handle double encoding
        if '%2F' in decoded or '%3F' in decoded:
            decoded = unquote(decoded)
        # Remove port :443 for https
        decoded = re.sub(r':443(?=/)', '', decoded)
        return decoded
