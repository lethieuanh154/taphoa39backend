"""
Giu hang cho don dat online (DatHang).

KHONG bao gio tru truc tiep `OnHand` cua product: `OnHand` bi sync_products_from_kiotviet()
ghi de moi lan full reload buoi sang, nen so giu hang phai nam o collection rieng.
Ton hien thi cho khach = OnHand + CloneOnHandNV - Reserved.

Collection: product_reservations/{orderId}
{
  orderId, customerName, customerPhone,
  createdAt, expiresAt,            # ISO, expiresAt = createdAt + RESERVATION_TTL_HOURS
  status: active | released | expired,
  releasedAt, releaseReason,       # checked | canceled | edited | expired
  items: [{ productId, code, name, quantity }]
}

Het han la LAZY: `get_reserved_map()` chi cong don reservation con han, nen du scheduler
co miss (restart, mat dien) thi so ton van dung ngay lap tuc. Scheduler chi lo danh dau
status cho don hien dung mau o BanHang/Management.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

firebase_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(firebase_env_path)

from firebase.init_firebase import init_firestore

db = init_firestore("FIREBASE_SERVICE_ACCOUNT_PRODUCT", app_name="reservation_app")

COLLECTION_NAME = "product_reservations"

RESERVATION_TTL_HOURS = 24

STATUS_ACTIVE = "active"
STATUS_RELEASED = "released"
STATUS_EXPIRED = "expired"

# Cache map giu hang: doc rat nhieu (moi request public product), ghi rat it.
_CACHE_TTL_SECONDS = 60


def _now() -> datetime:
    return datetime.utcnow()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1]
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ReservationService:
    """Giu hang theo don dat online. Khong dung toi OnHand goc."""

    def __init__(self):
        self.db = db
        self._map_cache: Optional[Dict[str, float]] = None
        self._map_cache_at: Optional[datetime] = None

    # ---------- cache ----------

    def _invalidate_cache(self) -> None:
        self._map_cache = None
        self._map_cache_at = None

    def _cache_valid(self) -> bool:
        if self._map_cache is None or self._map_cache_at is None:
            return False
        return (_now() - self._map_cache_at).total_seconds() < _CACHE_TTL_SECONDS

    # ---------- doc ----------

    def _active_docs(self) -> List[Dict[str, Any]]:
        """Moi reservation dang active (ke ca da qua han - caller tu loc)."""
        try:
            docs = self.db.collection(COLLECTION_NAME).where("status", "==", STATUS_ACTIVE).stream()
            data = [d.to_dict() or {} for d in docs]
            print(f"[Reservation] doc {COLLECTION_NAME}: {len(data)} ban giu hang status=active")
            return data
        except Exception as e:
            print(f"[Reservation] LOI: Loi doc reservation active: {type(e).__name__}: {e}")
            return []

    def create_for_order(self, order_id: str, customer: Optional[Dict[str, Any]],
                         items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Tao ban giu hang cho 1 don. items: [{productId, code, name, quantity}].
        Doc id = orderId nen dat lai cung don se ghi de, khong nhan doi so giu."""
        clean_items = []
        for it in items or []:
            pid = str(it.get("productId") or "")
            qty = _to_float(it.get("quantity"))
            if not pid or qty <= 0:
                continue
            clean_items.append({
                "productId": pid,
                "code": it.get("code") or "",
                "name": it.get("name") or "",
                "quantity": qty,
            })

        if not clean_items:
            return {"success": False, "error": "Khong co dong hang hop le de giu"}

        created = _now()
        payload = {
            "orderId": str(order_id),
            "customerName": (customer or {}).get("Name") or "",
            "customerPhone": (customer or {}).get("ContactNumber") or "",
            "createdAt": _iso(created),
            "expiresAt": _iso(created + timedelta(hours=RESERVATION_TTL_HOURS)),
            "status": STATUS_ACTIVE,
            "releasedAt": None,
            "releaseReason": None,
            "items": clean_items,
        }

        try:
            self.db.collection(COLLECTION_NAME).document(str(order_id)).set(payload)
            self._invalidate_cache()
            print(f"[Reservation] Ghi {COLLECTION_NAME}/{order_id}: "
                  f"{len(clean_items)} mat hang, het han {payload['expiresAt']}")
            return {"success": True, "reservation": payload}
        except Exception as e:
            print(f"[Reservation] LOI: Loi tao reservation {order_id}: {type(e).__name__}: {e}")
            return {"success": False, "error": str(e)}

    def release(self, order_id: str, reason: str = "released") -> Dict[str, Any]:
        """Nha hang da giu. Goi khi: don thanh hoa don (checked), huy don, sua don.
        KHONG cong lai OnHand - OnHand chua bao gio bi tru."""
        try:
            doc_ref = self.db.collection(COLLECTION_NAME).document(str(order_id))
            snap = doc_ref.get()
            if not snap.exists:
                return {"success": True, "released": False, "message": "Khong co ban giu hang"}

            data = snap.to_dict() or {}
            if data.get("status") != STATUS_ACTIVE:
                return {"success": True, "released": False, "message": "Ban giu hang da dong"}

            doc_ref.update({
                "status": STATUS_EXPIRED if reason == "expired" else STATUS_RELEASED,
                "releasedAt": _iso(_now()),
                "releaseReason": reason,
            })
            self._invalidate_cache()
            return {"success": True, "released": True}
        except Exception as e:
            print(f"[Reservation] LOI: Loi nha reservation {order_id}: {type(e).__name__}: {e}")
            return {"success": False, "error": str(e)}

    # ---------- doc so lieu ----------

    def get_reserved_map(self) -> Dict[str, float]:
        """{productId: so luong dang giu}. Chi tinh reservation active VA con han."""
        if self._cache_valid():
            return self._map_cache or {}

        now = _now()
        reserved: Dict[str, float] = {}
        for data in self._active_docs():
            expires = _parse_iso(data.get("expiresAt"))
            if expires and expires <= now:
                continue  # qua han -> coi nhu khong ton tai (lazy expiry)
            for it in data.get("items") or []:
                pid = str(it.get("productId") or "")
                if not pid:
                    continue
                reserved[pid] = reserved.get(pid, 0.0) + _to_float(it.get("quantity"))

        self._map_cache = reserved
        self._map_cache_at = now
        print(f"[Reservation] reserved map: {len(reserved)} san pham dang duoc giu")
        return reserved

    def get_reserved_for(self, product_id: str) -> float:
        return self.get_reserved_map().get(str(product_id), 0.0)

    def list_active(self, include_expired: bool = False) -> List[Dict[str, Any]]:
        """Danh sach ban giu hang cho trang quan ly. Moi ban co them `isExpired`."""
        now = _now()
        result = []
        for data in self._active_docs():
            expires = _parse_iso(data.get("expiresAt"))
            is_expired = bool(expires and expires <= now)
            if is_expired and not include_expired:
                continue
            data["isExpired"] = is_expired
            result.append(data)
        result.sort(key=lambda d: d.get("createdAt") or "", reverse=True)
        print(f"[Reservation] list_active(include_expired={include_expired}): tra ve {len(result)} ban")
        return result

    def expire_overdue(self) -> Dict[str, Any]:
        """Danh dau cac ban giu hang qua han -> status=expired.
        Tra ve orderIds de caller cap nhat status don hang tuong ung.
        An toan khi chay lai: chi dung toi doc con active."""
        now = _now()
        expired_ids: List[str] = []
        try:
            docs = self.db.collection(COLLECTION_NAME).where("status", "==", STATUS_ACTIVE).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                expires = _parse_iso(data.get("expiresAt"))
                if not expires or expires > now:
                    continue
                doc.reference.update({
                    "status": STATUS_EXPIRED,
                    "releasedAt": _iso(now),
                    "releaseReason": "expired",
                })
                expired_ids.append(str(data.get("orderId") or doc.id))
        except Exception as e:
            print(f"[Reservation] LOI: Loi danh dau het han: {type(e).__name__}: {e}")
            return {"success": False, "error": str(e), "expired": []}

        if expired_ids:
            self._invalidate_cache()
            print(f"[Reservation] Danh dau het han {len(expired_ids)} ban giu hang")
        return {"success": True, "expired": expired_ids, "count": len(expired_ids)}

    def clear_old(self, keep_days: int = 7) -> Dict[str, Any]:
        """Xoa ban giu hang da dong va cu hon keep_days. Giu doc active du cu."""
        cutoff = _iso(_now() - timedelta(days=keep_days))
        deleted = 0
        try:
            docs = self.db.collection(COLLECTION_NAME).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                if data.get("status") == STATUS_ACTIVE:
                    continue
                if (data.get("createdAt") or "") >= cutoff:
                    continue
                doc.reference.delete()
                deleted += 1
        except Exception as e:
            print(f"[Reservation] LOI: Loi don ban giu hang cu: {type(e).__name__}: {e}")
            return {"success": False, "error": str(e)}

        print(f"[Reservation] Xoa {deleted} ban giu hang cu (truoc {cutoff})")
        return {"success": True, "deleted": deleted, "cutoff": cutoff}
