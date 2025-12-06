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
from routes.firebase_customers import create_firebase_customers_bp
from routes.firebase_invoices import create_firebase_invoices_bp
from routes.firebase_orders import create_firebase_orders_bp
from routes.firebase_products import create_firebase_products_bp
from routes.kiotviet_routes import create_kiotviet_routes_bp
from routes.sync_routes import create_sync_routes_bp
from routes.static_routes import create_static_routes_bp
from routes.firebase_websocket import register_namespaces
from routes.auth_routes import auth_bp

# SocketIO middleware removed — websockets are no longer used.


def _build_app() -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/*": {"origins": "*"}})

    product_service = FirestoreProductService(Cache())
    invoice_service = FirestoreInvoiceService(Cache())
    customer_service = FirestoreCustomerService(Cache())
    order_service = FirestoreorderService(Cache())

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
        # Allow both polling and websocket, but frontend will use polling only
        transports=['polling', 'websocket']
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
    app.register_blueprint(create_firebase_orders_bp(order_service, socketio))

    # Attach socketio to app for external use if needed
    app.socketio = socketio

    return app


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
