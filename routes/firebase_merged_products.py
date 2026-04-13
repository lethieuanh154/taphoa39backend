"""
Routes for merged products sync across clients.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from firebase.firebase_service.merged_products_service import MergedProductsService


def create_firebase_merged_products_bp(socketio=None) -> Blueprint:
    """Create the merged products blueprint."""
    bp = Blueprint("firebase_merged_products", __name__, url_prefix="/api/firebase/merged-products")
    service = MergedProductsService()

    @bp.route("", methods=["GET"])
    def get_merged_products():
        """Get all merged products from Firestore."""
        result = service.get_merged_products()
        return jsonify(result)

    @bp.route("", methods=["POST"])
    def save_merged_products():
        """Save merged products to Firestore (replace all)."""
        data = request.get_json()
        items = data.get("items", [])
        modified_by = data.get("modifiedBy", None)

        result = service.save_merged_products(items, modified_by)

        # Broadcast to other clients via WebSocket if available
        if socketio and result.get("success"):
            try:
                socketio.emit(
                    "merged_products_updated",
                    {
                        "items": items,
                        "count": len(items),
                        "lastModified": result.get("lastModified"),
                        "modifiedBy": modified_by
                    },
                    namespace="/api/websocket/products"
                )
                print(f"📡 Broadcast merged_products_updated: {len(items)} items")
            except Exception as e:
                print(f"⚠️ Failed to broadcast merged products update: {e}")

        return jsonify(result)

    @bp.route("/add", methods=["POST"])
    def add_merged_item():
        """Add a single merged item."""
        data = request.get_json()
        item = data.get("item", {})
        modified_by = data.get("modifiedBy", None)

        result = service.add_merged_item(item, modified_by)

        # Broadcast to other clients
        if socketio and result.get("success"):
            try:
                current = service.get_merged_products()
                socketio.emit(
                    "merged_products_updated",
                    {
                        "items": current.get("items", []),
                        "count": len(current.get("items", [])),
                        "lastModified": result.get("lastModified"),
                        "modifiedBy": modified_by
                    },
                    namespace="/api/websocket/products"
                )
            except Exception as e:
                print(f"⚠️ Failed to broadcast merged products update: {e}")

        return jsonify(result)

    @bp.route("/remove", methods=["POST"])
    def remove_merged_items():
        """Remove merged items by IDs."""
        data = request.get_json()
        item_ids = data.get("itemIds", [])
        modified_by = data.get("modifiedBy", None)

        result = service.remove_merged_items(item_ids, modified_by)

        # Broadcast to other clients
        if socketio and result.get("success"):
            try:
                current = service.get_merged_products()
                socketio.emit(
                    "merged_products_updated",
                    {
                        "items": current.get("items", []),
                        "count": len(current.get("items", [])),
                        "lastModified": result.get("lastModified"),
                        "modifiedBy": modified_by
                    },
                    namespace="/api/websocket/products"
                )
            except Exception as e:
                print(f"⚠️ Failed to broadcast merged products update: {e}")

        return jsonify(result)

    @bp.route("/atomic-update", methods=["POST"])
    def atomic_update_merged_items():
        """Atomic update: remove items + update items in one Firestore operation."""
        data = request.get_json()
        updates = data.get("updates", [])
        remove_ids = data.get("removeIds", [])
        modified_by = data.get("modifiedBy", None)

        result = service.update_merged_items(updates, remove_ids, modified_by)

        # Broadcast to other clients
        if socketio and result.get("success"):
            try:
                current = service.get_merged_products()
                socketio.emit(
                    "merged_products_updated",
                    {
                        "items": current.get("items", []),
                        "count": len(current.get("items", [])),
                        "lastModified": result.get("lastModified"),
                        "modifiedBy": modified_by
                    },
                    namespace="/api/websocket/products"
                )
            except Exception as e:
                print(f"⚠️ Failed to broadcast merged products update: {e}")

        return jsonify(result)

    @bp.route("/clear", methods=["POST"])
    def clear_merged_products():
        """Clear all merged products."""
        data = request.get_json() or {}
        modified_by = data.get("modifiedBy", None)

        result = service.clear_all(modified_by)

        # Broadcast to other clients
        if socketio and result.get("success"):
            try:
                socketio.emit(
                    "merged_products_updated",
                    {
                        "items": [],
                        "count": 0,
                        "lastModified": result.get("lastModified"),
                        "modifiedBy": modified_by
                    },
                    namespace="/api/websocket/products"
                )
            except Exception as e:
                print(f"⚠️ Failed to broadcast merged products clear: {e}")

        return jsonify(result)

    # --- Auto-Merge History Routes ---

    @bp.route("/history", methods=["GET"])
    def get_auto_merge_history():
        """Get all auto-merge history entries from Firestore."""
        result = service.get_auto_merge_history()
        return jsonify(result)

    @bp.route("/history/add", methods=["POST"])
    def add_auto_merge_history():
        """Add new auto-merge history entries."""
        data = request.get_json()
        entries = data.get("entries", [])
        modified_by = data.get("modifiedBy", None)

        result = service.add_auto_merge_history(entries, modified_by)
        return jsonify(result)

    @bp.route("/history/mark-returned", methods=["POST"])
    def mark_history_returned():
        """Mark auto-merge history entries as returned."""
        data = request.get_json()
        entry_ids = data.get("entryIds", [])
        modified_by = data.get("modifiedBy", None)

        result = service.mark_history_returned(entry_ids, modified_by)
        return jsonify(result)

    return bp
