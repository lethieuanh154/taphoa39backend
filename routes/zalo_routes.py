from __future__ import annotations

import logging
import os
import secrets
import time
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv
from flask import Blueprint, jsonify, redirect, request

load_dotenv()
logger = logging.getLogger(__name__)

ZALO_APP_ID = os.getenv("ZALO_APP_ID", "")
ZALO_APP_SECRET = os.getenv("ZALO_APP_SECRET", "")
ZALO_OA_ID = "1420769616971124037"
ZALO_REDIRECT_URI = os.getenv("ZALO_REDIRECT_URI", "")

# Fallback: env token used if Firestore has none yet
_ENV_OA_TOKEN = os.getenv("ZALO_OA_ACCESS_TOKEN", "")

# In-memory cache for OA token
_oa_token_cache: Dict[str, Any] = {}
_oa_token_lock = threading.Lock()

# Rate limit: {ip: timestamp}
_register_timestamps: Dict[str, float] = {}
RATE_LIMIT_SECONDS = 10

TOKEN_COLLECTION = "config"
TOKEN_DOC_ID = "zalo_oa_token"


def _retry_request(method: str, url: str, max_retries: int = 3, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 15)
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, **kwargs)
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            wait = 2 ** attempt
            logger.warning("Retry %d/%d for %s %s: %s", attempt + 1, max_retries, method, url, exc)
            time.sleep(wait)
    raise RuntimeError(f"Failed after {max_retries} retries: {last_exc}")


# ── OA Token Management ──

def _get_token_db():
    from firebase.init_firebase import init_firestore
    return init_firestore("FIREBASE_SERVICE_ACCOUNT_CUSTOMER")


def _load_oa_token_from_firestore() -> Dict[str, Any]:
    try:
        db = _get_token_db()
        doc = db.collection(TOKEN_COLLECTION).document(TOKEN_DOC_ID).get()
        if doc.exists:
            return doc.to_dict() or {}
    except Exception as exc:
        logger.error("Failed to load OA token from Firestore: %s", exc)
    return {}


def _save_oa_token_to_firestore(data: Dict[str, Any]) -> None:
    try:
        db = _get_token_db()
        db.collection(TOKEN_COLLECTION).document(TOKEN_DOC_ID).set(data, merge=True)
        logger.info("OA token saved to Firestore")
    except Exception as exc:
        logger.error("Failed to save OA token to Firestore: %s", exc)


def _refresh_oa_token(refresh_token: str) -> Dict[str, Any]:
    resp = _retry_request(
        "POST",
        "https://oauth.zaloapp.com/v4/oa/access_token",
        headers={"Content-Type": "application/x-www-form-urlencoded", "secret_key": ZALO_APP_SECRET},
        data={
            "refresh_token": refresh_token,
            "app_id": ZALO_APP_ID,
            "grant_type": "refresh_token",
        },
    )
    result = resp.json()
    if result.get("access_token"):
        token_data = {
            "access_token": result["access_token"],
            "refresh_token": result.get("refresh_token", refresh_token),
            "expires_in": result.get("expires_in", 3600),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_oa_token_to_firestore(token_data)
        with _oa_token_lock:
            _oa_token_cache.update(token_data)
        logger.info("OA token refreshed successfully")
        return token_data

    error = result.get("error_description") or result.get("error_name") or str(result)
    logger.error("OA token refresh failed: %s", error)
    raise RuntimeError(f"OA token refresh failed: {error}")


def get_oa_access_token() -> str:
    """Get a valid OA access_token. Auto-refreshes if near expiry."""
    with _oa_token_lock:
        cached = dict(_oa_token_cache)

    if not cached.get("access_token"):
        cached = _load_oa_token_from_firestore()
        if cached.get("access_token"):
            with _oa_token_lock:
                _oa_token_cache.update(cached)

    # Auto-refresh if near expiry
    if cached.get("access_token") and cached.get("refreshed_at") and cached.get("refresh_token"):
        try:
            refreshed_at = datetime.fromisoformat(cached["refreshed_at"])
            if refreshed_at.tzinfo is None:
                refreshed_at = refreshed_at.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - refreshed_at).total_seconds()
            expires_in = cached.get("expires_in", 3600)
            if elapsed > expires_in * 0.8:
                logger.info("OA token near expiry (%.0fs/%.0fs), refreshing...", elapsed, expires_in)
                try:
                    refreshed = _refresh_oa_token(cached["refresh_token"])
                    return refreshed["access_token"]
                except Exception as exc:
                    logger.warning("Auto-refresh failed, using existing token: %s", exc)
        except Exception:
            pass

    if cached.get("access_token"):
        return cached["access_token"]

    return _ENV_OA_TOKEN


