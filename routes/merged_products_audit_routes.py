"""
Routes for merged products audit/backup system.
Lightweight: only stores IDs (productId, invoiceId), not full data.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from firebase.firebase_service.merged_products_audit_service import MergedProductsAuditService


def create_merged_products_audit_bp() -> Blueprint:
    """Create the merged products audit blueprint."""
    bp = Blueprint("merged_products_audit", __name__, url_prefix="/api/merged-products-audit")
    service = MergedProductsAuditService()

    @bp.route("/log", methods=["POST"])
    def log_action():
        """Log audit records for a date."""
        data = request.get_json()
        date = data.get("date")
        records = data.get("records", [])

        if not date or not records:
            return jsonify({"success": False, "error": "Missing date or records"}), 400

        result = service.log_action(date, records)
        return jsonify(result)

    @bp.route("/<date>", methods=["GET"])
    def get_audit(date):
        """Get audit records for a specific date (YYYY-MM-DD)."""
        result = service.get_audit_by_date(date)
        return jsonify(result)

    @bp.route("/clear-old", methods=["POST"])
    def clear_old():
        """Manually trigger cleanup of old audit documents."""
        result = service.clear_old_audits()
        return jsonify(result)

    return bp, service
