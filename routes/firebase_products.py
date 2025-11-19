from __future__ import annotations

from flask import Blueprint, jsonify, request

from firebase.firebase_hanghoa.import_to_firestore import update_products_from_banhang_app_to_firestore
from routes.shared import (
    apply_product_updates,
    broadcast_products_onhand_updated,
    normalize_product_updates,
    to_number,
)


def create_firebase_products_bp(product_service, socketio) -> Blueprint:
    bp = Blueprint("firebase_products", __name__, url_prefix="/api/firebase")

    @bp.route("/products/update_onhand_batch", methods=["PUT"])
    def update_onhand_from_invoice():
        invoice_obj = request.json
        result = update_products_from_banhang_app_to_firestore(invoice_obj)
        updates_for_broadcast = []
        for item in result.get('updated_products', []):
            pid = item.get("Id")
            new_onhand = item.get("new_OnHand")
            converted_onhand = to_number(new_onhand)
            if not pid or converted_onhand is None:
                continue
            updates_for_broadcast.append({"Id": str(pid), "OnHand": converted_onhand})

        if updates_for_broadcast:
            broadcast_products_onhand_updated(socketio, updates_for_broadcast)
        return jsonify(result)

    @bp.route("/get/products", methods=["GET"])
    def get_all_products():
        return jsonify(product_service.read_all_products())

    @bp.route("/get/grouped_products", methods=["GET"])
    def get_grouped_products():
        grouped = product_service.group_product()
        return jsonify(grouped)

    @bp.route("/get/products/<product_id>", methods=["GET"])
    def get_product(product_id: str):
        product = product_service.read_product(product_id)
        if product:
            return jsonify(product)
        return jsonify({"error": "Product not found"}), 404

    @bp.route("/add/product", methods=["POST"])
    def add_product():
        product = request.json
        return jsonify(product_service.add_product(product))

    @bp.route("/update/products", methods=["PUT"])
    def update_product():
        try:
            payload = request.get_json(silent=True)
            if payload is None:
                return jsonify({"status": "error", "message": "No JSON body provided"}), 400
            try:
                normalized = normalize_product_updates(payload)
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400

            results, broadcast_updates = apply_product_updates(product_service, normalized)

            if broadcast_updates:
                broadcast_products_onhand_updated(socketio, broadcast_updates)

            return jsonify({"message": f"Processed {len(results)} items", "results": results})
        except Exception as exc:  # pragma: no cover - best effort logging
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    @bp.route("/products/del/<product_id>", methods=["DELETE"])
    def delete_product(product_id: str):
        return jsonify(product_service.delete_product(product_id))

    @bp.route("/update/products/batch", methods=["PUT"])
    def update_products_batch():
        products_dict = request.json
        result = product_service.update_products(products_dict)
        return jsonify(result)

    return bp
