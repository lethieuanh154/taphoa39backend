"""Endpoint hoa don TAM TINH.

Nam duoi /api/ nen bi admin_auth gate - chi may POS dang nhap moi day duoc hoa
don tam. Trang khach xem (/hd/<token>) thi khong gate, xem routes/invoice_public.py.

Du lieu chi nam trong RAM, xem services/provisional_invoices.py de biet vi sao.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from routes.shared import handle_api_errors
from services.provisional_invoices import provisional_store

NAMESPACE = "/api/websocket/invoices"

# Cung namespace voi invoice_created de app chi phai giu mot ket noi.
EVENT_CREATED = "provisional_invoice"
EVENT_REMOVED = "provisional_invoice_removed"


def notify_provisional_invoice(socketio, invoice_id: str) -> None:
    """Bao app co hoa don tam moi. Chi gui id, giong invoice_created."""
    try:
        socketio.emit(EVENT_CREATED, {"id": str(invoice_id)}, namespace=NAMESPACE)
    except Exception as exc:
        print(f"[provisional] emit {EVENT_CREATED} that bai: {exc}")


def notify_provisional_removed(socketio, invoice_id: str) -> None:
    """Bao app go hoa don tam - thuong la vi no vua duoc thanh toan that."""
    try:
        socketio.emit(EVENT_REMOVED, {"id": str(invoice_id)}, namespace=NAMESPACE)
    except Exception as exc:
        print(f"[provisional] emit {EVENT_REMOVED} that bai: {exc}")


def drop_provisional_for(socketio, invoice_id: str) -> None:
    """Go hoa don tam ung voi mot hoa don vua duoc thanh toan.

    Goi tu add_invoice. Khong co hoa don tam tuong ung thi khong lam gi - phan
    lon hoa don khong di qua buoc tam tinh.
    """
    if provisional_store.remove(invoice_id):
        notify_provisional_removed(socketio, invoice_id)


def create_provisional_invoices_bp(socketio) -> Blueprint:
    bp = Blueprint("provisional_invoices", __name__, url_prefix="/api/firebase")

    @bp.route("/provisional_invoices", methods=["POST"])
    @handle_api_errors
    def upsert_provisional_invoice():
        invoice = request.get_json(silent=True) or {}
        invoice_id = str(invoice.get("id") or "").strip()
        if not invoice_id:
            return jsonify({"status": "error", "message": "invoice id is required"}), 400

        stored = provisional_store.put(invoice)
        if stored is None:
            return jsonify({"status": "error", "message": "invoice id is required"}), 400

        notify_provisional_invoice(socketio, invoice_id)
        return jsonify({"status": "ok", "invoice": stored})

    @bp.route("/provisional_invoices", methods=["GET"])
    @handle_api_errors
    def list_provisional_invoices():
        return jsonify(provisional_store.list_all())

    @bp.route("/provisional_invoices/<invoice_id>", methods=["GET"])
    @handle_api_errors
    def get_provisional_invoice(invoice_id: str):
        invoice = provisional_store.get(invoice_id)
        if not invoice:
            return jsonify({"status": "error", "message": "Provisional invoice not found"}), 404
        return jsonify(invoice)

    @bp.route("/provisional_invoices/<invoice_id>", methods=["DELETE"])
    @handle_api_errors
    def delete_provisional_invoice(invoice_id: str):
        removed = provisional_store.remove(invoice_id)
        if removed:
            notify_provisional_removed(socketio, invoice_id)
        return jsonify({"status": "ok", "removed": removed})

    return bp
