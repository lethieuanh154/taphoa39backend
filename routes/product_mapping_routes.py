"""
Product Mapping Routes
GET  /api/v2/product-mappings?supplierTaxCode=xxx
POST /api/v2/product-mappings        (single or batch)
PUT  /api/v2/product-mappings/rename
PUT  /api/v2/product-mappings/unit
"""

import logging
from flask import Blueprint, request, jsonify
from firebase.firebase_invoices.product_mapping_service import product_mapping_service

logger = logging.getLogger(__name__)


def create_product_mapping_routes():
    bp = Blueprint("product_mappings", __name__, url_prefix="/api/v2/product-mappings")

    @bp.route("", methods=["GET"])
    def get_mappings():
        supplier_tax_code = request.args.get("supplierTaxCode", "").strip()
        if not supplier_tax_code:
            return jsonify({"success": False, "error": "Thiếu supplierTaxCode"}), 400

        mappings = product_mapping_service.get_mappings_by_supplier(supplier_tax_code)
        return jsonify({"success": True, "mappings": mappings, "count": len(mappings)})

    @bp.route("", methods=["POST"])
    def save_mappings():
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Không có dữ liệu"}), 400

        # Accept single object or array
        if isinstance(data, list):
            saved = product_mapping_service.save_mappings_batch(data)
            return jsonify({"success": True, "saved": saved})
        else:
            ok = product_mapping_service.save_mapping(data)
            return jsonify({"success": ok})

    @bp.route("/rename", methods=["PUT"])
    def rename_mapping():
        data = request.get_json() or {}
        mapping_id = data.get("id", "").strip()
        new_description = data.get("newDescription", "").strip()
        normalized_new = data.get("normalizedNew", "").strip()

        if not mapping_id or not new_description:
            return jsonify({"success": False, "error": "Thiếu id hoặc newDescription"}), 400

        ok = product_mapping_service.rename_mapping(mapping_id, new_description, normalized_new)
        return jsonify({"success": ok})

    @bp.route("/unit", methods=["PUT"])
    def update_unit():
        data = request.get_json() or {}
        mapping_id = data.get("id", "").strip()
        new_unit = data.get("newUnit", "").strip()

        if not mapping_id or not new_unit:
            return jsonify({"success": False, "error": "Thiếu id hoặc newUnit"}), 400

        ok = product_mapping_service.update_unit(mapping_id, new_unit)
        return jsonify({"success": ok})

    return bp
