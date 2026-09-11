from __future__ import annotations

import os
from typing import Dict, Tuple

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

from firebase.firebase_service.cache import Cache
from firebase.firebase_service.customer_service import FirestoreCustomerService
from firebase.firebase_service.invoice_service import FirestoreInvoiceService
from firebase.firebase_service.order_service import FirestoreorderService
from firebase.firebase_service.product_service import FirestoreProductService
from firebase.firebase_service.employee_service import FirestoreEmployeeService
from routes.firebase_customers import create_firebase_customers_bp
from routes.firebase_invoices import create_firebase_invoices_bp
from routes.firebase_orders import create_firebase_orders_bp
from routes.firebase_products import create_firebase_products_bp
from routes.firebase_employees import create_firebase_employees_bp
from routes.kiotviet_routes import create_kiotviet_routes_bp
from routes.kiotviet_campaign import create_kiotviet_campaign_bp
from routes.sync_routes import create_sync_routes_bp
from routes.static_routes import create_static_routes_bp
from routes.firebase_websocket import register_namespaces
from routes.auth_routes import auth_bp
from routes.invoice_processing import create_invoice_processing_bp
from routes.invoice_routes_v2 import create_invoice_routes_v2, create_invoice_legacy_routes
from routes.product_mapping_routes import create_product_mapping_routes

from routes.osrm_proxy_routes import bp as osrm_proxy_bp
from routes.product_history_routes import bp as product_history_bp
from routes.firebase_merged_products import create_firebase_merged_products_bp
from routes.customer_registration import create_customer_registration_bp
from routes.zalo_routes import create_zalo_routes_bp
from routes.gmail_routes import create_gmail_routes_bp
from routes.merged_products_audit_routes import create_merged_products_audit_bp
from routes.chat_routes import create_chat_routes_bp
from firebase.firebase_service.chat_service import FirestoreChatService
from firebase.firebase_service.promotion_service import FirestorePromotionService
from routes.firebase_promotions import create_firebase_promotions_bp
from routes.firebase_public import create_firebase_public_bp
from routes.invoice_public import create_invoice_public_bp
from routes.provisional_invoices import create_provisional_invoices_bp
from routes.admin_auth import register_admin_auth


def _build_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    product_service = FirestoreProductService(Cache())
    invoice_service = FirestoreInvoiceService(Cache())
    customer_service = FirestoreCustomerService(Cache())
    order_service = FirestoreorderService(Cache())
    employee_service = FirestoreEmployeeService(Cache())
    promotion_service = FirestorePromotionService(Cache())

    # Initialize SocketIO without async_mode (uses threading by default)
    # Frontend uses polling transport only, so no WebSocket needed
    # This avoids eventlet monkey patching issues that can block REST APIs
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        logger=False,
        engineio_logger=False,
        ping_timeout=60,
        ping_interval=25,
        # Only allow polling - Werkzeug dev server doesn't support WebSocket in threading mode
        transports=['polling']
    )

    # Register Socket.IO namespaces so clients can connect and receive events
    try:
        register_namespaces(socketio)
    except Exception:
        # best-effort registration; avoid crashing startup if socketio not available
        pass
    app.register_blueprint(auth_bp)
    app.register_blueprint(create_static_routes_bp())
    app.register_blueprint(create_kiotviet_routes_bp())
    app.register_blueprint(create_kiotviet_campaign_bp())
    app.register_blueprint(create_sync_routes_bp(product_service))
    app.register_blueprint(create_firebase_products_bp(product_service, socketio))
    app.register_blueprint(
        create_firebase_invoices_bp(
            invoice_service,
            product_service,
            customer_service,
            socketio,
        )
    )
    app.register_blueprint(create_firebase_customers_bp(customer_service, socketio))
    app.register_blueprint(create_firebase_orders_bp(order_service, customer_service, socketio))
    app.register_blueprint(create_firebase_employees_bp(employee_service, socketio))
    app.register_blueprint(create_invoice_processing_bp())
    app.register_blueprint(create_invoice_processing_bp('/api/v1', 'invoice_processing_api'))
    app.register_blueprint(create_invoice_routes_v2())
    app.register_blueprint(create_invoice_legacy_routes())
    app.register_blueprint(create_product_mapping_routes())
    app.register_blueprint(product_history_bp)
    app.register_blueprint(create_firebase_merged_products_bp(socketio))
    app.register_blueprint(create_customer_registration_bp(customer_service, socketio))
    app.register_blueprint(create_zalo_routes_bp())
    app.register_blueprint(create_gmail_routes_bp())

    # Promotions (khuyến mại)
    app.register_blueprint(create_firebase_promotions_bp(promotion_service, product_service, socketio))

    # Public API cho app DatHang (che giấu dữ liệu nội bộ: Cost, OnHandNV, kiotViet...)
    app.register_blueprint(create_firebase_public_bp(
        product_service, promotion_service, order_service, customer_service, socketio
    ))

    # Trang hoa don dien tu cho khach (/hd/<token>) - public, bao ve bang token ngau nhien
    app.register_blueprint(create_provisional_invoices_bp(socketio))
    app.register_blueprint(create_invoice_public_bp(invoice_service))

    # Chat messaging
    chat_service = FirestoreChatService()
    app.register_blueprint(create_chat_routes_bp(chat_service, socketio, customer_service))

    # OSRM routing proxy (avoids CORS from browser)
    app.register_blueprint(osrm_proxy_bp)

    # Merged products audit (lightweight backup)
    audit_bp, audit_service = create_merged_products_audit_bp()
    app.register_blueprint(audit_bp)

    # Admin auth gate (mac dinh log-only; bat ENFORCE_ADMIN_AUTH=true de chan)
    register_admin_auth(app)

    # Attach socketio to app for external use if needed
    app.socketio = socketio

    # Pre-warm product cache to avoid 17s cold start on first search/featured request
    _warmup_product_cache(product_service)

    # Schedule daily audit cleanup at 5:00 AM
    _schedule_audit_cleanup(audit_service)

    return app


