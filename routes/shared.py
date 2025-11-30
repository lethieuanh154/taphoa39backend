from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from functools import wraps
from flask import jsonify, request
from google.api_core.exceptions import ResourceExhausted
import traceback

from routes.firebase_websocket import set_last_notify

UPDATE_ID_KEYS: Tuple[str, ...] = ("Id", "id", "productId", "ProductId")
ONHAND_KEYS: Tuple[str, ...] = ("OnHand", "onHand", "onhand")


def norm_id(data: Dict[str, Any]) -> Optional[Any]:
    for key in UPDATE_ID_KEYS:
        if key in data and data[key] is not None:
            return data[key]
    return None


def norm_onhand(data: Dict[str, Any]) -> Optional[Any]:
    for key in ONHAND_KEYS:
        if key in data:
            return data.get(key)
    return None


def is_valid_pid(pid: Optional[Any]) -> bool:
    if pid is None:
        return False
    pid_str = str(pid).strip()
    if pid_str in ("", "productId", "onHand", "OnHand", "Id", "id"):
        return False
    return pid_str.isdigit()


def to_number(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize_product_updates(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        normalized: List[Dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Each list item must be an object")
            pid = norm_id(item)
            fields = {
                key: value
                for key, value in item.items()
                if key not in UPDATE_ID_KEYS
            }
            normalized.append({
                "Id": str(pid) if pid is not None else None,
                "fields": fields,
            })
        return normalized

    if isinstance(payload, dict):
        if any(key in payload for key in UPDATE_ID_KEYS):
            pid = norm_id(payload)
            fields = {
                key: value
                for key, value in payload.items()
                if key not in UPDATE_ID_KEYS
            }
            return [{
                "Id": str(pid) if pid is not None else None,
                "fields": fields,
            }]

        normalized = []
        for key, value in payload.items():
            if isinstance(value, dict):
                fields = dict(value)
            else:
                fields = {"OnHand": value}
            normalized.append({"Id": str(key), "fields": fields})
        return normalized

    raise ValueError("Unsupported JSON body type")


def apply_product_updates(product_service, normalized_items: Iterable[Dict[str, Any]]):
    results: List[Dict[str, Any]] = []
    broadcast_updates: List[Dict[str, Any]] = []

    for item in normalized_items:
        pid = item.get("Id")

        if not is_valid_pid(pid):
            results.append({"id": pid, "result": "invalid_id"})
            continue

        raw_fields = item.get("fields") or {}
        if not isinstance(raw_fields, dict) or len(raw_fields) == 0:
            results.append({"id": pid, "result": "no_fields"})
            continue

        updates: Dict[str, Any] = {}
        invalid_onhand = False
        broadcast_fields: Dict[str, Any] = {}

        for key, value in raw_fields.items():
            if key in ONHAND_KEYS:
                converted = to_number(value)
                if converted is None:
                    invalid_onhand = True
                    continue
                updates["OnHand"] = converted
                broadcast_fields["OnHand"] = converted
            else:
                updates[key] = value
                broadcast_fields[key] = value

        if not updates:
            if invalid_onhand:
                results.append({"id": pid, "result": "invalid_onhand"})
            else:
                results.append({"id": pid, "result": "no_updates"})
            continue

        try:
            update_result = product_service.update_product(pid, updates)
            result_entry = {"id": pid, "result": update_result}
            if invalid_onhand:
                result_entry["warning"] = "invalid_onhand"
            results.append(result_entry)

            if broadcast_fields:
                entry = {"Id": pid}
                entry.update(broadcast_fields)
                broadcast_updates.append(entry)
        except Exception as exc:  # pragma: no cover - best effort logging
            import traceback
            print(f"Error updating product {pid}: {exc}")
            print(traceback.format_exc())
            results.append({"id": pid, "result": f"error: {str(exc)}"})

    return results, broadcast_updates


def notify_product_onhand_updated(socketio, product_id: Any, fields: Dict[str, Any]):
    # Emit a minimal notification so clients know to fetch fresh product data.
    if not socketio:
        return
    socketio.emit('product_onhand_updated', {'productId': str(product_id)}, namespace='/api/websocket/products')


def broadcast_products_onhand_updated(socketio, updates: Iterable[Dict[str, Any]]):
    updates_list = list(updates)
    if not updates_list:
        return
    # Emit only product IDs; clients should call GET /api/firebase/get/products/<id> or
    # use `GET /api/firebase/products/latest` to refresh data.
    ids = []
    for item in updates_list:
        pid = item.get('Id') or item.get('productId')
        if pid is None:
            continue
        ids.append(str(pid))

    if not socketio:
        return
    socketio.emit('products_onhand_updated', ids, namespace='/api/websocket/products')
    for pid in ids:
        notify_product_onhand_updated(socketio, pid, {})


def broadcast_customer_updates(socketio, results: Iterable[Dict[str, Any]]):
    if not results:
        return
    # Emit only customer IDs so clients will fetch fresh customer data.
    ids: List[str] = []
    for result in results:
        if not isinstance(result, dict) or not result.get('applied'):
            continue
        customer_data = result.get('customer')
        if not isinstance(customer_data, dict):
            continue
        cid = customer_data.get('Id') or customer_data.get('id')
        if cid is None:
            continue
        cid_str = str(cid)
        ids.append(cid_str)
        if socketio:
            socketio.emit('customer_updated', {'id': cid_str}, namespace='/api/websocket/customers')

    if ids and socketio:
        socketio.emit('customers_updated', ids, namespace='/api/websocket/customers')


def notify_customer_created(socketio, customer: Dict[str, Any]):
    if not isinstance(customer, dict):
        return
    cid = customer.get('Id') or customer.get('id')
    if cid is None:
        return
    if not socketio:
        return
    socketio.emit('customer_created', {'id': str(cid)}, namespace='/api/websocket/customers')


def notify_invoice_updated(socketio, invoice: Dict[str, Any]):
    if isinstance(invoice, dict):
        iid = invoice.get('Id') or invoice.get('id')
    else:
        iid = invoice
    if iid is None:
        return
    if not socketio:
        return
    socketio.emit('invoice_updated', {'id': str(iid)}, namespace='/api/websocket/invoices')
    try:
        set_last_notify('/api/websocket/invoices', 'invoice_updated', {'id': str(iid)})
    except Exception:
        pass


def notify_invoice_deleted(socketio, invoice_id: Any):
    if not socketio:
        return
    socketio.emit('invoice_deleted', {'id': str(invoice_id)}, namespace='/api/websocket/invoices')
    try:
        set_last_notify('/api/websocket/invoices', 'invoice_deleted', {'id': str(invoice_id)})
    except Exception:
        pass


def notify_invoice_created(socketio, invoice: Dict[str, Any]):
    if isinstance(invoice, dict):
        iid = invoice.get('Id') or invoice.get('id')
    else:
        iid = invoice
    if iid is None:
        return
    if not socketio:
        return
    socketio.emit('invoice_created', {'id': str(iid)}, namespace='/api/websocket/invoices')
    try:
        set_last_notify('/api/websocket/invoices', 'invoice_created', {'id': str(iid)})
    except Exception:
        pass


def notify_order_created(socketio, order: Dict[str, Any]):
    if isinstance(order, dict):
        oid = order.get('Id') or order.get('id')
    else:
        oid = order
    if oid is None:
        return
    if not socketio:
        return
    socketio.emit('order_created', {'id': str(oid)}, namespace='/api/websocket/orders')
    try:
        set_last_notify('/api/websocket/orders', 'order_created', {'id': str(oid)})
    except Exception:
        pass


def notify_order_updated(socketio, order: Dict[str, Any]):
    if isinstance(order, dict):
        oid = order.get('Id') or order.get('id')
    else:
        oid = order
    if oid is None:
        return
    if not socketio:
        return
    socketio.emit('order_updated', {'id': str(oid)}, namespace='/api/websocket/orders')
    try:
        set_last_notify('/api/websocket/orders', 'order_updated', {'id': str(oid)})
    except Exception:
        pass


def notify_order_deleted(socketio, order_id: Any):
    if not socketio:
        return
    socketio.emit('order_deleted', {'id': str(order_id)}, namespace='/api/websocket/orders')
    try:
        set_last_notify('/api/websocket/orders', 'order_deleted', {'id': str(order_id)})
    except Exception:
        pass


def notify_daily_summary(socketio, date: str, summary: Dict[str, Any]):
    payload = {'date': date, 'summary': summary if summary is not None else {}}
    if not socketio:
        return
    socketio.emit('daily_summary', payload, namespace='/api/websocket/invoices')
    try:
        set_last_notify('/api/websocket/invoices', 'daily_summary', payload)
    except Exception:
        pass


def notify_monthly_summary(socketio, year: str, month: str, summary: Dict[str, Any]):
    payload = {'year': year, 'month': month, 'summary': summary if summary is not None else {}}
    if not socketio:
        return
    socketio.emit('monthly_summary', payload, namespace='/api/websocket/invoices')
    try:
        set_last_notify('/api/websocket/invoices', 'monthly_summary', payload)
    except Exception:
        pass


def notify_yearly_summary(socketio, year: str, summary: Dict[str, Any]):
    payload = {'year': year, 'summary': summary if summary is not None else {}}
    if not socketio:
        return
    socketio.emit('yearly_summary', payload, namespace='/api/websocket/invoices')
    try:
        set_last_notify('/api/websocket/invoices', 'yearly_summary', payload)
    except Exception:
        pass


def notify_top_products(socketio, filters: Dict[str, Any], products: List[Dict[str, Any]]):
    payload = {'filters': filters, 'products': products}
    if not socketio:
        return
    socketio.emit('top_products', payload, namespace='/api/websocket/invoices')
    try:
        set_last_notify('/api/websocket/invoices', 'top_products', payload)
    except Exception:
        pass


def safe_float(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def safe_int(val: Any) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def collect_customer_ids_from_invoice(invoice: Dict[str, Any]) -> Set[Any]:
    customer_ids: Set[Any] = set()
    if not isinstance(invoice, dict):
        return customer_ids

    for key in ("customerId", "CustomerId", "customer_id"):
        value = invoice.get(key)
        if value is not None and str(value).strip():
            customer_ids.add(value)

    customer_info = invoice.get('customer')
    if isinstance(customer_info, dict):
        for key in ("Id", "id", "CustomerId"):
            value = customer_info.get(key)
            if value is not None and str(value).strip():
                customer_ids.add(value)

    return customer_ids


def invalidate_invoice_cache(customer_service, invoice: Dict[str, Any]):
    customer_ids = collect_customer_ids_from_invoice(invoice)
    if customer_ids:
        customer_service.invalidate_invoices_cache(customer_ids)


# ============================================================================
# ERROR HANDLING UTILITIES
# ============================================================================

def handle_api_errors(f: Callable) -> Callable:
    """
    Decorator for consistent error handling in Flask routes.

    Handles:
    - ResourceExhausted (Firestore quota) -> 429
    - ValueError -> 400
    - KeyError -> 400
    - General exceptions -> 500

    Usage:
        @bp.route('/endpoint')
        @handle_api_errors
        def my_endpoint():
            return jsonify({"status": "success"})
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ResourceExhausted as exc:
            print(traceback.format_exc())
            return jsonify({
                "status": "error",
                "message": "Firestore quota exceeded",
                "details": str(exc)
            }), 429
        except ValueError as exc:
            print(traceback.format_exc())
            return jsonify({
                "status": "error",
                "message": str(exc)
            }), 400
        except KeyError as exc:
            print(traceback.format_exc())
            return jsonify({
                "status": "error",
                "message": f"Missing required field: {str(exc)}"
            }), 400
        except Exception as exc:
            print(traceback.format_exc())
            return jsonify({
                "status": "error",
                "message": str(exc),
                "trace": traceback.format_exc()
            }), 500
    return decorated


# ============================================================================
# FETCH ENDPOINT FACTORY
# ============================================================================

def create_fetch_handler(service, read_method_name: str = "read_all"):
    """
    Factory function to create a fetch endpoint handler for any resource.

    Accepts JSON: { "id": "123" } or { "ids": ["1","2"] }
    Returns the latest document(s) from Firestore.

    Args:
        service: The service instance (e.g., customer_service, product_service)
        read_method_name: Name of the method to read all items (default: "read_all")

    Returns:
        Flask route handler function

    Usage:
        @bp.route("/customers/fetch", methods=["POST"])
        def fetch_customers():
            return create_fetch_handler(customer_service, "read_all_customers")()
    """
    @handle_api_errors
    def fetch_handler():
        payload = request.get_json(silent=True) or {}
        ids = []

        # Extract IDs from payload
        if isinstance(payload, dict) and payload.get("id"):
            ids = [str(payload.get("id"))]
        elif isinstance(payload, dict) and payload.get("ids"):
            ids = [str(i) for i in payload.get("ids") if i is not None]
        else:
            return jsonify({
                "status": "error",
                "message": "Provide 'id' or 'ids' in JSON body"
            }), 400

        # Get all items and create lookup dictionary
        read_all_method = getattr(service, read_method_name, None)
        if not read_all_method:
            raise ValueError(f"Service method '{read_method_name}' not found")

        all_items = read_all_method() or []

        # Build lookup by Id/id field
        lookup = {}
        for item in all_items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get('Id') or item.get('id'))
            if item_id:
                lookup[item_id] = item

        # Find matching items
        results = []
        for item_id in ids:
            if item_id in lookup:
                results.append(lookup[item_id])

        # Return single item or array
        if len(results) == 1:
            return jsonify(results[0])
        return jsonify(results)

    return fetch_handler


def create_simple_fetch_handler(service, read_single_method_name: str):
    """
    Simplified fetch handler that reads items one by one.
    Use this when you don't need to load all items into memory.

    Args:
        service: The service instance
        read_single_method_name: Name of the method to read a single item (e.g., "read_product")

    Returns:
        Flask route handler function

    Usage:
        @bp.route("/products/fetch", methods=["POST"])
        def fetch_products():
            return create_simple_fetch_handler(product_service, "read_product")()
    """
    @handle_api_errors
    def fetch_handler():
        payload = request.get_json(silent=True) or {}
        ids = []

        # Extract IDs from payload
        if isinstance(payload, dict) and payload.get("id"):
            ids = [str(payload.get("id"))]
        elif isinstance(payload, dict) and payload.get("ids"):
            ids = [str(i) for i in payload.get("ids") if i is not None]
        else:
            return jsonify({
                "status": "error",
                "message": "Provide 'id' or 'ids' in JSON body"
            }), 400

        # Get read method
        read_method = getattr(service, read_single_method_name, None)
        if not read_method:
            raise ValueError(f"Service method '{read_single_method_name}' not found")

        # Read items
        results = []
        for item_id in ids:
            item = read_method(str(item_id))
            if item:
                results.append(item)

        # Return single item or array
        if len(results) == 1:
            return jsonify(results[0])
        return jsonify(results)

    return fetch_handler
