from __future__ import annotations

from flask import Blueprint, jsonify, request
from routes.shared import (
    create_simple_fetch_handler,
    handle_api_errors,
    notify_order_created,
    notify_order_deleted,
    notify_order_updated,
)


def create_firebase_orders_bp(order_service, socketio) -> Blueprint:
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
                else:
                    notify_order_created(socketio, order_id)
            except Exception:
                notify_order_created(socketio, order_id or order)

        return jsonify(result)

    @bp.route("/update_order/<order_id>", methods=["PUT"])
    def update_order(order_id: str):
        updates = request.json
        result = order_service.update_order(order_id, updates)
        updated_order = order_service.read_order(order_id)
        if updated_order:
            notify_order_updated(socketio, updated_order)
        return jsonify(result)

    @bp.route("/orders/<order_id>", methods=["DELETE"])
    def delete_order(order_id: str):
        result = order_service.delete_order(order_id)
        notify_order_deleted(socketio, order_id)
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

    return bp
