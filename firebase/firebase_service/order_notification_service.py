"""Writes order notifications to taphoa39khachhang Firestore for real-time sync.

BanHang and DatHang are on different servers, so WebSocket cannot relay events
between them. Instead, after each order CRUD operation, a notification document
is written to the shared `taphoa39khachhang` Firebase project. The BanHang
frontend listens to this collection via Firestore onSnapshot.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from firebase.init_firebase import init_firestore

COLLECTION_NAME = "orderNotifications"

# Reuse the same Firestore project as chat (taphoa39khachhang)
_db = None


def _get_db():
    global _db
    if _db is None:
        _db = init_firestore("FIREBASE_SERVICE_ACCOUNT_CUSTOMER", app_name="order_notify")
    return _db


def notify_order_realtime(action: str, order: Any, order_id: Optional[str] = None) -> None:
    """Write a notification doc to Firestore for real-time pickup by frontends.

    Args:
        action: 'created', 'updated', or 'deleted'
        order: Full order dict (for created/updated) or None (for deleted)
        order_id: Required for 'deleted' action
    """
    try:
        db = _get_db()
        ref = db.collection(COLLECTION_NAME)

        oid = order_id
        if not oid and isinstance(order, dict):
            oid = order.get('id') or order.get('Id')
        if not oid:
            return

        doc_data: Dict[str, Any] = {
            'action': action,
            'orderId': str(oid),
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        }

        if action in ('created', 'updated') and isinstance(order, dict):
            doc_data['order'] = order

        ref.add(doc_data)
    except Exception as e:
        print(f"[order_notify] Error writing notification: {type(e).__name__}: {e}")


def cleanup_old_notifications(hours: int = 24) -> int:
    """Remove notification docs older than `hours`. Call periodically."""
    try:
        db = _get_db()
        ref = db.collection(COLLECTION_NAME)
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + 'Z'
        old_docs = ref.where('timestamp', '<', cutoff).stream()
        count = 0
        for doc in old_docs:
            doc.reference.delete()
            count += 1
        if count > 0:
            print(f"[order_notify] Cleaned up {count} old notifications")
        return count
    except Exception as e:
        print(f"[order_notify] Cleanup error: {type(e).__name__}: {e}")
        return 0
