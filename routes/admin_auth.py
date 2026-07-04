from __future__ import annotations

import os
import re

from flask import jsonify, request

from firebase.firebase_auth.auth_firebase_setup import verify_firebase_token

# Path PUBLIC (app khach DatHang) hoac tu co auth rieng -> KHONG gate
_SKIP_PREFIXES = (
    "/api/public/",
    "/api/chat/",
    "/api/websocket/",
    "/api/auth/",                    # login/verify/refresh (co logic rieng)
    "/api/gmail/",                   # dung token Firestore rieng
    "/api/kiotviet/categories",
    "/api/kiotviet/product-images",
    "/api/item/",
    "/api/osrm",
)
_SKIP_EXACT = ("/api/firebase/promotions/apply",)
_ORDER_BY_ID = re.compile(r"^/api/firebase/orders/[^/]+$")


def is_gated(method: str, path: str) -> bool:
    """True neu endpoint la ADMIN (can auth). False neu public/skip."""
    if method == "OPTIONS" or not path.startswith("/api/"):
        return False
    if path.startswith(_SKIP_PREFIXES) or path in _SKIP_EXACT:
        return False
    if method == "GET" and _ORDER_BY_ID.match(path):
        return False  # DatHang xem 1 don (trang confirm)
    return True


def _extract_id_token(req) -> str | None:
    tok = req.headers.get("X-Id-Token")
    if tok:
        return tok.strip()
    auth = req.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth.split("Bearer ", 1)[1].strip()
    return None


def register_admin_auth(app) -> None:
    """Gate cac endpoint admin bang Firebase ID token.
    ENFORCE_ADMIN_AUTH=false (mac dinh): chi LOG WARN, KHONG chan -> deploy an toan.
    Sau khi FE (Management/BanHang) gui X-Id-Token va log het WARN -> dat =true de enforce."""
    enforce = os.getenv("ENFORCE_ADMIN_AUTH", "false").lower() in ("1", "true", "yes")
    print(f"[admin-auth] middleware active (enforce={enforce})")

    @app.before_request
    def _admin_gate():
        if not is_gated(request.method, request.path):
            return None

        token = _extract_id_token(request)
        user = None
        if token:
            try:
                user = verify_firebase_token(token)
            except Exception:
                user = None

        if not user:
            print(f"[admin-auth] {'BLOCK' if enforce else 'WARN(off)'} "
                  f"{request.method} {request.path} ip={request.remote_addr}")
            if enforce:
                return jsonify({"error": "Unauthorized - admin auth required"}), 401
        else:
            request.admin_user = user
        return None
