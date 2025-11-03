import os
from calendar import monthrange
from datetime import datetime, timedelta
from typing import List, Tuple

from google.cloud import firestore
from firebase.init_firebase import init_firestore


# Init Firestore (use the invoices project/service account)
# Set FIREBASE_SERVICE_ACCOUNT_HOADON in .env (JSON content)
DB = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON", app_name="hoadon_app")
INV_COLLECTION = "invoices"
BATCH_LIMIT = 400


def _collect_docs_for_month_by_string_date(year: int, month: int, field: str) -> List[firestore.DocumentSnapshot]:
    """Query invoices where string date field is in [YYYY-MM-01, YYYY-MM-last]."""
    last_day = monthrange(year, month)[1]
    start_str = f"{year}-{month:02d}-01"
    end_str = f"{year}-{month:02d}-{last_day:02d}"
    q = (
        DB.collection(INV_COLLECTION)
        .where(field, ">=", start_str)
        .where(field, "<=", end_str)
    )
    return list(q.stream())


def _collect_docs_for_month_by_timestamp(year: int, month: int, field: str) -> List[firestore.DocumentSnapshot]:
    """Query invoices where timestamp field is in [first_day, first_day_next_month)."""
    first_day = datetime(year, month, 1)
    # next month
    if month == 12:
        first_day_next = datetime(year + 1, 1, 1)
    else:
        first_day_next = datetime(year, month + 1, 1)
    q = (
        DB.collection(INV_COLLECTION)
        .where(field, ">=", first_day)
        .where(field, "<", first_day_next)
    )
    return list(q.stream())


def _find_docs_to_delete(year: int, month: int) -> Tuple[List[firestore.DocumentSnapshot], str]:
    """
    Try multiple common date fields. Returns (docs, field_used).
    Order: string fields, then timestamp fields.
    """
    string_fields = ["date", "Date", "invoiceDate", "InvoiceDate", "saleDate", "SaleDate"]
    ts_fields = ["createdAt", "created_at", "CreatedAt", "timestamp", "Timestamp", "createdDate", "CreatedDate"]

    # Try string ISO date
    for f in string_fields:
        docs = _collect_docs_for_month_by_string_date(year, month, f)
        if docs:
            return docs, f

    # Try timestamp
    for f in ts_fields:
        docs = _collect_docs_for_month_by_timestamp(year, month, f)
        if docs:
            return docs, f

    # Nothing found with known fields; last resort: empty result
    return [], ""


def delete_invoices_by_month(year: int, month: int) -> dict:
    """
    Delete all invoices in [YYYY-MM-01, YYYY-MM-last] from Firestore.
    Returns summary dict.
    """
    docs, field_used = _find_docs_to_delete(year, month)
    total = len(docs)
    deleted = 0

    if total == 0:
        return {"deleted": 0, "total_matched": 0, "field": field_used}

    for i in range(0, total, BATCH_LIMIT):
        batch = DB.batch()
        chunk = docs[i : i + BATCH_LIMIT]
        for snap in chunk:
            batch.delete(snap.reference)
        batch.commit()
        deleted += len(chunk)

    return {"deleted": deleted, "total_matched": total, "field": field_used}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Delete invoices by month from Firestore")
    parser.add_argument("--year", type=int, required=True, help="Year, e.g. 2025")
    parser.add_argument("--month", type=int, required=True, help="Month 1-12")
    args = parser.parse_args()

    summary = delete_invoices_by_month(args.year, args.month)
    print(summary)