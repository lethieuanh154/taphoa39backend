from google.api_core.exceptions import ResourceExhausted

try:
    from google.cloud.firestore_v1 import FieldFilter
except ImportError:  # pragma: no cover
    from google.cloud.firestore_v1.base_query import FieldFilter  # type: ignore

from firebase.init_firebase import init_firestore

COLLECTION_NAME = "customers"
INVOICE_COLLECTION_NAME = "invoices"

db = init_firestore("FIREBASE_SERVICE_ACCOUNT_CUSTOMER")
customers_ref = db.collection(COLLECTION_NAME)
invoice_db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON")
invoices_ref = invoice_db.collection(INVOICE_COLLECTION_NAME)


class FirestoreCustomerService:
    def __init__(self, cache):
        self.cache = cache
        self.customers_ref = customers_ref
        self.invoices_ref = invoices_ref

    def add_customer(self, customer):
        doc_ref = self.customers_ref.document(str(customer["id"]))
        doc_ref.set(customer)
        self.cache.invalidate("all_customers")
        return {"message": "customer added"} 
    
    def add_customers(self, customers):
        for customer in customers:
            doc_ref = self.customers_ref.document(str(customer["id"]))
            doc_ref.set(customer)
        self.cache.invalidate("all_customers")
        return {"message": f"{len(customers)} customers added"}
    
    def delete_customers(self, customer_ids) -> dict:
        if not customer_ids:
            return {
                "message": "customer_ids is required",
                "deleted": [],
                "failed": {},
                "deleted_count": 0,
                "failed_count": 0,
                "requested": 0,
            }

        normalized_ids = []
        invalid_inputs = []
        for raw_id in customer_ids:
            if raw_id is None:
                invalid_inputs.append(raw_id)
                continue
            doc_id = str(raw_id).strip()
            if not doc_id:
                invalid_inputs.append(raw_id)
                continue
            normalized_ids.append(doc_id)

        unique_ids = list(dict.fromkeys(normalized_ids))
        if not unique_ids:
            return {
                "message": "customer_ids is invalid",
                "deleted": [],
                "failed": {},
                "deleted_count": 0,
                "failed_count": 0,
                "requested": 0,
                "invalid": invalid_inputs,
            }

        deleted = []
        failed = {}

        for doc_id in unique_ids:
            doc_ref = self.customers_ref.document(doc_id)
            try:
                doc_ref.delete()
                deleted.append(doc_id)
                self.cache.invalidate(doc_id)
            except Exception as exc:
                failed[doc_id] = str(exc)

        if deleted:
            self.cache.invalidate("all_customers")

        return {
            "message": f"deleted {len(deleted)} of {len(unique_ids)} customers",
            "deleted": deleted,
            "failed": failed,
            "deleted_count": len(deleted),
            "failed_count": len(failed),
            "requested": len(unique_ids),
            "invalid": invalid_inputs,
        }

    def read_all_customers(self):
    # Nếu có cache thì dùng, không thì lấy từ Firestore
        if self.cache.has("all_customers"):
            return self.cache.get("all_customers")
        docs = self.customers_ref.stream()
        result = [doc.to_dict() | {"id": doc.id} for doc in docs]
        self.cache.set("all_customers", result, ttl=300)  # Cache 5 phút
        return result

    def get_invoices_by_customer_id(self, customer_id):
        if customer_id is None:
            return []

        normalized_id = str(customer_id).strip()
        if not normalized_id:
            return []

        cache_key = f"invoices_by_customer_id:{normalized_id}"
        if self.cache and self.cache.has(cache_key):
            return self.cache.get(cache_key)

        candidate_ids = {normalized_id}
        try:
            customer_doc = self.customers_ref.document(normalized_id).get()
            if customer_doc.exists:
                customer_data = customer_doc.to_dict() or {}
                for key in ("Id", "id", "CustomerId"):
                    value = customer_data.get(key)
                    if value is not None:
                        candidate_ids.add(str(value))
        except Exception:
            # If customer lookup fails we still fall back to the provided ID
            pass

        invoices = []
        seen_invoice_ids = set()

        def _append_invoice(doc):
            if doc.id in seen_invoice_ids:
                return
            payload = doc.to_dict() or {}
            payload.setdefault("id", doc.id)
            payload.pop("customer", None)
            invoices.append(payload)
            seen_invoice_ids.add(doc.id)

        def _run_field_queries(field_path, values):
            candidates = [str(val).strip() for val in values if str(val).strip()]
            if not candidates:
                return 0

            total = 0
            chunk_size = 10  # Firestore 'in' queries support up to 10 values
            for start in range(0, len(candidates), chunk_size):
                batch = candidates[start:start + chunk_size]
                try:
                    if len(batch) == 1:
                        query = self.invoices_ref.where(filter=FieldFilter(field_path, "==", batch[0]))
                    else:
                        query = self.invoices_ref.where(filter=FieldFilter(field_path, "in", batch))
                    for doc in query.stream():
                        _append_invoice(doc)
                        total += 1
                except ResourceExhausted:
                    raise
                except Exception:
                    continue
            return total

        try:
            total_found = _run_field_queries("customerId", candidate_ids)
            alt_ids = [cid for cid in candidate_ids if cid != normalized_id]

            if total_found == 0:
                for field_path in ("customer.Id", "customer.id", "customer.CustomerId"):
                    total_found += _run_field_queries(field_path, candidate_ids)
                    if total_found > 0:
                        break
            elif alt_ids:
                for field_path in ("customer.Id", "customer.id", "customer.CustomerId"):
                    _run_field_queries(field_path, alt_ids)
        except ResourceExhausted:
            raise

        if self.cache:
            self.cache.set(cache_key, invoices, ttl=120)
        return invoices