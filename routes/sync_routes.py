from __future__ import annotations

from flask import Blueprint, jsonify

from firebase.firebase_khachhang.import_to_firestore import update_customer_from_kiotviet_to_firestore


def create_sync_routes_bp(product_service) -> Blueprint:
    bp = Blueprint("sync_routes", __name__, url_prefix="/api/sync")

    @bp.route("/kiotviet/firebase/customers", methods=["PUT"])
    def sync_customers_from_kiotviet():
        return jsonify(update_customer_from_kiotviet_to_firestore())

    @bp.route("/kiotviet/firebase/products", methods=["PUT"])
    def sync_products_from_kiotviet():
        return jsonify(product_service.update_products_from_kiotviet_to_firestore())

    return bp
