from __future__ import annotations

from flask import Blueprint, jsonify, request
from routes.shared import (
    create_simple_fetch_handler,
    handle_api_errors,
    notify_order_created,
    notify_order_deleted,
    notify_order_updated,
)
from firebase.firebase_service.order_notification_service import notify_order_realtime


def create_firebase_orders_bp(order_service, customer_service, socketio) -> Blueprint:
    bp = Blueprint("firebase_orders", __name__, url_prefix="/api/firebase")

    @bp.route("/orders", methods=["GET"])
    @handle_api_errors
    def get_all_orders():
        orders = order_service.read_all_orders()
        return jsonify(orders)

    @bp.route("/orders/<order_id>", methods=["GET"])
    @handle_api_errors
    def get_order_by_id(order_id: str):
        order = order_service.read_order(order_id)
        if order:
            return jsonify(order)
        return jsonify({"status": "error", "message": "Order not found"}), 404

    @bp.route("/add_order", methods=["POST"])
    def add_order():
        order = request.json
        result = order_service.add_order(order)

        # Deduct redeemed points from customer if points were used
        _deduct_redeemed_points(order, customer_service)

        # Try to determine the persisted order id and fetch the stored document
        order_id = None
        if isinstance(result, dict):
            order_id = result.get('id') or result.get('Id')
        if not order_id:
            order_id = order.get('id') if isinstance(order, dict) else None
            if not order_id:
                order_id = order.get('Id') if isinstance(order, dict) else None

        if order_id:
            try:
                persisted = order_service.read_order(str(order_id))
                if persisted:
                    notify_order_created(socketio, persisted)
                    notify_order_realtime('created', persisted)
                else:
                    notify_order_created(socketio, order_id)
                    notify_order_realtime('created', order)
            except Exception:
                notify_order_created(socketio, order_id or order)
                notify_order_realtime('created', order)

        return jsonify(result)

    @bp.route("/update_order/<order_id>", methods=["PUT"])
    def update_order(order_id: str):
        updates = request.json
        result = order_service.update_order(order_id, updates)
        updated_order = order_service.read_order(order_id)
        if updated_order:
            notify_order_updated(socketio, updated_order)
            notify_order_realtime('updated', updated_order)
        return jsonify(result)

    @bp.route("/orders/<order_id>", methods=["DELETE"])
    def delete_order(order_id: str):
        result = order_service.delete_order(order_id)
        notify_order_deleted(socketio, order_id)
        notify_order_realtime('deleted', None, order_id=order_id)
        return jsonify(result)

    @bp.route("/orders/fetch", methods=["POST"])
    def fetch_orders_changed():
        """
        Accepts JSON: { "id": "123" } or { "ids": ["1","2"] }
        Returns the latest order document(s) from Firestore.
        """
        return create_simple_fetch_handler(order_service, "read_order")()

    @bp.route("/orders/date", methods=["GET"])
    @handle_api_errors
    def get_orders_by_date():
        date = request.args.get('date')
        if not date:
            return jsonify({"status": "error", "message": "date is required"}), 400
        orders = order_service.get_orders_by_date(date)
        return jsonify(orders)

    @bp.route("/orders/delivery-date", methods=["GET"])
    @handle_api_errors
    def get_orders_by_delivery_date():
        date = request.args.get('date')
        if not date:
            return jsonify({"status": "error", "message": "date is required"}), 400
        orders = order_service.get_orders_by_delivery_date(date)
        return jsonify(orders)

    return bp


def _deduct_redeemed_points(order, customer_service):
    """Increment RedeemedPoints on customer after order uses reward points."""
    if not customer_service or not isinstance(order, dict):
        return

    points_for_ship = order.get("pointsUsedForShip", 0) or 0
    points_for_order = order.get("pointsUsedForOrder", 0) or 0
    total_used = points_for_ship + points_for_order
    if total_used <= 0:
        return

    # Find customer by phone
    phone = ""
    customer_info = order.get("customer")
    if isinstance(customer_info, dict):
        phone = (customer_info.get("ContactNumber") or "").strip()
    if not phone:
        return

    try:
        from google.cloud.firestore_v1 import Increment
        for doc in customer_service.customers_ref.where("ContactNumber", "==", phone).limit(1).stream():
            doc.reference.update({"RedeemedPoints": Increment(total_used)})
            # Invalidate customer cache để BanHang sync lấy data mới
            if customer_service.cache:
                customer_service.cache.invalidate(doc.id)
                customer_service.cache.invalidate("all_customers")
            print(f"[add_order] Deducted {total_used} points from customer phone={phone}, cache invalidated")
            return
        print(f"[add_order] Customer not found for phone={phone}, cannot deduct points")
    except Exception as e:
        print(f"[add_order] Error deducting points: {type(e).__name__}: {e}")