# ── Blueprint ──

def create_zalo_routes_bp() -> Blueprint:
    bp = Blueprint("zalo_routes", __name__, url_prefix="/api/zalo")

    @bp.route("/login", methods=["GET"])
    def zalo_login():
        if not ZALO_APP_ID or not ZALO_REDIRECT_URI:
            return jsonify({"error": "Zalo OAuth not configured"}), 500

        state = request.args.get("state") or secrets.token_urlsafe(16)
        oauth_url = (
            f"https://oauth.zaloapp.com/v4/permission"
            f"?app_id={ZALO_APP_ID}"
            f"&redirect_uri={ZALO_REDIRECT_URI}"
            f"&state={state}"
        )
        return jsonify({"oauth_url": oauth_url})

    @bp.route("/callback", methods=["POST"])
    def zalo_callback():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON body required"}), 400

        code = (payload.get("code") or "").strip()
        if not code:
            return jsonify({"error": "Authorization code is required"}), 400

        try:
            token_resp = _retry_request(
                "POST",
                "https://oauth.zaloapp.com/v4/access_token",
                headers={"Content-Type": "application/x-www-form-urlencoded", "secret_key": ZALO_APP_SECRET},
                data={"code": code, "app_id": ZALO_APP_ID, "grant_type": "authorization_code"},
            )
            token_data = token_resp.json()
        except Exception as exc:
            logger.error("Zalo token exchange failed: %s", exc)
            return jsonify({"error": "Không thể kết nối Zalo"}), 502

        access_token = token_data.get("access_token")
        if not access_token:
            error_msg = token_data.get("error_description") or token_data.get("error_name") or "Token exchange failed"
            logger.error("Zalo token error: %s", token_data)
            return jsonify({"error": error_msg}), 400

        try:
            user_resp = _retry_request(
                "GET",
                "https://graph.zalo.me/v2.0/me",
                headers={"access_token": access_token},
                params={"fields": "id,name,phone"},
            )
            user_data = user_resp.json()
        except Exception as exc:
            logger.error("Zalo user info failed: %s", exc)
            return jsonify({"error": "Không thể lấy thông tin Zalo"}), 502

        zalo_user_id = user_data.get("id")
        if not zalo_user_id:
            return jsonify({"error": "Không lấy được Zalo user ID"}), 400

        phone = user_data.get("phone") or None
        if phone and phone.startswith("84") and len(phone) == 11:
            phone = "0" + phone[2:]

        return jsonify({
            "zalo_user_id": str(zalo_user_id),
            "name": user_data.get("name") or "",
            "phone": phone,
        })

    # ── OA Authorization (admin runs once) ──

    @bp.route("/authorize-oa", methods=["GET"])
    def authorize_oa():
        """Admin visits this URL to authorize OA → Zalo OA OAuth flow."""
        if not ZALO_APP_ID:
            return jsonify({"error": "ZALO_APP_ID not configured"}), 500

        redirect_uri = request.host_url.rstrip("/") + "/api/zalo/authorize-oa/callback"
        oauth_url = (
            f"https://oauth.zaloapp.com/v4/oa/permission"
            f"?app_id={ZALO_APP_ID}"
            f"&redirect_uri={redirect_uri}"
        )
        return redirect(oauth_url)

    @bp.route("/authorize-oa/callback", methods=["GET"])
    def authorize_oa_callback():
        """Zalo redirects here after OA admin authorizes."""
        code = request.args.get("code", "").strip()
        if not code:
            return jsonify({"error": "No authorization code received"}), 400

        redirect_uri = request.host_url.rstrip("/") + "/api/zalo/authorize-oa/callback"

        try:
            resp = _retry_request(
                "POST",
                "https://oauth.zaloapp.com/v4/oa/access_token",
                headers={"Content-Type": "application/x-www-form-urlencoded", "secret_key": ZALO_APP_SECRET},
                data={
                    "code": code,
                    "app_id": ZALO_APP_ID,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            result = resp.json()
        except Exception as exc:
            logger.error("OA token exchange failed: %s", exc)
            return jsonify({"error": f"Token exchange failed: {exc}"}), 502

        access_token = result.get("access_token")
        refresh_token = result.get("refresh_token")

        if not access_token:
            error = result.get("error_description") or result.get("error_name") or str(result)
            return jsonify({"error": f"OA authorization failed: {error}"}), 400

        token_data = {
            "access_token": access_token,
            "refresh_token": refresh_token or "",
            "expires_in": result.get("expires_in", 3600),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "authorized_at": datetime.now(timezone.utc).isoformat(),
        }

        _save_oa_token_to_firestore(token_data)
        with _oa_token_lock:
            _oa_token_cache.update(token_data)

        logger.info("OA authorized successfully, tokens saved")

        return (
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            "<h2 style='color:#43a047'>OA Authorization thanh cong!</h2>"
            "<p>Access token va refresh token da duoc luu vao Firestore.</p>"
            "<p>He thong se tu dong refresh token khi gan het han.</p>"
            "<p style='color:#999;margin-top:24px'>Ban co the dong tab nay.</p>"
            "</body></html>"
        )

    @bp.route("/oa-token-status", methods=["GET"])
    def oa_token_status():
        """Admin endpoint: check current OA token health."""
        data = _load_oa_token_from_firestore()
        if not data.get("access_token"):
            return jsonify({
                "status": "no_token",
                "has_env_fallback": bool(_ENV_OA_TOKEN),
                "action": "Truy cap /api/zalo/authorize-oa de authorize OA.",
            })

        refreshed_at = data.get("refreshed_at", "")
        expires_in = data.get("expires_in", 3600)
        elapsed = 0
        if refreshed_at:
            try:
                dt = datetime.fromisoformat(refreshed_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - dt).total_seconds()
            except Exception:
                pass

        return jsonify({
            "status": "active" if elapsed < expires_in else "expired",
            "has_refresh_token": bool(data.get("refresh_token")),
            "refreshed_at": refreshed_at,
            "authorized_at": data.get("authorized_at", ""),
            "expires_in": expires_in,
            "elapsed_seconds": int(elapsed),
            "token_preview": data["access_token"][:20] + "...",
        })

    return bp


# ── Public helpers ──

def send_zalo_cs_message(zalo_user_id: str, text: str) -> Dict[str, Any]:
    """Send CS message via Zalo OA. Auto-refreshes token on expiry."""
    token = get_oa_access_token()
    if not token:
        logger.warning("No OA access token available, skipping CS message")
        return {"skipped": True, "reason": "no_token"}

    try:
        resp = _retry_request(
            "POST",
            "https://openapi.zalo.me/v3.0/oa/message/cs",
            headers={"Content-Type": "application/json", "access_token": token},
            json={"recipient": {"user_id": zalo_user_id}, "message": {"text": text}},
        )
        result = resp.json()

        # Token expired mid-request → refresh once and retry
        if result.get("error") == -216:
            logger.info("OA token expired during CS message, refreshing...")
            cached = _load_oa_token_from_firestore()
            if cached.get("refresh_token"):
                try:
                    refreshed = _refresh_oa_token(cached["refresh_token"])
                    resp = _retry_request(
                        "POST",
                        "https://openapi.zalo.me/v3.0/oa/message/cs",
                        headers={"Content-Type": "application/json", "access_token": refreshed["access_token"]},
                        json={"recipient": {"user_id": zalo_user_id}, "message": {"text": text}},
                    )
                    result = resp.json()
                except Exception as exc:
                    logger.error("Refresh + retry CS message failed: %s", exc)

        if result.get("error") and result["error"] != 0:
            logger.error("Zalo CS message error: %s", result)
        else:
            logger.info("Zalo CS message sent to %s", zalo_user_id)
        return result
    except Exception as exc:
        logger.error("Zalo CS message failed: %s", exc)
        return {"error": str(exc)}


def rate_limit_check(ip: str) -> bool:
    now = time.time()
    last = _register_timestamps.get(ip, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return True
    _register_timestamps[ip] = now
    return False
