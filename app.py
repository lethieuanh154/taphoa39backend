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
from routes.firebase_websocket import register_namespaces
from routes.kiotviet_routes import create_kiotviet_routes_bp
from routes.sync_routes import create_sync_routes_bp
from routes.static_routes import create_static_routes_bp


class SocketIOPathAliasMiddleware:
    """Rewrite alternate Socket.IO paths to the canonical engine path."""

    def __init__(self, app, aliases: Dict[str, str]):
        self._app = app
        self._aliases = aliases

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "") or ""
        for alias, target in self._aliases.items():
            if path.startswith(alias) and not path.startswith(target):
                suffix = path[len(alias) :]
                environ["PATH_INFO"] = f"{target}{suffix}"
                request_uri = environ.get("REQUEST_URI")
                if request_uri and request_uri.startswith(alias):
                    environ["REQUEST_URI"] = f"{target}{request_uri[len(alias):]}"
                raw_uri = environ.get("RAW_URI")
                if raw_uri and raw_uri.startswith(alias):
                    environ["RAW_URI"] = f"{target}{raw_uri[len(alias):]}"
                break
        return self._app(environ, start_response)


def _build_app() -> Tuple[Flask, SocketIO]:
    app = Flask(__name__)
    CORS(app, resources={r"/*": {"origins": "*"}})

    product_service = FirestoreProductService(Cache())
    invoice_service = FirestoreInvoiceService(Cache())
    customer_service = FirestoreCustomerService(Cache())
    order_service = FirestoreorderService(Cache())

    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        engineio_logger=False,
        logger=False,
        path="/api/websocket/socket.io",
    )

    app.wsgi_app = SocketIOPathAliasMiddleware(
        app.wsgi_app,
        {
            "/socket.io": "/api/websocket/socket.io",
            "/socket.io/": "/api/websocket/socket.io/",
        },
    )

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

    register_namespaces(socketio, product_service)

    return app, socketio


app, socketio = _build_app()


if __name__ == "__main__":
    env = os.getenv("e", "prod")
    port = 8000 if env == "prod" else 5000
    print(f"Running in {env.upper()} mode on port {port}")
    socketio.run(app, host="0.0.0.0", port=port)
