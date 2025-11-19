from __future__ import annotations

from flask_socketio import SocketIO

from routes.websocket_handlers import (
    CustomersNamespace,
    InvoicesNamespace,
    OrdersNamespace,
    ProductsNamespace,
)


def register_namespaces(socketio: SocketIO, product_service) -> None:
    socketio.on_namespace(ProductsNamespace(socketio, product_service))
    socketio.on_namespace(CustomersNamespace())
    socketio.on_namespace(InvoicesNamespace())
    socketio.on_namespace(OrdersNamespace())
