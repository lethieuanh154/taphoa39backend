"""Kho hoa don TAM TINH - giu trong RAM, khong ghi Firestore.

Nhan vien bam "Tam tinh" ben TapHoa39BanHang de day hoa don chua thanh toan
sang app TapHoa39QRHoaDon, cho khach xem tong tien va quet QR trong luc con
dang goi hang.

VI SAO KHONG GHI FIRESTORE:
Moi ban ghi trong collection `invoices` deu duoc cac bao cao coi la doanh thu
that (adjust_invoice_summaries, apply_invoice_delta, so lieu KeToan). Hoa don
tam tinh co the bi bo giua chung - khach doi y, nhan vien sua gio hang - nen
de no lot vao do la cong khong doanh thu. Giu trong RAM thi khong the ro ri
sang bao cao du co quen loc o dau.

DANH DOI da chap nhan:
- Container restart la mat sach. Chap nhan duoc: hoa don tam chi song vai phut,
  va bam "Tam tinh" lai la co ngay.
- Chi dung duoc vi gunicorn chay `--workers=1` (xem Dockerfile). Neu sau nay
  tang worker, kho nay phai chuyen sang Redis cung luc voi SocketIO message_queue,
  neu khong moi worker se giu mot ban khac nhau.

Het ngay (theo gio Viet Nam) la tu het han, dung yeu cau "ngay hom sau mat".
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# Gio Viet Nam. Khong dung pytz de khoi them dependency chi cho mot phep cong.
_VN_OFFSET = timezone(timedelta(hours=7))

# Tran an toan: hoa don tam khong bao gio nhieu den muc nay trong mot ngay,
# cham tran nghia la co gi do sai chu khong phai ban dat hang.
_MAX_ENTRIES = 500


def _vn_day() -> str:
    return datetime.now(_VN_OFFSET).strftime("%Y-%m-%d")


def _now_iso() -> str:
    """Gio Viet Nam, KHONG kem offset - dung dinh dang paidAt cua BanHang.

    formatVietnamISOString() ben BanHang tra "2026-08-28T09:15:00.000" (naive).
    Neu o day tra kem "+07:00" thi DateTime.parse cua Flutter ra gio UTC, va app
    hien hoa don tam lech 7 tieng so voi hoa don da thanh toan ngay ben canh.
    """
    now = datetime.now(_VN_OFFSET)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


class ProvisionalInvoiceStore:
    """Kho khoa theo invoice id, co them chi muc publicToken cho trang /hd/."""

    def __init__(self, max_entries: int = _MAX_ENTRIES):
        self._lock = threading.RLock()
        self._max_entries = max_entries
        # id -> {"invoice": dict, "day": "YYYY-MM-DD", "updatedAt": iso}
        self._entries: dict[str, dict[str, Any]] = {}
        # publicToken -> id
        self._tokens: dict[str, str] = {}

    # ---------------------------------------------------------------- ghi

    def put(self, invoice: dict) -> Optional[dict]:
        """Them hoac cap nhat mot hoa don tam. Tra ve ban da luu, None neu thieu id."""
        invoice_id = str(invoice.get("id") or "").strip()
        if not invoice_id:
            return None

        stored = dict(invoice)
        stored["isProvisional"] = True
        stored["provisionalAt"] = _now_iso()

        with self._lock:
            self._purge_locked()

            # Bam "Tam tinh" nhieu lan sau khi them hang: token cu phai duoc go
            # khoi chi muc, neu khong no tro toi ban ghi da bi thay the.
            previous = self._entries.get(invoice_id)
            if previous:
                old_token = str(previous["invoice"].get("publicToken") or "").lower()
                if old_token:
                    self._tokens.pop(old_token, None)

            if len(self._entries) >= self._max_entries and invoice_id not in self._entries:
                self._drop_oldest_locked()

            self._entries[invoice_id] = {
                "invoice": stored,
                "day": _vn_day(),
                "updatedAt": stored["provisionalAt"],
            }

            token = str(stored.get("publicToken") or "").lower()
            if token:
                self._tokens[token] = invoice_id

        return stored

    def remove(self, invoice_id: str) -> bool:
        """Go hoa don tam. Goi khi thanh toan xong hoac nhan vien huy."""
        key = str(invoice_id or "").strip()
        if not key:
            return False

        with self._lock:
            entry = self._entries.pop(key, None)
            if not entry:
                return False
            token = str(entry["invoice"].get("publicToken") or "").lower()
            if token:
                self._tokens.pop(token, None)
            return True

    # ---------------------------------------------------------------- doc

    def get(self, invoice_id: str) -> Optional[dict]:
        with self._lock:
            self._purge_locked()
            entry = self._entries.get(str(invoice_id or "").strip())
            return dict(entry["invoice"]) if entry else None

    def get_by_public_token(self, token: str) -> Optional[dict]:
        normalized = str(token or "").lower()
        if not normalized:
            return None

        with self._lock:
            self._purge_locked()
            invoice_id = self._tokens.get(normalized)
            if not invoice_id:
                return None
            entry = self._entries.get(invoice_id)
            return dict(entry["invoice"]) if entry else None

    def list_all(self) -> list[dict]:
        """Toan bo hoa don tam con han. App goi khi tai lai danh sach."""
        with self._lock:
            self._purge_locked()
            return [dict(e["invoice"]) for e in self._entries.values()]

    # ------------------------------------------------------------- noi bo

    def _purge_locked(self) -> None:
        today = _vn_day()
        stale = [k for k, v in self._entries.items() if v["day"] != today]
        for key in stale:
            entry = self._entries.pop(key, None)
            if not entry:
                continue
            token = str(entry["invoice"].get("publicToken") or "").lower()
            if token:
                self._tokens.pop(token, None)

    def _drop_oldest_locked(self) -> None:
        oldest = min(self._entries.items(), key=lambda kv: kv[1]["updatedAt"], default=None)
        if not oldest:
            return
        key, entry = oldest
        self._entries.pop(key, None)
        token = str(entry["invoice"].get("publicToken") or "").lower()
        if token:
            self._tokens.pop(token, None)


# Mot the hien dung chung cho ca ba noi: route tam tinh, add_invoice (go sau khi
# thanh toan) va trang /hd/<token>. Import truc tiep bien nay, dung tao moi.
provisional_store = ProvisionalInvoiceStore()
