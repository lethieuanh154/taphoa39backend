"""
Service for managing merged products in Firestore.
Stores merged products data that needs to be synced across multiple clients.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import os
from pathlib import Path

from dotenv import load_dotenv

# Load firebase-specific .env file
firebase_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(firebase_env_path)

from firebase.init_firebase import init_firestore

# Initialize Firestore using the product service account (shared)
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_PRODUCT", app_name="merged_products_app")


class MergedProductsService:
    """Service for merged products CRUD operations."""

    COLLECTION_NAME = "merged_products"
    DOC_ID = "shared_items"  # Single document to store all merged items

    def __init__(self):
        self.db = db

    def get_merged_products(self) -> Dict[str, Any]:
        """
        Get all merged products from Firestore.
        Returns the shared document containing all merged items.
        """
        try:
            doc_ref = self.db.collection(self.COLLECTION_NAME).document(self.DOC_ID)
            doc = doc_ref.get()

            if doc.exists:
                data = doc.to_dict()
                return {
                    "success": True,
                    "items": data.get("items", []),
                    "lastModified": data.get("lastModified", None),
                    "modifiedBy": data.get("modifiedBy", None)
                }
            else:
                return {
                    "success": True,
                    "items": [],
                    "lastModified": None,
                    "modifiedBy": None
                }
        except Exception as e:
            print(f"❌ Error getting merged products: {e}")
            return {
                "success": False,
                "error": str(e),
                "items": []
            }

    def save_merged_products(
        self,
        items: List[Dict[str, Any]],
        modified_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Save merged products to Firestore.
        Replaces all existing items with the new list.
        """
        try:
            doc_ref = self.db.collection(self.COLLECTION_NAME).document(self.DOC_ID)

            data = {
                "items": items,
                "lastModified": datetime.utcnow().isoformat(),
                "modifiedBy": modified_by or "unknown"
            }

            doc_ref.set(data)

            print(f"✅ Saved {len(items)} merged products to Firestore")
            return {
                "success": True,
                "count": len(items),
                "lastModified": data["lastModified"]
            }
        except Exception as e:
            print(f"❌ Error saving merged products: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def add_merged_item(
        self,
        item: Dict[str, Any],
        modified_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add a single merged item to the list.
        """
        try:
            # Get current items
            current = self.get_merged_products()
            items = current.get("items", [])

            # Add new item
            items.append(item)

            # Save back
            return self.save_merged_products(items, modified_by)
        except Exception as e:
            print(f"❌ Error adding merged item: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def remove_merged_items(
        self,
        item_ids: List[str],
        modified_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Remove merged items by their IDs.
        """
        try:
            # Get current items
            current = self.get_merged_products()
            items = current.get("items", [])

            # Filter out items to remove
            id_set = set(item_ids)
            items = [item for item in items if item.get("id") not in id_set]

            # Save back
            return self.save_merged_products(items, modified_by)
        except Exception as e:
            print(f"❌ Error removing merged items: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def update_merged_items(
        self,
        updates: List[Dict[str, Any]],
        remove_ids: List[str],
        modified_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Atomic update: remove items by IDs AND update specific items in one operation.
        Reads current Firestore state (not client state) to avoid stale overwrites.
        - remove_ids: item IDs to completely remove
        - updates: items to replace (matched by 'id' field)
        """
        try:
            current = self.get_merged_products()
            items = current.get("items", [])

            # Remove items by IDs
            id_set = set(remove_ids)
            items = [item for item in items if item.get("id") not in id_set]

            # Update items (replace matching items with new versions)
            update_map = {u.get("id"): u for u in updates if u.get("id")}
            items = [update_map.pop(item.get("id"), item) for item in items]

            return self.save_merged_products(items, modified_by)
        except Exception as e:
            print(f"❌ Error in atomic update: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def clear_all(self, modified_by: Optional[str] = None) -> Dict[str, Any]:
        """
        Clear all merged products.
        """
        return self.save_merged_products([], modified_by)

    # --- Auto-Merge History ---

    HISTORY_DOC_ID = "auto_merge_history"
    MAX_HISTORY_ENTRIES = 500

    def get_auto_merge_history(self) -> Dict[str, Any]:
        """Get all auto-merge history entries from Firestore."""
        try:
            doc_ref = self.db.collection(self.COLLECTION_NAME).document(self.HISTORY_DOC_ID)
            doc = doc_ref.get()

            if doc.exists:
                data = doc.to_dict()
                return {
                    "success": True,
                    "entries": data.get("entries", []),
                    "lastModified": data.get("lastModified", None)
                }
            else:
                return {
                    "success": True,
                    "entries": [],
                    "lastModified": None
                }
        except Exception as e:
            print(f"❌ Error getting auto-merge history: {e}")
            return {
                "success": False,
                "error": str(e),
                "entries": []
            }

    def add_auto_merge_history(
        self,
        entries: List[Dict[str, Any]],
        modified_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Append new history entries to Firestore. Keeps max 500 entries."""
        try:
            current = self.get_auto_merge_history()
            all_entries = current.get("entries", [])
            all_entries.extend(entries)

            # Keep only the most recent entries (sort by timestamp desc, keep first N)
            all_entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
            all_entries = all_entries[:self.MAX_HISTORY_ENTRIES]

            doc_ref = self.db.collection(self.COLLECTION_NAME).document(self.HISTORY_DOC_ID)
            data = {
                "entries": all_entries,
                "lastModified": datetime.utcnow().isoformat(),
                "modifiedBy": modified_by or "unknown"
            }
            doc_ref.set(data)

            print(f"✅ Saved {len(entries)} new history entries (total: {len(all_entries)})")
            return {
                "success": True,
                "count": len(all_entries),
                "lastModified": data["lastModified"]
            }
        except Exception as e:
            print(f"❌ Error adding auto-merge history: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def mark_history_returned(
        self,
        entry_ids: List[str],
        modified_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Mark specific auto-merge history entries as returned in Firestore."""
        if not entry_ids:
            return {"success": True, "updated": 0}

        try:
            current = self.get_auto_merge_history()
            all_entries = current.get("entries", [])

            updated_count = 0
            ids_set = set(entry_ids)
            for entry in all_entries:
                if entry.get("id") in ids_set:
                    entry["returned"] = True
                    updated_count += 1

            doc_ref = self.db.collection(self.COLLECTION_NAME).document(self.HISTORY_DOC_ID)
            data = {
                "entries": all_entries,
                "lastModified": datetime.utcnow().isoformat(),
                "modifiedBy": modified_by or "unknown"
            }
            doc_ref.set(data)

            print(f"✅ Marked {updated_count}/{len(entry_ids)} history entries as returned")
            return {
                "success": True,
                "updated": updated_count,
                "lastModified": data["lastModified"]
            }
        except Exception as e:
            print(f"❌ Error marking history returned: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def delete_history_entries(
        self,
        entry_ids: List[str],
        modified_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delete specific auto-merge history entries from Firestore."""
        if not entry_ids:
            return {"success": True, "deleted": 0}

        try:
            current = self.get_auto_merge_history()
            all_entries = current.get("entries", [])

            ids_set = set(entry_ids)
            remaining = [e for e in all_entries if e.get("id") not in ids_set]
            deleted_count = len(all_entries) - len(remaining)

            doc_ref = self.db.collection(self.COLLECTION_NAME).document(self.HISTORY_DOC_ID)
            data = {
                "entries": remaining,
                "lastModified": datetime.utcnow().isoformat(),
                "modifiedBy": modified_by or "unknown"
            }
            doc_ref.set(data)

            print(f"✅ Deleted {deleted_count}/{len(entry_ids)} history entries")
            return {
                "success": True,
                "deleted": deleted_count,
                "remaining": len(remaining),
                "lastModified": data["lastModified"]
            }
        except Exception as e:
            print(f"❌ Error deleting history entries: {e}")
            return {
                "success": False,
                "error": str(e)
            }