def _warmup_product_cache(product_service):
    """Pre-warm product cache and schedule background refresh every 55 minutes.
    TTL cache = 1h, refresh at 55min = cache luôn warm, không có cold miss."""
    import threading
    import time

    REFRESH_INTERVAL = 55 * 60  # 55 phút (trước khi TTL 1h hết hạn)

    def _refresh_cache():
        try:
            t0 = time.time()
            # Fetch xong MOI swap vao cache. KHONG invalidate truoc: lam vay thi trong
            # 18-20s fetch, cache rong -> moi request khach tu keo full scan rieng
            # (stampede -> refresh phinh 18s len 234s roi fail, prod 11/09/2026).
            products = product_service.refresh_all_products_cache()
            elapsed = (time.time() - t0) * 1000
            print(f"🔄 [CacheRefresh] Refreshed {len(products)} products in {elapsed:.0f}ms")
        except Exception as e:
            print(f"❌ [CacheRefresh] Failed: {e}")
        # Danh muc: goi KiotViet o thread nen, KHONG bao gio trong request khach
        try:
            product_service.refresh_categories_from_kiotviet()
        except Exception as e:
            print(f"❌ [CacheRefresh] Categories failed: {e}")

    def _warmup_and_schedule():
        # Initial warmup
        try:
            t0 = time.time()
            products = product_service.read_all_products(include_inactive=False, include_deleted=False)
            elapsed = (time.time() - t0) * 1000
            print(f"🔥 [Warmup] Product cache loaded: {len(products)} products in {elapsed:.0f}ms")
        except Exception as e:
            print(f"❌ [Warmup] Product cache warmup failed: {e}")

        try:
            product_service.refresh_categories_from_kiotviet()
        except Exception as e:
            print(f"❌ [Warmup] Categories warmup failed: {e}")

        # Schedule periodic refresh
        while True:
            time.sleep(REFRESH_INTERVAL)
            _refresh_cache()

    thread = threading.Thread(target=_warmup_and_schedule, daemon=True)
    thread.start()
    print(f"⏰ [CacheRefresh] Scheduled every {REFRESH_INTERVAL // 60} minutes")


def _schedule_audit_cleanup(audit_service):
    """Schedule daily cleanup of old audit documents at 5:00 AM."""
    import threading
    from datetime import datetime, timedelta

    def _run_cleanup():
        try:
            result = audit_service.clear_old_audits()
            print(f"🧹 [Scheduler] Audit cleanup: {result}")
        except Exception as e:
            print(f"❌ [Scheduler] Audit cleanup failed: {e}")
        # Re-schedule for next 5:00 AM
        _schedule_next()

    def _schedule_next():
        now = datetime.now()
        next_run = now.replace(hour=5, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        delay = (next_run - now).total_seconds()
        timer = threading.Timer(delay, _run_cleanup)
        timer.daemon = True
        timer.start()
        print(f"⏰ [Scheduler] Next audit cleanup at {next_run.strftime('%Y-%m-%d %H:%M')} ({delay:.0f}s)")

    _schedule_next()


app = _build_app()


if __name__ == "__main__":
    env = os.getenv("e", "prod")
    port = 8000 if env == "prod" else 5000
    print(f"\n{'='*60}")
    print(f"Starting server in {env.upper()} mode on port {port}")
    print(f"Socket.IO: Polling transport (threading mode)")
    print(f"Server URL: http://0.0.0.0:{port}")
    print(f"{'='*60}\n")

    # Use socketio.run() which handles both regular HTTP and Socket.IO
    # Using threading mode (default) instead of eventlet to avoid blocking REST APIs
    app.socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,  # Disable debug to prevent blocking
        use_reloader=False,  # Disable reloader for stability
        log_output=True,  # Show request logs
        allow_unsafe_werkzeug=True
    )
