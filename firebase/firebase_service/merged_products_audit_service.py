"""
Lightweight audit/backup service for merged products.
Stores only IDs (productId, invoiceId, mergedItemId) — NOT full product data.
Auto-clears daily at 5:00 AM via scheduler.

Collection: merged_products_audit/{YYYY-MM-DD}
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from pathlib import Path

from dotenv import load_dotenv

# Load firebase-specific .env file
firebase_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(firebase_env_path)

from firebase.init_firebase import init_firestore

# Reuse product service account (same Firestore project)
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_PRODUCT", app_name="merged_products_audit_app")

COLLECTION_NAME = "merged_products_audit"


class MergedProductsAuditService:
    """Lightweight audit log for merged products actions."""

    def __init__(self):
        self.db = db

    def log_action(self, date: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Append audit records to the document for a given date.
        Each record: { mergedItemId, invoiceId, productIds[], action, actionBy, actionAt, kvInvoiceId? }
        """
        try:
            doc_ref = self.db.collection(COLLECTION_NAME).document(date)
            doc = doc_ref.get()

            existing_records = []
            if doc.exists:
                data = doc.to_dict()
                existing_records = data.get("records", [])

            all_records = existing_records + records
            now = datetime.utcnow().isoformat()

            doc_ref.set({
                "records": all_records,
                "createdAt": data.get("createdAt", now) if doc.exists else now,
                "lastUpdated": now
            })

            print(f"📝 [Audit] Logged {len(records)} records for {date} (total: {len(all_records)})")
            return {
                "success": True,
                "count": len(all_records),
                "date": date
            }
        except Exception as e:
            print(f"❌ [Audit] Error logging action: {e}")
            return {"success": False, "error": str(e)}

    def get_audit_by_date(self, date: str) -> Dict[str, Any]:
        """Get all audit records for a specific date."""
        try:
            doc = self.db.collection(COLLECTION_NAME).document(date).get()
            if doc.exists:
                data = doc.to_dict()
                return {
                    "success": True,
                    "date": date,
                    "records": data.get("records", []),
                    "createdAt": data.get("createdAt"),
                    "lastUpdated": data.get("lastUpdated")
                }
            return {
                "success": True,
                "date": date,
                "records": []
            }
        except Exception as e:
            print(f"❌ [Audit] Error getting audit for {date}: {e}")
            return {"success": False, "error": str(e), "records": []}

    def clear_old_audits(self) -> Dict[str, Any]:
        """
        Delete all audit documents BEFORE today.
        Called by scheduler at 5:00 AM daily.
        """
        try:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            docs = self.db.collection(COLLECTION_NAME).stream()

            deleted_count = 0
            for doc in docs:
                if doc.id < today:
                    doc.reference.delete()
                    deleted_count += 1

            print(f"🧹 [Audit] Cleared {deleted_count} old audit documents (before {today})")
            return {
                "success": True,
                "deleted": deleted_count,
                "cutoff": today
            }
        except Exception as e:
            print(f"❌ [Audit] Error clearing old audits: {e}")
            return {"success": False, "error": str(e)}
