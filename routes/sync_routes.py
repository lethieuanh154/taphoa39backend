from __future__ import annotations

from flask import Blueprint, jsonify, request

from routes.shared import handle_api_errors, safe_int
from firebase.firebase_khachhang.import_to_firestore import update_customer_from_kiotviet_to_firestore


def create_sync_routes_bp(product_service) -> Blueprint:
    bp = Blueprint("sync_routes", __name__, url_prefix="/api/sync")

    @bp.route("/kiotviet/firebase/customers", methods=["PUT"])
    def sync_customers_from_kiotviet():
        return jsonify(update_customer_from_kiotviet_to_firestore())

    @bp.route("/kiotviet/firebase/products", methods=["POST"])
    @handle_api_errors
    def sync_products_from_kiotviet():
        """Trigger a sync from KiotViet into Firestore and return final Firestore data.
        Accepts optional JSON body: { "limit": 100, "skip_products": false }

        Optimizations:
        - Returns sync stats by default (no product data)
        - Set skip_products=false to include products in response
        - Uses optimized sync with retry logic and timeout
        """
        payload = request.get_json(silent=True)

        # Handle case where payload is None, list, or dict
        if payload is None or isinstance(payload, list):
            payload = {}

        skip_products = payload.get("skip_products", True)  # Default to skip for faster response

        # Perform optimized sync
        sync_result = product_service.update_products_from_kiotviet_to_firestore()

        # Check if sync succeeded
        if not sync_result.get("success", False):
            return jsonify({
                "sync": sync_result,
                "products": [],
                "error": sync_result.get("message", "Đồng bộ thất bại")
            }), 500

        # Only fetch products if explicitly requested
        if skip_products:
            return jsonify({
                "sync": sync_result,
                "message": "Đồng bộ thành công. Gọi /api/firebase/get/products để lấy danh sách.",
                "products_count": sync_result.get("stats", {}).get("total_api_items", 0)
            })

        # Fetch and return products (slower)
        products = product_service.read_all_products(include_inactive=True, include_deleted=True) or []

        return jsonify({"sync": sync_result, "products": products})

    @bp.route("/kiotviet/firebase/products/compare", methods=["GET"])
    def compare_products_between_sources():
        kiotviet_products = product_service.fetch_api_items()
        firebase_products = product_service.read_all_products()

        kv_by_id = {str(getattr(prod, "Id", "")): prod for prod in kiotviet_products if getattr(prod, "Id", None) is not None}
        fb_by_id = {str(prod.get("Id")): prod for prod in firebase_products if prod.get("Id")}

        all_ids = set(kv_by_id.keys()) | set(fb_by_id.keys())

        missing_in_firebase = []
        missing_in_kiotviet = []
        checksum_mismatches = []

        for pid in all_ids:
            kv_item = kv_by_id.get(pid)
            fb_item = fb_by_id.get(pid)

            if kv_item is None and fb_item is not None:
                missing_in_kiotviet.append({
                    "Id": pid,
                    "code": fb_item.get("Code") or fb_item.get("code"),
                })
                continue

            if kv_item is not None and fb_item is None:
                kv_code = None
                if hasattr(kv_item, "__dict__"):
                    kv_code = getattr(kv_item, "Code", None) or kv_item.__dict__.get("Code") or kv_item.__dict__.get("code")
                else:
                    try:
                        kv_code = kv_item.get("Code") or kv_item.get("code")
                    except Exception:
                        kv_code = None

                missing_in_firebase.append({
                    "Id": pid,
                    "code": kv_code,
                })
                continue

            if kv_item is None or fb_item is None:
                continue

            kv_dict = kv_item.__dict__ if hasattr(kv_item, "__dict__") else kv_item
            kv_checksum = product_service.hash_item(kv_dict)
            fb_checksum = fb_item.get("SyncChecksum") or product_service.hash_item(fb_item)

            if kv_checksum != fb_checksum:
                discrepancy = {
                    "Id": pid,
                    "kiotviet_checksum": kv_checksum,
                    "firebase_checksum": fb_checksum,
                }

                kv_onhand = getattr(kv_item, "OnHand", None)
                fb_onhand = fb_item.get("OnHand")
                if kv_onhand is not None:
                    discrepancy["kiotviet_onhand"] = kv_onhand
                if fb_onhand is not None:
                    discrepancy["firebase_onhand"] = fb_onhand

                kv_modified = getattr(kv_item, "ModifiedDate", None)
                fb_modified = fb_item.get("ModifiedDate")
                if kv_modified:
                    discrepancy["kiotviet_modified"] = str(kv_modified)
                if fb_modified:
                    discrepancy["firebase_modified"] = str(fb_modified)

                checksum_mismatches.append(discrepancy)

        return jsonify({
            "total_kiotviet": len(kv_by_id),
            "total_firebase": len(fb_by_id),
            "missing_in_firebase": sorted(missing_in_firebase, key=safe_int),
            "missing_in_kiotviet": sorted(missing_in_kiotviet, key=safe_int),
            "checksum_mismatches": checksum_mismatches,
        })

    return bp
