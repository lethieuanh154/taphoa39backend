"""WebSocket handlers removed — stubs kept for compatibility.

This module previously provided Flask-SocketIO Namespaces. All real-time
notifications were replaced by REST polling endpoints. The classes below are
lightweight stubs to avoid import errors in other modules that may still
reference these names.
"""

from __future__ import annotations

class ProductsNamespace:
    namespace = '/api/websocket/products'

    def __init__(self, *args, **kwargs):
        pass

    def on_connect(self):
        print('Products namespace stub connected')

    def on_disconnect(self):
        print('Products namespace stub disconnected')


class CustomersNamespace:
    namespace = '/api/websocket/customers'

    def on_connect(self):
        print('Customers namespace stub connected')

    def on_disconnect(self):
        print('Customers namespace stub disconnected')


class InvoicesNamespace:
    namespace = '/api/websocket/invoices'

    def on_connect(self):
        print('Invoices namespace stub connected')

    def on_disconnect(self):
        print('Invoices namespace stub disconnected')


class OrdersNamespace:
    namespace = '/api/websocket/orders'

    def on_connect(self):
        print('Orders namespace stub connected')

    def on_disconnect(self):
        print('Orders namespace stub disconnected')
