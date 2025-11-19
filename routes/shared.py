from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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
    if not fields:
        return

    payload = {'productId': str(product_id)}

    def copy_field(src_key: str, dest_key: Optional[str] = None) -> None:
        if src_key in fields and fields[src_key] is not None:
            payload[dest_key or src_key] = fields[src_key]

    copy_field('OnHand', 'onHand')
    copy_field('onHand', 'onHand')
    copy_field('BasePrice', 'basePrice')
    copy_field('basePrice', 'basePrice')
    copy_field('Cost', 'cost')
    copy_field('cost', 'cost')
    copy_field('Code', 'code')
    copy_field('code', 'code')
    copy_field('FullName', 'fullName')
    copy_field('fullName', 'fullName')
    copy_field('Name', 'name')
    copy_field('name', 'name')

    if len(payload) > 1:
        socketio.emit('product_onhand_updated', payload, namespace='/api/websocket/products')


def broadcast_products_onhand_updated(socketio, updates: Iterable[Dict[str, Any]]):
    updates_list = list(updates)
    if not updates_list:
        return

    socketio.emit('products_onhand_updated', updates_list, namespace='/api/websocket/products')
    for item in updates_list:
        pid = item.get('Id') or item.get('productId')
        if pid is None:
            continue
        fields = {k: v for k, v in item.items() if k not in UPDATE_ID_KEYS}
        notify_product_onhand_updated(socketio, pid, fields)


def broadcast_customer_updates(socketio, results: Iterable[Dict[str, Any]]):
    if not results:
        return

    batch_payload: List[Dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict) or not result.get('applied'):
            continue

        customer_data = result.get('customer')
        if not customer_data:
            continue

        batch_payload.append(customer_data)
        socketio.emit('customer_updated', customer_data, namespace='/api/websocket/customers')

    if batch_payload:
        socketio.emit('customers_updated', batch_payload, namespace='/api/websocket/customers')


def notify_customer_created(socketio, customer: Dict[str, Any]):
    if not isinstance(customer, dict):
        return
    socketio.emit('customer_created', customer, namespace='/api/websocket/customers')


def notify_invoice_updated(socketio, invoice: Dict[str, Any]):
    socketio.emit('invoice_updated', {'data': invoice}, namespace='/api/websocket/invoices')


def notify_invoice_deleted(socketio, invoice_id: Any):
    socketio.emit('invoice_deleted', {'data': invoice_id}, namespace='/api/websocket/invoices')


def notify_invoice_created(socketio, invoice: Dict[str, Any]):
    socketio.emit('invoice_created', {'data': invoice}, namespace='/api/websocket/invoices')


def notify_order_created(socketio, order: Dict[str, Any]):
    socketio.emit('order_created', {'data': order}, namespace='/api/websocket/orders')


def notify_order_updated(socketio, order: Dict[str, Any]):
    socketio.emit('order_updated', {'data': order}, namespace='/api/websocket/orders')


def notify_order_deleted(socketio, order_id: Any):
    socketio.emit('order_deleted', {'data': order_id}, namespace='/api/websocket/orders')


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
