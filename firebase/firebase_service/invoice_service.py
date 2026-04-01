from datetime import datetime
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from google.api_core.exceptions import DeadlineExceeded
from google.cloud.firestore_v1 import Increment

from dotenv import load_dotenv

from firebase.init_firebase import init_firestore

load_dotenv()

# Khởi tạo Firebase
COLLECTION_NAME = "invoices"

# Đặt tên app duy nhất cho mỗi service account
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON")
# Chuyển chuỗi JSON thành dict và tạo credential


def _retry_on_deadline(operation, max_retries=3, initial_delay=1, operation_name="Firestore operation"):
    """
    Retry wrapper for Firestore operations that may timeout.
    Uses exponential backoff for retries.
    """
    retry_delay = initial_delay
    for attempt in range(max_retries):
        try:
            return operation()
        except DeadlineExceeded as e:
            if attempt < max_retries - 1:
                print(f"{operation_name} timeout on attempt {attempt + 1}/{max_retries}, retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"{operation_name} failed after {max_retries} attempts: {str(e)}")
                raise Exception(f"Firestore timeout after {max_retries} attempts. Please check your network connection.")


class FirestoreInvoiceService:
    def __init__(self, cache):
        self.cache = cache
        self.invoices_ref = db.collection(COLLECTION_NAME)

    def stream_invoices(self):
        docs = self.invoices_ref.stream()
        for doc in docs:
            data = doc.to_dict() or {}
            yield data | {"id": doc.id}

    def read_invoice(self, invoice_id):
        if self.cache.has(invoice_id):
            return self.cache.get(invoice_id)

        doc = self.invoices_ref.document(invoice_id).get()
        if doc.exists:
            invoice = doc.to_dict()
            self.cache.set(invoice_id, invoice, ttl=300)
            return invoice
        return None

    def get_invoices_by_date(self, date):
        """
        Get invoices for a specific date (full day)
        Expected date format: YYYY-MM-DD (e.g., "2025-06-17")
        """
        try:
            # Create string for comparison in ISO format for start and end of day
            start_str = f"{date}T00:00:00.000Z"
            end_str = f"{date}T23:59:59.999Z"

            # Query Firestore with string
            query = self.invoices_ref \
                .where('createdDate', '>=', start_str) \
                .where('createdDate', '<=', end_str)
            invoices = query.stream()
            return [invoice.to_dict() for invoice in invoices]
        except Exception as e:
            raise Exception(f"Error getting invoices by date: {str(e)}")

    def get_invoices_by_status(self, status: str):
        """
        Get invoices by status
        """
        try:
            query = self.invoices_ref.where('status', '==', status)
            invoices = query.stream()
            return [invoice.to_dict() for invoice in invoices]
        except Exception as e:
            raise Exception(f"Error getting invoices by status: {str(e)}")

    def get_invoices_by_customer(self, customer_id: str):
        """
        Get invoices by customer ID
        """
        try:
            # Assuming customerId is stored in 'customerId' field
            query = self.invoices_ref.where('customerId', '==', customer_id)
            invoices = query.stream()
            return [invoice.to_dict() for invoice in invoices]
        except Exception as e:
            raise Exception(f"Error getting invoices by customer: {str(e)}")

    def add_invoice(self, invoice):
        doc_ref = self.invoices_ref.document(str(invoice["id"]))

        def _add_operation():
            doc_ref.set(invoice, timeout=30.0)
            self.cache.invalidate("all_invoices")
            self.cache.invalidate(str(invoice["id"]))
            return {"message": "invoice added"}

        return _retry_on_deadline(_add_operation, operation_name=f"Add invoice {invoice['id']}")

    def update_invoice(self, invoice_id, updates):
        doc_ref = self.invoices_ref.document(invoice_id)

        def _update_operation():
            doc_ref.update(updates, timeout=30.0)
            self.cache.invalidate(invoice_id)
            self.cache.invalidate("all_invoices")
            return {"message": "invoice updated"}

        return _retry_on_deadline(_update_operation, operation_name=f"Update invoice {invoice_id}")

    def delete_invoice(self, invoice_id):
        def _delete_operation():
            self.invoices_ref.document(invoice_id).delete(timeout=30.0)
            self.cache.invalidate(invoice_id)
            self.cache.invalidate("all_invoices")
            return {"message": "invoice deleted"}

        return _retry_on_deadline(_delete_operation, operation_name=f"Delete invoice {invoice_id}")

    def adjust_invoice_summaries(self, invoice: dict, direction: int) -> dict:
        if invoice is None or not isinstance(invoice, dict):
            return {"updated": False, "reason": "invalid_invoice"}

        if direction not in (1, -1):
            return {"updated": False, "reason": "invalid_direction"}

        totals = self._compute_invoice_totals(invoice)
        if totals["buyer_quantity"] == 0:
            return {"updated": False, "reason": "no_totals"}

        keys = self._extract_summary_keys(invoice)
        if keys["date"] is None:
            return {"updated": False, "reason": "missing_date"}

        deltas = {
            "revenue": direction * totals["revenue"],
            "cost": direction * totals["cost"],
            "profit": direction * totals["profit"],
            "buyer_quantity": direction * totals["buyer_quantity"],
            "kvRevenue": direction * totals.get("kvRevenue", 0),
            "kvCost": direction * totals.get("kvCost", 0),
            "kvProfit": direction * totals.get("kvProfit", 0),
            "kvVat": direction * totals.get("kvVat", 0),
            "kvVatInput": direction * totals.get("kvVatInput", 0),
            "kvVatPayable": direction * totals.get("kvVatPayable", 0),
            "nvRevenue": direction * totals.get("nvRevenue", 0),
            "nvCost": direction * totals.get("nvCost", 0),
            "nvProfit": direction * totals.get("nvProfit", 0),
        }

        # Run all summary updates in parallel (they are independent docs)
        tasks = [("DailySummary", keys["date"])]
        if keys["month"]:
            tasks.append(("MonthlySummary", keys["month"]))
        if keys["year"]:
            tasks.append(("YearlySummary", keys["year"]))

        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = [executor.submit(self._apply_summary_delta, coll, doc_id, deltas) for coll, doc_id in tasks]
            for f in futures:
                f.result()

        return {
            "updated": True,
            "keys": keys,
            "deltas": deltas,
        }

    def _compute_invoice_totals(self, invoice: dict) -> dict:
        """
        Tính tổng revenue/cost/profit cho invoice, tách bạch KV (gốc) và NV (clone).
        Duyệt cartItems để phân loại từng item.
        """
        kv_revenue = 0.0
        kv_cost = 0.0
        kv_vat = 0.0
        kv_vat_input = 0.0
        nv_revenue = 0.0
        nv_cost = 0.0

        cart_items = invoice.get("cartItems", [])
        has_cart_items = isinstance(cart_items, list) and len(cart_items) > 0

        if has_cart_items:
            for item in cart_items:
                if not isinstance(item, dict):
                    continue
                product = item.get("product", {}) if isinstance(item, dict) else {}
                quantity = self.safe_int(item.get("quantity", 0))
                price = self.safe_float(
                    item.get("unitPrice")
                    or item.get("price")
                    or product.get("BasePrice")
                    or product.get("Price")
                )
                cost_price = self.safe_float(product.get("Cost"))
                item_revenue = price * quantity
                item_cost = cost_price * quantity

                if self._is_clone_product(product):
                    nv_revenue += item_revenue
                    nv_cost += item_cost
                else:
                    kv_revenue += item_revenue
                    kv_cost += item_cost
                    tax_rate = self.safe_float(product.get("Tax", 0))
                    if tax_rate > 0:
                        kv_vat += item_revenue * tax_rate / 100
                        kv_vat_input += item_cost * tax_rate / 100
        else:
            # Fallback: dùng invoice-level totals (không thể split)
            total_revenue = self.safe_float(
                invoice.get("totalPrice")
                or invoice.get("TotalPrice")
                or invoice.get("grandTotal")
            )
            total_cost = self.safe_float(
                invoice.get("totalCost")
                or invoice.get("TotalCost")
                or invoice.get("costTotal")
            )
            kv_revenue = total_revenue
            kv_cost = total_cost

        revenue = kv_revenue + nv_revenue
        cost = kv_cost + nv_cost
        profit = revenue - cost

        return {
            "revenue": round(revenue, 2),
            "cost": round(cost, 2),
            "profit": round(profit, 2),
            "buyer_quantity": 1,
            "kvRevenue": round(kv_revenue, 2),
            "kvCost": round(kv_cost, 2),
            "kvProfit": round(kv_revenue - kv_cost, 2),
            "kvVat": round(kv_vat, 2),
            "kvVatInput": round(kv_vat_input, 2),
            "kvVatPayable": round(kv_vat - kv_vat_input, 2),
            "nvRevenue": round(nv_revenue, 2),
            "nvCost": round(nv_cost, 2),
            "nvProfit": round(nv_revenue - nv_cost, 2),
        }

    def _extract_summary_keys(self, invoice: dict) -> dict:
        created = (
            invoice.get("createdDate")
            or invoice.get("CreatedDate")
            or invoice.get("date")
            or invoice.get("Date")
        )

        date_str = None
        if created:
            if isinstance(created, datetime):
                date_str = created.date().isoformat()
            else:
                created_str = str(created)
                if len(created_str) >= 10:
                    date_str = created_str[:10]

        if not date_str:
            return {"date": None, "month": None, "year": None}

        try:
            year = date_str[:4]
            month = date_str[:7]
        except Exception:
            year = None
            month = None

        return {"date": date_str, "month": month, "year": year}

    def _apply_summary_delta(self, collection: str, doc_id: str, delta: dict) -> None:
        """Apply delta to summary doc using Increment (no read needed, atomic server-side)."""
        if not doc_id:
            return

        doc_ref = db.collection(collection).document(doc_id)

        payload = {
            "revenue": Increment(delta["revenue"]),
            "cost": Increment(delta["cost"]),
            "profit": Increment(delta["profit"]),
            "buyer_quantity": Increment(delta["buyer_quantity"]),
            "kvRevenue": Increment(delta.get("kvRevenue", 0)),
            "kvCost": Increment(delta.get("kvCost", 0)),
            "kvProfit": Increment(delta.get("kvProfit", 0)),
            "kvVat": Increment(delta.get("kvVat", 0)),
            "kvVatInput": Increment(delta.get("kvVatInput", 0)),
            "kvVatPayable": Increment(delta.get("kvVatPayable", 0)),
            "nvRevenue": Increment(delta.get("nvRevenue", 0)),
            "nvCost": Increment(delta.get("nvCost", 0)),
            "nvProfit": Increment(delta.get("nvProfit", 0)),
        }

        if collection == "DailySummary":
            payload["date"] = doc_id
        elif collection == "MonthlySummary":
            payload["month"] = doc_id
        elif collection == "YearlySummary":
            payload["year"] = doc_id

        payload["lastUpdated"] = datetime.utcnow().isoformat() + "Z"

        doc_ref.set(payload, merge=True)

    

    def safe_float(self, val):
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    def safe_int(self, val):
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    def _is_clone_product(self, product: dict) -> bool:
        """
        Xác định product là clone (NV) hay gốc (KiotViet).
        """
        is_clone = product.get("isClone")
        if is_clone is True or is_clone == "true":
            return True
        on_hand_nv = self.safe_float(product.get("OnHandNV", 0))
        on_hand = self.safe_float(product.get("OnHand", 0))
        if on_hand_nv > 0 and on_hand == 0:
            return True
        return False

    def calculate_daily_summary(self, date):
        invoices = self.get_invoices_by_date(date)
        revenue = 0
        cost = 0
        kv_revenue = 0
        kv_cost = 0
        kv_vat = 0
        kv_vat_input = 0
        nv_revenue = 0
        nv_cost = 0
        for invoice in invoices:
            cart_items = invoice.get('cartItems', [])
            has_cart_items = isinstance(cart_items, list) and len(cart_items) > 0

            if has_cart_items:
                for item in cart_items:
                    if not isinstance(item, dict):
                        continue
                    product = item.get('product', {}) if isinstance(item, dict) else {}
                    quantity = self.safe_int(item.get('quantity', 0))
                    price = self.safe_float(
                        item.get('unitPrice')
                        or item.get('price')
                        or product.get('BasePrice')
                        or product.get('Price')
                    )
                    cost_price = self.safe_float(product.get('Cost', 0))
                    item_revenue = price * quantity
                    item_cost = cost_price * quantity
                    revenue += item_revenue
                    cost += item_cost

                    if self._is_clone_product(product):
                        nv_revenue += item_revenue
                        nv_cost += item_cost
                    else:
                        kv_revenue += item_revenue
                        kv_cost += item_cost
                        tax_rate = self.safe_float(product.get('Tax', 0))
                        if tax_rate > 0:
                            kv_vat += item_revenue * tax_rate / 100
                            kv_vat_input += item_cost * tax_rate / 100
            else:
                # Fallback: invoice không có cartItems → dùng invoice-level totals
                total_revenue = self.safe_float(
                    invoice.get('totalPrice')
                    or invoice.get('TotalPrice')
                    or invoice.get('grandTotal')
                )
                total_cost = self.safe_float(
                    invoice.get('totalCost')
                    or invoice.get('TotalCost')
                    or invoice.get('costTotal')
                )
                revenue += total_revenue
                cost += total_cost
                kv_revenue += total_revenue
                kv_cost += total_cost

        profit = revenue - cost
        summary = {
            'buyer_quantity': len(invoices),
            'date': date,
            'revenue': round(revenue, 2),
            'cost': round(cost, 2),
            'profit': round(profit, 2),
            'kvRevenue': round(kv_revenue, 2),
            'kvCost': round(kv_cost, 2),
            'kvProfit': round(kv_revenue - kv_cost, 2),
            'kvVat': round(kv_vat, 2),
            'kvVatInput': round(kv_vat_input, 2),
            'kvVatPayable': round(kv_vat - kv_vat_input, 2),
            'nvRevenue': round(nv_revenue, 2),
            'nvCost': round(nv_cost, 2),
            'nvProfit': round(nv_revenue - nv_cost, 2),
        }
        summary_ref = db.collection('DailySummary').document(date)
        summary_ref.set(summary)
        return summary

    def get_daily_summary(self, date, recalculate=False):
        """Đọc từ DailySummary collection (1 read). Fallback calculate nếu chưa có."""
        if not recalculate:
            doc = db.collection('DailySummary').document(date).get()
            if doc.exists:
                return doc.to_dict()
        return self.calculate_daily_summary(date)

    def calculate_monthly_summary(self, year, month):
        """
        Tính revenue, cost, profit cho 1 tháng, sử dụng collection DailySummary thay vì gọi calculate_daily_summary
        """
        from calendar import monthrange
        days_in_month = monthrange(int(year), int(month))[1]
        revenue = 0
        cost = 0
        buyer_quantity = 0
        kv_revenue = 0
        kv_cost = 0
        kv_vat = 0
        kv_vat_input = 0
        nv_revenue = 0
        nv_cost = 0
        for day in range(1, days_in_month + 1):
            date_str = f"{year}-{str(month).zfill(2)}-{str(day).zfill(2)}"
            # Luôn recalculate từ invoices để đảm bảo data mới nhất
            daily = self.calculate_daily_summary(date_str)
            revenue += daily.get('revenue', 0)
            cost += daily.get('cost', 0)
            buyer_quantity += daily.get('buyer_quantity', 0)
            kv_revenue += daily.get('kvRevenue', 0)
            kv_cost += daily.get('kvCost', 0)
            kv_vat += daily.get('kvVat', 0)
            kv_vat_input += daily.get('kvVatInput', 0)
            nv_revenue += daily.get('nvRevenue', 0)
            nv_cost += daily.get('nvCost', 0)
        profit = revenue - cost
        doc_id = f"{year}-{str(month).zfill(2)}"
        summary = {
            'buyer_quantity': buyer_quantity,
            'month': doc_id,
            'revenue': round(revenue, 2),
            'cost': round(cost, 2),
            'profit': round(profit, 2),
            'kvRevenue': round(kv_revenue, 2),
            'kvCost': round(kv_cost, 2),
            'kvProfit': round(kv_revenue - kv_cost, 2),
            'kvVat': round(kv_vat, 2),
            'kvVatInput': round(kv_vat_input, 2),
            'kvVatPayable': round(kv_vat - kv_vat_input, 2),
            'nvRevenue': round(nv_revenue, 2),
            'nvCost': round(nv_cost, 2),
            'nvProfit': round(nv_revenue - nv_cost, 2),
        }
        summary_ref = db.collection('MonthlySummary').document(doc_id)
        summary_ref.set(summary)
        return summary
    def get_monthly_summary(self, year, month, recalculate=False):
        """Đọc từ MonthlySummary collection (1 read). Fallback calculate nếu chưa có."""
        doc_id = f"{year}-{str(month).zfill(2)}"
        if not recalculate:
            doc = db.collection('MonthlySummary').document(doc_id).get()
            if doc.exists:
                return doc.to_dict()
        return self.calculate_monthly_summary(year, month)

    def calculate_yearly_summary(self, year):
        """
        Tính revenue, cost, profit cho 1 năm, sử dụng collection MonthlySummary thay vì gọi calculate_monthly_summary
        """
        revenue = 0
        cost = 0
        buyer_quantity = 0
        kv_revenue = 0
        kv_cost = 0
        kv_vat = 0
        kv_vat_input = 0
        nv_revenue = 0
        nv_cost = 0
        for month in range(1, 13):
            # Luôn recalculate từ daily summaries để đảm bảo data mới nhất
            monthly = self.calculate_monthly_summary(year, month)
            revenue += monthly.get('revenue', 0)
            cost += monthly.get('cost', 0)
            buyer_quantity += monthly.get('buyer_quantity', 0)
            kv_revenue += monthly.get('kvRevenue', 0)
            kv_cost += monthly.get('kvCost', 0)
            kv_vat += monthly.get('kvVat', 0)
            kv_vat_input += monthly.get('kvVatInput', 0)
            nv_revenue += monthly.get('nvRevenue', 0)
            nv_cost += monthly.get('nvCost', 0)
        profit = revenue - cost
        summary = {
            'buyer_quantity': buyer_quantity,
            'year': str(year),
            'revenue': round(revenue, 2),
            'cost': round(cost, 2),
            'profit': round(profit, 2),
            'kvRevenue': round(kv_revenue, 2),
            'kvCost': round(kv_cost, 2),
            'kvProfit': round(kv_revenue - kv_cost, 2),
            'kvVat': round(kv_vat, 2),
            'kvVatInput': round(kv_vat_input, 2),
            'kvVatPayable': round(kv_vat - kv_vat_input, 2),
            'nvRevenue': round(nv_revenue, 2),
            'nvCost': round(nv_cost, 2),
            'nvProfit': round(nv_revenue - nv_cost, 2),
        }
        summary_ref = db.collection('YearlySummary').document(str(year))
        summary_ref.set(summary)
        return summary

    def get_yearly_summary(self, year, recalculate=False):
        """Đọc từ YearlySummary collection (1 read). Fallback calculate nếu chưa có."""
        if not recalculate:
            doc = db.collection('YearlySummary').document(str(year)).get()
            if doc.exists:
                return doc.to_dict()
        return self.calculate_yearly_summary(year)

    def calculate_date_range_summary(self, start_date, end_date):
        """
        Tính tổng hợp summary cho khoảng ngày từ start_date đến end_date (inclusive).
        Aggregate từ calculate_daily_summary cho mỗi ngày trong range.
        """
        from datetime import datetime as dt, timedelta
        start = dt.strptime(start_date, "%Y-%m-%d")
        end = dt.strptime(end_date, "%Y-%m-%d")
        revenue = 0
        cost = 0
        buyer_quantity = 0
        kv_revenue = 0
        kv_cost = 0
        kv_vat = 0
        kv_vat_input = 0
        nv_revenue = 0
        nv_cost = 0
        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            daily = self.calculate_daily_summary(date_str)
            revenue += daily.get('revenue', 0)
            cost += daily.get('cost', 0)
            buyer_quantity += daily.get('buyer_quantity', 0)
            kv_revenue += daily.get('kvRevenue', 0)
            kv_cost += daily.get('kvCost', 0)
            kv_vat += daily.get('kvVat', 0)
            kv_vat_input += daily.get('kvVatInput', 0)
            nv_revenue += daily.get('nvRevenue', 0)
            nv_cost += daily.get('nvCost', 0)
            current += timedelta(days=1)
        profit = revenue - cost
        return {
            'buyer_quantity': buyer_quantity,
            'start_date': start_date,
            'end_date': end_date,
            'revenue': round(revenue, 2),
            'cost': round(cost, 2),
            'profit': round(profit, 2),
            'kvRevenue': round(kv_revenue, 2),
            'kvCost': round(kv_cost, 2),
            'kvProfit': round(kv_revenue - kv_cost, 2),
            'kvVat': round(kv_vat, 2),
            'kvVatInput': round(kv_vat_input, 2),
            'kvVatPayable': round(kv_vat - kv_vat_input, 2),
            'nvRevenue': round(nv_revenue, 2),
            'nvCost': round(nv_cost, 2),
            'nvProfit': round(nv_revenue - nv_cost, 2),
        }
    
    def calculate_top_products_summary(self, date=None, year=None, month=None):
        """
        Tính top sản phẩm theo totalProfit, lưu vào Firestore collection TopProductsSummary.
        Nếu truyền date, year, month thì lưu theo từng mốc thời gian.
        """
        from collections import defaultdict
        product_sales = {}

        # Lấy invoices theo thời gian
        if date:
            invoices = self.get_invoices_by_date(date)
            doc_id = date
        elif year and month:
            from calendar import monthrange
            days_in_month = monthrange(int(year), int(month))[1]
            invoices = []
            for day in range(1, days_in_month + 1):
                date_str = f"{year}-{str(month).zfill(2)}-{str(day).zfill(2)}"
                invoices.extend(self.get_invoices_by_date(date_str))
            doc_id = f"{year}-{str(month).zfill(2)}"
        elif year:
            invoices = []
            for m in range(1, 13):
                from calendar import monthrange
                days_in_month = monthrange(int(year), m)[1]
                for day in range(1, days_in_month + 1):
                    date_str = f"{year}-{str(m).zfill(2)}-{str(day).zfill(2)}"
                    invoices.extend(self.get_invoices_by_date(date_str))
            doc_id = str(year)
        else:
            invoices = self.stream_invoices()
            doc_id = "all"

        for invoice in invoices:
            cart_items = invoice.get('cartItems', [])
            for item in cart_items:
                product = item.get('product', {})
                product_id = product.get('Id')
                product_name = product.get('FullName', 'Unknown')
                price = self.safe_float(item.get('price', product.get('BasePrice', 0)))
                quantity = self.safe_int(item.get('quantity', 0))
                cost = self.safe_float(product.get('Cost', 0))
                total_profit = (price - cost) * quantity
                if product_id is not None:
                    if product_id not in product_sales:
                        product_sales[product_id] = {
                            'productId': product_id,
                            'productName': product_name,
                            'totalProfit': 0,
                            'totalQuantity': 0
                        }
                    product_sales[product_id]['totalProfit'] += total_profit
                    product_sales[product_id]['totalQuantity'] += quantity

        # Sắp xếp theo lợi nhuận giảm dần và lấy top 20
        top_products = sorted(product_sales.values(), key=lambda x: x['totalProfit'], reverse=True)[:20]

        # Lưu vào Firestore
        summary_ref = db.collection('TopProductsSummary').document(doc_id)
        summary_ref.set({
            'top_products': top_products
        })
        return top_products