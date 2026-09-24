from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from routes.shared import handle_api_errors
from firebase.firebase_service.promotion_service import (
    FLASH_BANNER_MAX_PRODUCTS, is_flash_banner, parse_iso,
)


def create_firebase_promotions_bp(promotion_service, product_service, socketio) -> Blueprint:
    bp = Blueprint("firebase_promotions", __name__, url_prefix="/api/firebase")

    def _flash_banner_error(promo: dict, promo_id: str | None = None) -> str | None:
        """KM ngan ngay (< 7 ngay) = banner DatHang: toi da 4 SP chay trung thoi gian."""
        if not is_flash_banner(promo):
            return None
        start = parse_iso(promo.get("fromDate"))
        end = parse_iso(promo.get("toDate"))

        now = datetime.now(timezone.utc)
        products = {str(promo.get("targetProductId"))}
        for other in promotion_service.read_all_promotions(include_disabled=False):
            if other.get("id") == promo_id or not is_flash_banner(other):
                continue
            o_start = parse_iso(other.get("fromDate"))
            o_end = parse_iso(other.get("toDate"))
            if o_end < now:
                continue
            if o_start < end and o_end > start:
                products.add(str(other.get("targetProductId")))
        if len(products) > FLASH_BANNER_MAX_PRODUCTS:
            return f"KM duoi 7 ngay (banner DatHang) toi da {FLASH_BANNER_MAX_PRODUCTS} san pham cung thoi gian"
        return None

    # ──────────────────────────────────────────────
    # READ
    # ──────────────────────────────────────────────

    @bp.route("/promotions", methods=["GET"])
    @handle_api_errors
    def get_all_promotions():
        """Get all promotions. ?include_disabled=true to include disabled."""
        include_disabled = request.args.get("include_disabled", "false").lower() in ("1", "true")
        promos = promotion_service.read_all_promotions(include_disabled=include_disabled)
        return jsonify(promos)

    @bp.route("/promotions/active", methods=["GET"])
    @handle_api_errors
    def get_active_promotions():
        """Get currently active promotions (enabled + within date range).
        Enriches each promotion with targetProduct data for DatHang app."""
        promos = promotion_service.read_active_promotions()

        # Embed product data so frontend doesn't need IndexedDB lookup
        _PRODUCT_FIELDS = (
            "Id", "Code", "Name", "FullName", "Image", "BasePrice",
            "OnHand", "Unit", "CategoryId", "NormalizedName", "NormalizedCode",
            "isActive", "isDeleted", "isClone", "OnHandNV", "Description",
            "ConversionValue", "MasterUnitId", "MasterProductId", "ModifiedDate",
        )
        # 1 lan get_all thay vi N lan document().get() (120 KM -> 120 round-trip Firestore)
        products = product_service.read_products_bulk(
            [p.get("targetProductId") for p in promos if p.get("targetProductId")]
        )

        # Copy: promos la object nam trong cache cua promotion_service, khong duoc mutate
        enriched = []
        for promo in promos:
            pid = promo.get("targetProductId")
            if not pid:
                enriched.append(promo)
                continue
            product = products.get(str(pid))
            enriched.append({
                **promo,
                "targetProduct": {k: product.get(k) for k in _PRODUCT_FIELDS if k in product} if product else None,
            })

        return jsonify(enriched)

    @bp.route("/promotions/<promo_id>", methods=["GET"])
    @handle_api_errors
    def get_promotion(promo_id: str):
        promo = promotion_service.read_promotion(promo_id)
        if promo:
            return jsonify(promo)
        return jsonify({"error": "Promotion not found"}), 404

    @bp.route("/promotions/by-product/<product_id>", methods=["GET"])
    @handle_api_errors
    def get_promotions_for_product(product_id: str):
        """Get active promotions for a specific product."""
        promos = promotion_service.read_promotions_for_product(product_id)
        return jsonify(promos)

    # ──────────────────────────────────────────────
    # WRITE
    # ──────────────────────────────────────────────

    @bp.route("/promotions", methods=["POST"])
    @handle_api_errors
    def create_promotion():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400

        # Validate required fields
        required = ["name", "targetProductId", "fromDate", "toDate"]
        for field in required:
            if not data.get(field):
                return jsonify({"status": "error", "message": f"Missing: {field}"}), 400

        # Support boolean flags (new) or legacy type field
        has_gift = data.get("hasGift", False)
        has_pct = data.get("hasPercentDiscount", False)
        has_fixed = data.get("hasFixedDiscount", False)

        # Fallback: if no boolean flags, use legacy type field
        if not has_gift and not has_pct and not has_fixed:
            legacy_type = data.get("type", "")
            if legacy_type not in ("gift", "percentage", "fixed_amount"):
                return jsonify({"status": "error", "message": "Chon it nhat 1 loai khuyen mai"}), 400
            has_gift = legacy_type == "gift"
            has_pct = legacy_type == "percentage"
            has_fixed = legacy_type == "fixed_amount"

        has_gift_items = bool(data.get("giftItems"))
        has_gift_product = bool(data.get("giftProductId"))
        if has_gift and not has_gift_items and not has_gift_product:
            return jsonify({"status": "error", "message": "Tang kem requires giftProductId or giftItems"}), 400

        if has_pct and not data.get("discountPercent"):
            return jsonify({"status": "error", "message": "Giam % requires discountPercent"}), 400

        if has_fixed and not data.get("discountAmount"):
            return jsonify({"status": "error", "message": "Giam tien requires discountAmount"}), 400

        err = _flash_banner_error(data)
        if err:
            return jsonify({"status": "error", "message": err}), 400

        result = promotion_service.create_promotion(data)

        # Broadcast via WebSocket
        if socketio:
            socketio.emit('promotions_updated', {
                'action': 'created',
                'promotionId': result.get('id')
            }, namespace='/api/websocket/products')

        return jsonify(result), 201

    @bp.route("/promotions/<promo_id>", methods=["PUT"])
    @handle_api_errors
    def update_promotion(promo_id: str):
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400

        if any(k in data for k in ("fromDate", "toDate", "targetProductId", "isEnabled")):
            existing = promotion_service.read_promotion(promo_id) or {}
            merged = {**existing, **data}
            if merged.get("isEnabled", True):
                err = _flash_banner_error(merged, promo_id)
                if err:
                    return jsonify({"status": "error", "message": err}), 400

        result = promotion_service.update_promotion(promo_id, data)

        if socketio:
            socketio.emit('promotions_updated', {
                'action': 'updated',
                'promotionId': promo_id
            }, namespace='/api/websocket/products')

        return jsonify(result)

    @bp.route("/promotions/<promo_id>", methods=["DELETE"])
    @handle_api_errors
    def delete_promotion(promo_id: str):
        result = promotion_service.delete_promotion(promo_id)

        if socketio:
            socketio.emit('promotions_updated', {
                'action': 'deleted',
                'promotionId': promo_id
            }, namespace='/api/websocket/products')

        return jsonify(result)

    @bp.route("/promotions/<promo_id>/toggle", methods=["PUT"])
    @handle_api_errors
    def toggle_promotion(promo_id: str):
        data = request.get_json(silent=True) or {}
        enabled = data.get("isEnabled", True)
        if enabled:
            existing = promotion_service.read_promotion(promo_id)
            err = _flash_banner_error(existing, promo_id) if existing else None
            if err:
                return jsonify({"status": "error", "message": err}), 400
        result = promotion_service.toggle_promotion(promo_id, enabled)

        if socketio:
            socketio.emit('promotions_updated', {
                'action': 'toggled',
                'promotionId': promo_id
            }, namespace='/api/websocket/products')

        return jsonify(result)

    # ──────────────────────────────────────────────
    # APPLY TO CART
    # ──────────────────────────────────────────────

    @bp.route("/promotions/apply", methods=["POST"])
    @handle_api_errors
    def apply_promotions_to_cart():
        """
        Apply promotions to cart items.
        POST body: { "cartItems": [...] }
        """
        data = request.get_json(silent=True) or {}
        cart_items = data.get("cartItems", [])
        if not cart_items:
            return jsonify({"appliedPromotions": [], "giftItems": [], "totalDiscount": 0})

        result = promotion_service.apply_promotions(cart_items)
        return jsonify(result)

    return bp
