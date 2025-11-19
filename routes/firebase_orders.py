from __future__ import annotations

from flask import Blueprint, jsonify, request
from routes.shared import notify_order_created, notify_order_deleted, notify_order_updated


def create_firebase_orders_bp(order_service, socketio) -> Blueprint:
    bp = Blueprint("firebase_orders", __name__, url_prefix="/api/firebase")

    @bp.route("/orders", methods=["GET"])
    def get_all_orders():
        try:
            orders = order_service.read_all_orders()
            return jsonify(orders)
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    @bp.route("/orders/<order_id>", methods=["GET"])
    def get_order_by_id(order_id: str):
        try:
            order = order_service.read_order(order_id)
            if order:
                return jsonify(order)
            return jsonify({"status": "error", "message": "Order not found"}), 404
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    @bp.route("/add_order", methods=["POST"])
    def add_order():
        order = request.json
        result = order_service.add_order(order)
        notify_order_created(socketio, order)
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

    @bp.route("/orders/date", methods=["GET"])
    def get_orders_by_date():
        try:
            date = request.args.get('date')
            if not date:
                return jsonify({"status": "error", "message": "date is required"}), 400
            orders = order_service.get_orders_by_date(date)
            return jsonify(orders)
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    return bp
