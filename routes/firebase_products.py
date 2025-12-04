from __future__ import annotations

from flask import Blueprint, jsonify, request

from firebase.firebase_hanghoa.import_to_firestore import update_products_from_banhang_app_to_firestore
from routes.shared import (
    apply_product_updates,
    broadcast_products_onhand_updated,
    create_simple_fetch_handler,
    handle_api_errors,
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
    @handle_api_errors
    def get_all_products():
        include_inactive = request.args.get("include_inactive", "false").lower() in ("1", "true", "yes")
        include_deleted = request.args.get("include_deleted", "false").lower() in ("1", "true", "yes")
        products = product_service.read_all_products(include_inactive=include_inactive, include_deleted=include_deleted)
        return jsonify(products)

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

            # Keep REST update behavior but do not accept websocket updates for OnHand.
            # Broadcasting to websocket clients is still allowed so UIs can receive updates.
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

    @bp.route("/products/sync", methods=["POST"])
    @handle_api_errors
    def sync_products_from_kiotviet():
        """
        Trigger a sync from KiotViet into Firestore (KiotViet is source-of-truth).
        Accepts optional JSON body: { "force": true, "limit": 100 }
        Returns the sync summary and latest products (up to `limit`).
        """
        payload = request.get_json(silent=True) or {}
        force = bool(payload.get("force", False))
        limit = int(payload.get("limit", 100)) if payload.get("limit") is not None else 100

        # product_service.sync_products_from_kiotviet() is the canonical sync method
        sync_result = product_service.sync_products_from_kiotviet()

        # After a sync, return the freshest product list (limited)
        products = product_service.read_all_products() or []
        if limit and isinstance(limit, int) and limit > 0:
            products = products[:limit]

        return jsonify({"sync": sync_result, "products": products})

    @bp.route("/products/latest", methods=["GET"])
    @handle_api_errors
    def get_latest_products():
        """Return latest cached products (optional query param `limit`)."""
        try:
            limit = int(request.args.get("limit")) if request.args.get("limit") is not None else None
        except ValueError:
            limit = None

        include_inactive = request.args.get("include_inactive", "false").lower() in ("1", "true", "yes")
        include_deleted = request.args.get("include_deleted", "false").lower() in ("1", "true", "yes")

        products = product_service.read_all_products(include_inactive=include_inactive, include_deleted=include_deleted) or []
        if limit and isinstance(limit, int) and limit > 0:
            products = products[:limit]
        return jsonify(products)

    @bp.route("/products/fetch", methods=["POST"])
    def fetch_products_changed():
        """
        Accepts JSON: 
        - { "id": "123" } - Fetch single product
        - { "ids": ["1","2"] } - Fetch multiple products
        - { "all": true } - ✅ NEW: Fetch ALL products (bypass cache)

        Returns the latest product document(s) from Firestore. 
        """
        payload = request.get_json(silent=True) or {}
    
    # ✅ NEW: Support fetch all products
        if payload.get("all") == True:
            print("🔄 Fetching ALL products directly from Firestore (no cache)...")

            # Invalidate all caches first
            product_service.invalidate_all_product_caches()

            # Read directly from Firestore
            include_inactive = payload.get("include_inactive", False)
            include_deleted = payload.get("include_deleted", False)

            products = product_service.read_all_products_fresh(
                include_inactive=include_inactive,
                include_deleted=include_deleted
            )

            print(f"✅ Fetched {len(products)} products from Firestore")
            return jsonify(products)
    
    # Original logic for single/multiple IDs
        return create_simple_fetch_handler(product_service, "read_product")()
    
    def read_all_products_fresh(self, include_inactive: bool = False, include_deleted: bool = False):
        """
        ✅ NEW: Đọc TẤT CẢ products trực tiếp từ Firestore, KHÔNG dùng cache. 
        """
        print(f"🔄 read_all_products_fresh called (include_inactive={include_inactive}, include_deleted={include_deleted})")
    
        docs = self.products_ref.stream()
        result = []

        for doc in docs:
            data = doc.to_dict() or {}

            # Determine item flags
            is_active = self._coerce_bool(data.get("isActive"), True)
            is_deleted = self._coerce_bool(data.get("isDeleted"), False)

            # Apply filters based on function args
            if (not include_inactive) and (not is_active):
                continue
            if (not include_deleted) and is_deleted:
                continue

            result.append(dict(data))

        print(f"✅ Fetched {len(result)} products from Firestore (fresh)")
        return result


    def invalidate_all_product_caches(self):
        """Invalidate tất cả các cache keys liên quan đến products"""
        cache_keys_to_invalidate = [
            "all_products",
            "all_products:inactive=False:deleted=False",
            "all_products:inactive=True:deleted=False",
            "all_products:inactive=False:deleted=True",
            "all_products:inactive=True:deleted=True",
        ]
        
        for key in cache_keys_to_invalidate:
            self.cache.invalidate(key)
        
        print(f"🗑️ Invalidated {len(cache_keys_to_invalidate)} product cache keys")
    
    return bp
