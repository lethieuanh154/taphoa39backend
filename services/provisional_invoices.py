"""Kho hoa don TAM TINH - collection Firestore rieng, KHONG phai `invoices`.

Nhan vien bam "Tam tinh" ben TapHoa39BanHang de day hoa don chua thanh toan
sang app TapHoa39QRHoaDon, cho khach xem tong tien va quet QR trong luc con
dang goi hang.

VI SAO COLLECTION RIENG chu khong phai `invoices`:
Moi ban ghi trong `invoices` deu duoc coi la doanh thu that (adjust_invoice_summaries,
apply_invoice_delta, so lieu KeToan). Hoa don tam co the bi bo giua chung - khach
doi y, nhan vien sua gio hang - nen de no lot vao do la cong khong doanh thu.
Tach collection thi khong the ro ri sang bao cao du co quen loc o dau.

VI SAO KHONG GIU TRONG RAM (ban dau lam vay, da phai doi):
May POS chay Flask local, con dien thoai khach chay 4G nen mo /hd/<token> qua
VPS. Hoa don tam nam trong RAM may POS thi VPS khong tra duoc - khach quet QR ra
404. Firestore dung chung nen backend nao cung doc duoc.

DON CUOI NGAY:
Moi ban ghi mang `provisionalDay` (ngay gio Viet Nam). Doc va ghi deu loc theo
ngay hom nay, va don ban ghi cu mot lan moi ngay (_maybe_purge). Hoa don khach
bo giua chung khong bao gio song sang ngay hom sau.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from google.cloud.firestore_v1.base_query import FieldFilter

from firebase.init_firebase import init_firestore

COLLECTION_NAME = "provisional_invoices"

# Cung service account voi collection `invoices` - van la hoa don, chi khac vong doi.
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON")

# Gio Viet Nam. Khong dung pytz de khoi them dependency chi cho mot phep cong.
_VN_OFFSET = timezone(timedelta(hours=7))

# Firestore gioi han 500 thao tac moi batch.
_BATCH_LIMIT = 500


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
    """CRUD tren collection `provisional_invoices`, doc id = invoice id.

    Khong cache: bam "Tam tinh" lai sau khi them hang la noi dung doi ngay, cache
    cu se cho khach xem so tien sai.
    """

    def __init__(self, collection_name: str = COLLECTION_NAME):
        self._ref = db.collection(collection_name)
        self._purge_lock = threading.Lock()
        self._purged_day: Optional[str] = None

    # ---------------------------------------------------------------- ghi

    def put(self, invoice: dict) -> Optional[dict]:
        """Them hoac ghi de mot hoa don tam. Tra ve ban da luu, None neu thieu id."""
        invoice_id = str(invoice.get("id") or "").strip()
        if not invoice_id:
            return None

        self._maybe_purge()

        stored = dict(invoice)
        stored["id"] = invoice_id
        stored["isProvisional"] = True
        stored["provisionalAt"] = _now_iso()
        stored["provisionalDay"] = _vn_day()

        # set() ghi de toan bo: gio hang co the da bot mon so voi lan bam truoc,
        # merge se giu lai rac cua lan cu.
        self._ref.document(invoice_id).set(stored)
        return stored

    def remove(self, invoice_id: str) -> bool:
        """Go hoa don tam. Goi khi thanh toan xong hoac nhan vien dong tab."""
        key = str(invoice_id or "").strip()
        if not key:
            return False

        doc_ref = self._ref.document(key)
        if not doc_ref.get().exists:
            return False

        doc_ref.delete()
        return True

    # ---------------------------------------------------------------- doc

    def get(self, invoice_id: str) -> Optional[dict]:
        key = str(invoice_id or "").strip()
        if not key:
            return None

        snapshot = self._ref.document(key).get()
        if not snapshot.exists:
            return None

        return self._materialize(snapshot)

    def get_by_public_token(self, token: str) -> Optional[dict]:
        """Tra hoa don tam theo token cong khai, cho trang /hd/<token>."""
        normalized = str(token or "").lower()
        if not normalized:
            return None

        docs = self._ref.where(
            filter=FieldFilter("publicToken", "==", normalized)
        ).limit(1).stream()

        for doc in docs:
            return self._materialize(doc)
        return None

    def list_all(self) -> list[dict]:
        """Hoa don tam CUA HOM NAY. App goi khi tai lai danh sach.

        Loc theo ngay chu khong lay het: neu don dep loi vi ly do nao do, danh
        sach van khong dinh hoa don hom qua.
        """
        self._maybe_purge()

        docs = self._ref.where(
            filter=FieldFilter("provisionalDay", "==", _vn_day())
        ).stream()

        return [self._materialize(doc) for doc in docs]

    # ------------------------------------------------------------- don dep

    def purge_old(self) -> int:
        """Xoa moi hoa don tam cua nhung ngay truoc. Tra ve so ban ghi da xoa."""
        today = _vn_day()
        deleted = 0

        while True:
            # provisionalDay dang YYYY-MM-DD nen so sanh chuoi cung la so sanh ngay.
            stale = list(
                self._ref.where(filter=FieldFilter("provisionalDay", "<", today))
                .limit(_BATCH_LIMIT)
                .stream()
            )
            if not stale:
                break

            batch = db.batch()
            for doc in stale:
                batch.delete(doc.reference)
            batch.commit()
            deleted += len(stale)

            if len(stale) < _BATCH_LIMIT:
                break

        if deleted:
            print(f"[provisional] da don {deleted} hoa don tam cua ngay truoc")
        return deleted

    # ------------------------------------------------------------- noi bo

    def _maybe_purge(self) -> None:
        """Don mot lan moi ngay, kich hoat boi luot doc/ghi dau tien.

        Khong dung scheduler: may co the tat qua dem, va don theo su kien thi
        khong phu thuoc vao tien trinh con song luc nua dem.
        """
        today = _vn_day()
        if self._purged_day == today:
            return

        with self._purge_lock:
            if self._purged_day == today:
                return
            try:
                self.purge_old()
                self._purged_day = today
            except Exception as exc:
                # Don dep that bai khong duoc chan viec ban hang. Lan doc sau thu lai.
                print(f"[provisional] don ngay cu that bai: {exc}")

    @staticmethod
    def _materialize(doc) -> dict:
        return (doc.to_dict() or {}) | {"id": doc.id}


# Mot the hien dung chung cho ca ba noi: route tam tinh, add_invoice (go sau khi
# thanh toan) va trang /hd/<token>. Import truc tiep bien nay, dung tao moi.
provisional_store = ProvisionalInvoiceStore()
