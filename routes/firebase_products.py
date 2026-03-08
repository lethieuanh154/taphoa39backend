from __future__ import annotations

from datetime import datetime
from flask import Blueprint, jsonify, request

from firebase.firebase_hanghoa.import_to_firestore import update_products_from_banhang_app_to_firestore
from routes.shared import (
    apply_product_updates,
    broadcast_products_added,
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
            update_type = item.get("updateType", "OnHand")
            converted_onhand = to_number(new_onhand)
            if not pid or converted_onhand is None:
                continue
            # ✅ Broadcast với đúng field: OnHand hoặc OnHandNV
            if update_type == "OnHandNV":
                updates_for_broadcast.append({"Id": str(pid), "OnHandNV": converted_onhand, "updateType": "OnHandNV"})
            else:
                updates_for_broadcast.append({"Id": str(pid), "OnHand": converted_onhand, "updateType": "OnHand"})

        if updates_for_broadcast:
            broadcast_products_onhand_updated(socketio, updates_for_broadcast)
        return jsonify(result)

    @bp.route("/get/products", methods=["GET"])
    @handle_api_errors
    def get_all_products():
        # ⚠️ WARNING: This endpoint reads ALL products from Firestore!
        # Track caller for debugging excessive reads
        caller_ip = request.remote_addr
        user_agent = request.headers.get('User-Agent', 'unknown')[:100]
        print(f"⚠️ [FULL_READ] /get/products called from {caller_ip} - UA: {user_agent}")

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
    @handle_api_errors
    def add_product():
        """Add a single product to Firebase."""
        product = request.json
        if not product:
            return jsonify({"status": "error", "message": "No product data provided"}), 400
        
        # ✅ Xử lý tồn kho: user nhập -> OnHandNV, OnHand = 0
        product = _process_stock_for_new_product(product)
        
        return jsonify(product_service.add_product(product))

    @bp.route("/add/products/batch", methods=["POST"])
    @handle_api_errors
    def add_products_batch():
        """
        ✅ NEW: Add multiple products to Firebase in batch.
        Expects JSON: { "products": [...] }
        
        Xử lý tồn kho:
        - OnHand: Tồn kho từ KiotViet API (ban đầu = 0 cho sản phẩm mới)
        - OnHandNV: Tồn kho do user nhập khi tạo sản phẩm mới
        
        Khi tạo sản phẩm mới:
        - Giá trị tồn kho user nhập sẽ lưu vào OnHandNV
        - OnHand = 0 (vì sản phẩm mới chưa có trên KiotViet)
        """
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"status": "error", "message": "No JSON body provided"}), 400

        products = payload.get("products", [])
        if not products:
            return jsonify({"status": "error", "message": "No products provided"}), 400

        if not isinstance(products, list):
            return jsonify({"status": "error", "message": "Products must be a list"}), 400

        # ✅ Validate và xử lý tồn kho cho mỗi product
        processed_products = []
        errors = []
        
        for idx, product in enumerate(products):
            if not product.get("Id"):
                errors.append({"index": idx, "error": "Missing Id"})
                continue
            if not product.get("Code"):
                errors.append({"index": idx, "error": "Missing Code"})
                continue
            
            # ✅ Xử lý tồn kho: user nhập -> OnHandNV, OnHand = 0
            processed_product = _process_stock_for_new_product(product)
            processed_products.append(processed_product)

        if not processed_products:
            return jsonify({
                "status": "error", 
                "message": "No valid products to add",
                "errors": errors
            }), 400

        # ✅ Gọi service để add batch
        result = product_service.add_products_batch(processed_products)

        # Thêm errors từ validation vào result
        if errors:
            result["validation_errors"] = errors

        # ✅ Broadcast via WebSocket for realtime sync to other machines
        if result.get("status") != "error" and processed_products:
            print(f"📡 [add_products_batch] Broadcasting {len(processed_products)} new products via WebSocket")
            broadcast_products_added(socketio, processed_products)

        return jsonify(result)

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
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    @bp.route("/products/del/<product_id>", methods=["DELETE"])
    def delete_product(product_id: str):
        return jsonify(product_service.delete_product(product_id))

    @bp.route("/products/del-with-siblings/<product_id>", methods=["DELETE"])
    @handle_api_errors
    def delete_product_with_siblings(product_id: str):
        """
        Delete a product AND all its siblings (products with the same MasterUnitId).
        Use this for clone products to ensure ALL related units are deleted together.

        This endpoint:
        1. Finds the product's MasterUnitId (or uses product Id if it's the master)
        2. Deletes ALL products with that MasterUnitId
        3. Returns list of deleted product IDs
        """
        result = product_service.delete_product_with_siblings(product_id)
        return jsonify(result)

    @bp.route("/update/products/batch", methods=["PUT"])
    def update_products_batch():
        """
        Update multiple products in batch.
        Broadcasts updates via WebSocket for realtime sync across machines.
        """
        products_dict = request.json
        result = product_service.update_products(products_dict)

        # ✅ Broadcast updates via WebSocket for realtime sync
        # Extract all updated products for broadcasting
        broadcast_updates = []
        if isinstance(products_dict, dict):
            for group_key, products in products_dict.items():
                if isinstance(products, list):
                    for product in products:
                        if isinstance(product, dict) and product.get('Id'):
                            # Include all relevant fields for sync
                            update_data = {'Id': str(product.get('Id'))}
                            # Add fields if present - include all edited fields for realtime sync
                            for field in ['Code', 'Name', 'FullName', 'BasePrice', 'Cost', 'OnHand', 'OnHandNV', 'Description', 'NormalizedName', 'NormalizedCode','OrderTemplate']:
                                if field in product and product[field] is not None:
                                    update_data[field] = product[field]
                            broadcast_updates.append(update_data)

        if broadcast_updates:
            print(f"📡 [update_products_batch] Broadcasting {len(broadcast_updates)} product updates via WebSocket")
            broadcast_products_onhand_updated(socketio, broadcast_updates)

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

        sync_result = product_service.sync_products_from_kiotviet()

        products = product_service.read_all_products() or []
        if limit and isinstance(limit, int) and limit > 0:
            products = products[:limit]

        return jsonify({"sync": sync_result, "products": products})

    @bp.route("/products/latest", methods=["GET"])
    @handle_api_errors
    def get_latest_products():
        """Return latest cached products (optional query param `limit`)."""
        # ⚠️ WARNING: This endpoint reads ALL products from Firestore!
        caller_ip = request.remote_addr
        user_agent = request.headers.get('User-Agent', 'unknown')[:100]
        print(f"⚠️ [FULL_READ] /products/latest called from {caller_ip} - UA: {user_agent}")

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
        - { "all": true } - Fetch ALL products (bypass cache)

        Returns the latest product document(s) from Firestore.
        """
        payload = request.get_json(silent=True) or {}
    
        # Support fetch all products
        if payload.get("all") == True:
            # ⚠️ WARNING: This reads ALL products from Firestore (EXPENSIVE!)
            caller_ip = request.remote_addr
            user_agent = request.headers.get('User-Agent', 'unknown')[:100]
            print(f"⚠️ [FULL_READ_FRESH] /products/fetch ALL called from {caller_ip} - UA: {user_agent}")
            print("🔄 Fetching ALL products directly from Firestore (no cache)...")

            product_service.invalidate_all_product_caches()

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

    @bp.route("/products/variants/<int:product_id>", methods=["GET"])
    @handle_api_errors
    def get_product_variants(product_id: int):
        """
        Get a product and all its variants (by unit and attributes).
        Returns the master product and all related variants.
        """
        result = product_service.get_product_variants(product_id)
        return jsonify(result)

    @bp.route("/products/modified-since", methods=["POST"])
    @handle_api_errors
    def fetch_products_modified_since():
        """
        Fetch products modified since a given timestamp.
        Optimized endpoint to reduce Firestore reads by only fetching changed products.

        Accepts JSON:
        {
            "since": "2024-01-15T10:30:00Z",  // ISO 8601 timestamp (required)
            "include_inactive": true,         // Optional, default true
            "include_deleted": false          // Optional, default false
        }

        Returns: List of products modified since the given timestamp
        """
        payload = request.get_json(silent=True) or {}

        since_timestamp = payload.get("since")
        if not since_timestamp:
            return jsonify({"error": "Missing 'since' timestamp"}), 400

        include_inactive = payload.get("include_inactive", True)
        include_deleted = payload.get("include_deleted", False)

        print(f"🔄 Fetching products modified since {since_timestamp}...")

        products = product_service.read_products_modified_since(
            since_timestamp=since_timestamp,
            include_inactive=include_inactive,
            include_deleted=include_deleted
        )

        print(f"✅ Found {len(products)} products modified since {since_timestamp}")
        return jsonify({
            "products": products,
            "count": len(products),
            "since": since_timestamp,
            "fetched_at": datetime.now().isoformat()
        })

    return bp


def _process_stock_for_new_product(product: dict) -> dict:
    """
    ✅ Helper function: Xử lý tồn kho cho sản phẩm mới.

    Phân biệt:
    - OnHand: Tồn kho từ KiotViet API (/items/all) - tồn kho thực tế
    - OnHandNV: Tồn kho do user nhập khi tạo sản phẩm mới

    Khi tạo sản phẩm mới từ frontend:
    - User nhập tồn kho -> lưu vào OnHandNV
    - OnHand = 0 (vì sản phẩm mới chưa có trên KiotViet)

    Sau này khi sync từ KiotViet:
    - OnHand sẽ được cập nhật từ API KiotViet
    - OnHandNV giữ nguyên giá trị user đã nhập
    """
    if not isinstance(product, dict):
        return product

    # Tạo bản copy để không thay đổi dict gốc
    result = dict(product)

    # ✅ Ưu tiên lấy OnHandNV nếu frontend đã gửi sẵn
    # Nếu không có thì fallback sang OnHand hoặc stock
    if "OnHandNV" in result and result.get("OnHandNV") is not None:
        user_input_stock = result.get("OnHandNV")
    else:
        user_input_stock = result.get("OnHand") or result.get("stock") or 0

    # Parse thành số
    try:
        stock_value = float(user_input_stock) if user_input_stock is not None else 0
    except (TypeError, ValueError):
        stock_value = 0

    # ✅ Lưu tồn kho user nhập vào OnHandNV
    result["OnHandNV"] = stock_value

    # ✅ OnHand = 0 (sản phẩm mới chưa có trên KiotViet)
    # Sau này khi sync từ KiotViet, OnHand sẽ được cập nhật
    result["OnHand"] = 0

    # Xóa field "stock" nếu có (không cần lưu vào Firebase)
    result.pop("stock", None)

    print(f"📦 Product {result.get('Id')}: User input stock={user_input_stock} -> OnHandNV={stock_value}, OnHand=0")

    return result