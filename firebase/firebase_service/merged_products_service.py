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

    def clear_all(self, modified_by: Optional[str] = None) -> Dict[str, Any]:
        """
        Clear all merged products.
        """
        return self.save_merged_products([], modified_by)
