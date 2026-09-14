"""
Routes giu hang cho don dat online.

- BanHang doc /stock-map de chan thanh toan khi hang da bi don online giu.
- Trang quan ly doc /active de xem tong hop mat hang dang duoc giu.
- /release duoc goi khi don chuyen sang checked / canceled / edited.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from routes.shared import handle_api_errors


def create_reservation_bp(reservation_service, order_service=None) -> Blueprint:
    bp = Blueprint("reservations", __name__, url_prefix="/api/reservations")

    @bp.route("/stock-map", methods=["GET"])
    @handle_api_errors
    def stock_map():
        """{productId: so luong dang giu} - chi ban con han."""
        reserved = reservation_service.get_reserved_map()
        return jsonify({"reserved": reserved, "count": len(reserved)})

    @bp.route("/active", methods=["GET"])
    @handle_api_errors
    def active():
        """Danh sach ban giu hang cho trang quan ly.
        ?includeExpired=true de xem ca ban qua han chua kip danh dau."""
        include_expired = request.args.get("includeExpired", "").lower() == "true"
        items = reservation_service.list_active(include_expired=include_expired)
        return jsonify({"reservations": items, "count": len(items)})

    @bp.route("/by-product", methods=["GET"])
    @handle_api_errors
    def by_product():
        """Gom theo san pham: moi SP kem danh sach don dang giu no.
        Dung cho trang quan ly tong hop mat hang da duoc dat."""
        grouped = {}
        for r in reservation_service.list_active():
            for it in r.get("items") or []:
                pid = str(it.get("productId") or "")
                if not pid:
                    continue
                entry = grouped.setdefault(pid, {
                    "productId": pid,
                    "code": it.get("code") or "",
                    "name": it.get("name") or "",
                    "totalReserved": 0.0,
                    "orders": [],
                })
                entry["totalReserved"] += float(it.get("quantity") or 0)
                entry["orders"].append({
                    "orderId": r.get("orderId"),
                    "customerName": r.get("customerName"),
                    "customerPhone": r.get("customerPhone"),
                    "quantity": it.get("quantity"),
                    "createdAt": r.get("createdAt"),
                    "expiresAt": r.get("expiresAt"),
                })

        products = sorted(grouped.values(), key=lambda p: p["totalReserved"], reverse=True)
        return jsonify({"products": products, "count": len(products)})

    @bp.route("/release", methods=["POST"])
    @handle_api_errors
    def release():
        """Body: { orderId, reason }. reason: checked | canceled | edited."""
        body = request.get_json(silent=True) or {}
        order_id = str(body.get("orderId") or "").strip()
        if not order_id:
            return jsonify({"success": False, "error": "Thieu orderId"}), 400

        reason = body.get("reason") or "released"
        result = reservation_service.release(order_id, reason)
        status = 200 if result.get("success") else 500
        return jsonify(result), status

    @bp.route("/expire-overdue", methods=["POST"])
    @handle_api_errors
    def expire_overdue():
        """Danh dau ban giu hang qua han + set status don hang thanh 'expired'.
        Scheduler goi moi gio; van goi tay duoc."""
        result = reservation_service.expire_overdue()
        result["ordersUpdated"] = _mark_orders_expired(result.get("expired") or [])
        return jsonify(result)

    @bp.route("/clear-old", methods=["POST"])
    @handle_api_errors
    def clear_old():
        body = request.get_json(silent=True) or {}
        keep_days = int(body.get("keepDays") or 7)
        return jsonify(reservation_service.clear_old(keep_days=keep_days))

    def _mark_orders_expired(order_ids) -> int:
        """Don qua han -> status 'expired' de BanHang/Management hien dung mau."""
        if not order_ids or not order_service:
            return 0
        updated = 0
        for oid in order_ids:
            try:
                existing = order_service.read_order(str(oid))
                if not existing or existing.get("status") != "pending":
                    continue  # don da duoc xu ly -> khong dong vao
                order_service.orders_ref.document(str(oid)).update({"status": "expired"})
                updated += 1
            except Exception as e:
                print(f"[Reservation] LOI: Loi set expired cho don {oid}: {type(e).__name__}: {e}")
        if updated:
            try:
                order_service.cache.invalidate("all_orders")
            except Exception:
                pass
        return updated

    return bp
