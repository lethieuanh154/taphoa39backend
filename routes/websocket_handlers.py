from __future__ import annotations

from flask_socketio import Namespace, SocketIO, emit

from routes.shared import (
    apply_product_updates,
    broadcast_products_onhand_updated,
    normalize_product_updates,
)


class ProductsNamespace(Namespace):
    namespace = '/api/websocket/products'

    def __init__(self, socketio: SocketIO, product_service):
        super().__init__(self.namespace)
        self.socketio = socketio
        self.product_service = product_service

    def on_connect(self):
        print('Client connected to products websocket')

    def on_disconnect(self):
        print('Client disconnected from products websocket')

    def on_products_onhand_update_request(self, payload):
        try:
            items_payload = payload
            if isinstance(payload, dict) and 'products' in payload:
                items_payload = payload.get('products')

            if items_payload is None:
                emit('products_onhand_update_ack', {'ok': False, 'error': 'no items provided'})
                return

            normalized = normalize_product_updates(items_payload)
            results, broadcast_updates = apply_product_updates(self.product_service, normalized)

            if broadcast_updates:
                broadcast_products_onhand_updated(self.socketio, broadcast_updates)

            successes = [r for r in results if isinstance(r.get('result'), dict)]
            failures = [r for r in results if r not in successes]

            response = {'ok': bool(successes), 'count': len(successes)}
            if failures:
                response['errors'] = failures

            emit('products_onhand_update_ack', response)
        except ValueError as exc:
            emit('products_onhand_update_ack', {'ok': False, 'error': str(exc)})
        except Exception as exc:  # pragma: no cover - best effort logging
            import traceback
            print(traceback.format_exc())
            emit('products_onhand_update_ack', {'ok': False, 'error': str(exc)})


class CustomersNamespace(Namespace):
    namespace = '/api/websocket/customers'

    def on_connect(self):
        print('Client connected to customers websocket')

    def on_disconnect(self):
        print('Client disconnected from customers websocket')


class InvoicesNamespace(Namespace):
    namespace = '/api/websocket/invoices'

    def on_connect(self):
        print('Client connected to invoices websocket')
        emit('message', {'data': 'Connected to invoices WebSocket'})

    def on_disconnect(self):
        print('Client disconnected from invoices websocket')


class OrdersNamespace(Namespace):
    namespace = '/api/websocket/orders'

    def on_connect(self):
        print('Client connected to orders websocket')
        emit('message', {'data': 'Connected to orders WebSocket'})

    def on_disconnect(self):
        print('Client disconnected from orders websocket')
