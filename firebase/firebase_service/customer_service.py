from google.api_core.exceptions import ResourceExhausted
from dotenv import load_dotenv


load_dotenv()
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

    @staticmethod
    def _to_float(value):
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                cleaned = value.replace(",", "").strip()
                if cleaned == "":
                    return 0.0
                return float(cleaned)
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _to_int(value):
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                cleaned = value.replace(",", "").strip()
                if cleaned == "":
                    return 0
                return int(float(cleaned))
            except ValueError:
                return 0
        return 0

    @staticmethod
    def _extract_customer_id(invoice):
        if not isinstance(invoice, dict):
            return None

        for key in ("customerId", "CustomerId", "customer_id"):
            value = invoice.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()

        customer_info = invoice.get("customer")
        if isinstance(customer_info, dict):
            for key in ("Id", "id", "CustomerId"):
                value = customer_info.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()
        return None

    @staticmethod
    def _get_nested_value(payload, path):
        current = payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @classmethod
    def _resolve_invoice_debt(cls, invoice):
        if not isinstance(invoice, dict):
            return 0.0

        candidate_paths = (
            ("debt",),
            ("Debt",),
            ("customerDebt",),
            ("CustomerDebt",),
            ("remainAmount",),
            ("RemainAmount",),
            ("remainingAmount",),
            ("remainingDebt",),
            ("customer", "debt"),
            ("customer", "Debt"),
            ("payment", "debt"),
            ("payment", "Debt"),
            ("payment", "remaining"),
            ("payment", "remainingAmount"),
        )

        for path in candidate_paths:
            value = cls._get_nested_value(invoice, path)
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            amount = cls._to_float(value)
            if amount != 0.0:
                return abs(round(amount, 2))

        total_price = None
        for path in (("totalPrice",), ("TotalPrice",)):
            value = cls._get_nested_value(invoice, path)
            if value is None:
                continue
            total_price = cls._to_float(value)
            break

        if total_price is None:
            total_price = 0.0

        total_paid = 0.0
        paid_paths = (
            ("totalPaid",),
            ("TotalPaid",),
            ("paid",),
            ("Paid",),
            ("customerPaid",),
            ("CustomerPaid",),
            ("payment", "totalPaid"),
            ("payment", "TotalPaid"),
            ("payment", "paid"),
            ("payment", "Paid"),
            ("payment", "received"),
            ("payment", "receivedAmount"),
        )

        for path in paid_paths:
            value = cls._get_nested_value(invoice, path)
            if value is None:
                continue
            amount = cls._to_float(value)
            if amount > total_paid:
                total_paid = amount

        payments = cls._get_nested_value(invoice, ("payments",))
        if isinstance(payments, list):
            list_total = 0.0
            for entry in payments:
                if isinstance(entry, dict):
                    list_total += cls._to_float(entry.get("amount"))
            if list_total > total_paid:
                total_paid = list_total

        derived = total_price - total_paid
        if derived < 0:
            derived = 0.0
        return round(derived, 2)

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

    def update_customer(self, customer_id: str, updates: dict) -> dict:
        if customer_id is None:
            return {"message": "customer_id is required", "updated": False}

        doc_id = str(customer_id).strip()
        if not doc_id:
            return {"message": "customer_id is invalid", "updated": False}

        if not isinstance(updates, dict) or len(updates) == 0:
            return {"message": "updates must be a non-empty object", "updated": False, "id": doc_id}

        sanitized_updates = {key: value for key, value in updates.items() if key not in (None, "")}
        if not sanitized_updates:
            return {"message": "no valid fields to update", "updated": False, "id": doc_id}

        doc_ref = self.customers_ref.document(doc_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            return {"message": "customer not found", "updated": False, "id": doc_id, "reason": "not_found"}

        try:
            doc_ref.update(sanitized_updates)
            self.cache.invalidate("all_customers")
            self.cache.invalidate(doc_id)
            return {
                "message": "customer updated",
                "updated": True,
                "id": doc_id,
                "changes": sanitized_updates,
            }
        except Exception as exc:
            return {"message": str(exc), "updated": False, "id": doc_id}
    
    def apply_invoice_delta(self, previous_invoice=None, new_invoice=None):
        results = []

        if previous_invoice:
            results.append(self._apply_invoice(previous_invoice, direction=-1))
        if new_invoice:
            results.append(self._apply_invoice(new_invoice, direction=1))

        return results

    def _apply_invoice(self, invoice, direction):
        if direction not in (1, -1):
            raise ValueError("direction must be 1 or -1")

        customer_id = self._extract_customer_id(invoice)
        if not customer_id:
            return {"applied": False, "reason": "no_customer"}

        doc_ref = self.customers_ref.document(customer_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            return {"applied": False, "reason": "customer_not_found", "customer_id": customer_id}

        invoice_debt = self._resolve_invoice_debt(invoice)
        invoice_total_price = self._to_float(invoice.get("totalPrice"))
        invoice_cost = self._to_float(invoice.get("totalCost"))
        invoice_profit = invoice_total_price - invoice_cost

        data = snapshot.to_dict() or {}
        current_debt = self._to_float(data.get("Debt"))
        current_revenue = self._to_float(data.get("TotalRevenue"))
        current_invoiced = self._to_int(data.get("TotalInvoiced"))
        current_profit = self._to_float(data.get("TotalPoint"))

        new_total_invoiced = max(current_invoiced + (direction * 1), 0)
        new_total_debt = current_debt + (direction * invoice_debt)
        new_total_revenue = current_revenue + (direction * invoice_total_price)
        new_total_profit = current_profit + (direction * invoice_profit)

        if new_total_debt < 0:
            new_total_debt = 0.0
        if new_total_revenue < 0:
            new_total_revenue = 0.0
        if new_total_profit < 0:
            new_total_profit = 0.0

        updates = {
            "Debt": round(new_total_debt, 2),
            "TotalRevenue": round(new_total_revenue, 2),
            "TotalInvoiced": new_total_invoiced,
            "TotalPoint": round(new_total_profit, 2),
        }

        try:
            doc_ref.update(updates)
            if self.cache:
                self.cache.invalidate("all_customers")
                self.cache.invalidate(customer_id)
            self.invalidate_invoices_cache(customer_id)
            updated_data = dict(data)
            updated_data.update(updates)
            updated_data["id"] = customer_id
            return {
                "applied": True,
                "customer_id": customer_id,
                "updates": updates,
                "direction": direction,
                "customer": updated_data,
            }
        except Exception as exc:
            return {"applied": False, "reason": str(exc), "customer_id": customer_id}

    def recalculate_customer_totals(self, customer_id):
        if customer_id is None:
            return {"updated": False, "reason": "customer_id_required"}

        normalized_id = str(customer_id).strip()
        if not normalized_id:
            return {"updated": False, "reason": "customer_id_invalid"}

        doc_ref = self.customers_ref.document(normalized_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            return {"updated": False, "reason": "not_found", "customer_id": normalized_id}

        try:
            invoices = self.get_invoices_by_customer_id(normalized_id)
        except ResourceExhausted:
            raise
        except Exception as exc:
            return {
                "updated": False,
                "reason": f"invoice_lookup_failed: {exc}",
                "customer_id": normalized_id,
            }

        total_invoiced = len(invoices)
        total_revenue = 0.0
        total_debt = 0.0

        for invoice in invoices:
            total_revenue += self._to_float(invoice.get("totalPrice"))
            total_debt += self._resolve_invoice_debt(invoice)

        total_point = total_revenue / total_invoiced if total_invoiced else 0.0

        updates = {
            "Debt": round(total_debt, 2),
            "TotalInvoiced": total_invoiced,
            "TotalRevenue": round(total_revenue, 2),
            "TotalPoint": round(total_point, 2),
        }

        try:
            doc_ref.update(updates)
        except Exception as exc:
            return {
                "updated": False,
                "reason": str(exc),
                "customer_id": normalized_id,
            }

        data = snapshot.to_dict() or {}
        data.update(updates)
        data["id"] = normalized_id

        if self.cache:
            self.cache.invalidate("all_customers")
            self.cache.invalidate(normalized_id)

        return {
            "updated": True,
            "customer_id": normalized_id,
            "updates": updates,
            "customer": data,
        }

    def recalculate_customer_from_invoice(self, invoice):
        customer_id = self._extract_customer_id(invoice)
        if not customer_id:
            return {"updated": False, "reason": "no_customer"}

        return self.recalculate_customer_totals(customer_id)

    def refresh_customer_aggregates(self):
        def _to_number(value):
            if value is None:
                return 0.0
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    cleaned = value.replace(",", "").strip()
                    if cleaned == "":
                        return 0.0
                    return float(cleaned)
                except ValueError:
                    return 0.0
            return 0.0

        updated_customers = []
        failures = {}

        errors = {}

        try:
            customer_docs = list(self.customers_ref.stream())
        except Exception as exc:
            raise exc

        for doc in customer_docs:
            customer_id = doc.id
            data = doc.to_dict() or {}
            try:
                invoices = self.get_invoices_by_customer_id(customer_id)
            except ResourceExhausted:
                raise
            except Exception as exc:
                failures[customer_id] = f"invoice_lookup_failed: {exc}"
                continue

            total_invoiced = len(invoices)
            total_revenue = 0.0
            total_debt = 0.0

            for invoice in invoices:
                total_revenue += _to_number(invoice.get("totalPrice"))
                total_debt += self._resolve_invoice_debt(invoice)

            total_point = total_revenue / total_invoiced if total_invoiced else 0.0

            updates = {
                "Debt": round(total_debt, 2),
                "TotalInvoiced": total_invoiced,
                "TotalRevenue": round(total_revenue, 2),
                "TotalPoint": round(total_point, 2),
            }

            try:
                doc.reference.update(updates)
            except Exception as exc:
                failures[customer_id] = f"update_failed: {exc}"
                continue

            data.update(updates)
            data["id"] = customer_id
            updated_customers.append(data)
            if self.cache:
                self.cache.invalidate(customer_id)

        if failures:
            errors["update_failures"] = failures

        if self.cache:
            self.cache.invalidate("all_customers")
            if updated_customers:
                self.cache.set("all_customers", updated_customers, ttl=300)

        return updated_customers, errors

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
        cache_key = "all_customers"
        if self.cache and self.cache.has(cache_key):
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        docs = self.customers_ref.stream()
        result = [doc.to_dict() | {"Id": doc.id} for doc in docs]

        if self.cache:
            self.cache.set(cache_key, result, ttl=300)
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

    def invalidate_invoices_cache(self, customer_ids):
        if not self.cache:
            return

        if customer_ids is None:
            return

        if not isinstance(customer_ids, (list, tuple, set)):
            customer_ids = [customer_ids]

        for raw_id in customer_ids:
            if raw_id is None:
                continue
            normalized = str(raw_id).strip()
            if not normalized:
                continue
            cache_key = f"invoices_by_customer_id:{normalized}"
            self.cache.invalidate(cache_key)