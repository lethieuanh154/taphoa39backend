from dotenv import load_dotenv

from firebase.init_firebase import init_firestore

load_dotenv()

# Khởi tạo Firebase
COLLECTION_NAME = "invoices"

# Đặt tên app duy nhất cho mỗi service account
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON")
# Chuyển chuỗi JSON thành dict và tạo credential



class FirestoreInvoiceService:
    def __init__(self, cache):
        self.cache = cache
        self.invoices_ref = db.collection(COLLECTION_NAME)

    def read_all_invoices(self):
        # Kiểm tra cache
        if self.cache.has("all_invoices"):
            return self.cache.get("all_invoices")

        docs = self.invoices_ref.stream()
        result = [doc.to_dict() | {"id": doc.id} for doc in docs]
        self.cache.set("all_invoices", result, ttl=300)  # Cache 5 phút
        return result

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
        doc_ref.set(invoice)
        self.cache.invalidate("all_invoices")
        return {"message": "invoice added"}

    def update_invoice(self, invoice_id, updates):
        doc_ref = self.invoices_ref.document(invoice_id)
        doc_ref.update(updates)
        self.cache.invalidate(invoice_id)
        self.cache.invalidate("all_invoices")
        return {"message": "invoice updated"}

    def delete_invoice(self, invoice_id):
        self.invoices_ref.document(invoice_id).delete()
        self.cache.invalidate(invoice_id)
        self.cache.invalidate("all_invoices")
        return {"message": "invoice deleted"}

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

    def calculate_daily_summary(self, date):
        invoices = self.get_invoices_by_date(date)
        revenue = 0
        cost = 0
        for invoice in invoices:
            cart_items = invoice.get('cartItems', [])
            for item in cart_items:
                product = item.get('product', {})
                quantity = self.safe_int(item.get('quantity', 0))
                price = self.safe_float(item.get('price', product.get('BasePrice', 0)))
                cost_price = self.safe_float(product.get('Cost', 0))
                revenue += price * quantity
                cost += cost_price * quantity
        profit = revenue - cost
        summary_ref = db.collection('DailySummary').document(date)
        summary_ref.set({
            'buyer_quantity': len(invoices),
            'date': date,
            'revenue': revenue,
            'cost': cost,
            'profit': profit
        })
        return { 'buyer_quantity': len(invoices),'date': date, 'revenue': revenue, 'cost': cost, 'profit': profit}

    def get_daily_summary(self, date):
        return self.calculate_daily_summary(date)

    def calculate_monthly_summary(self, year, month):
        """
        Tính revenue, cost, profit cho 1 tháng, lưu vào collection MonthlySummary
        """
        from calendar import monthrange
        days_in_month = monthrange(int(year), int(month))[1]
        revenue = 0
        cost = 0
        for day in range(1, days_in_month + 1):
            date_str = f"{year}-{str(month).zfill(2)}-{str(day).zfill(2)}"
            daily = self.calculate_daily_summary(date_str)
            revenue += daily['revenue']
            cost += daily['cost']
            buyer_quantity+=daily["buyer_quantity"]
        profit = revenue - cost
        doc_id = f"{year}-{str(month).zfill(2)}"
        summary_ref = db.collection('MonthlySummary').document(doc_id)
        summary_ref.set({
            'buyer_quantity': buyer_quantity,
            'month': doc_id,
            'revenue': revenue,
            'cost': cost,
            'profit': profit
        })
        return { 'buyer_quantity': buyer_quantity,'month': doc_id, 'revenue': revenue, 'cost': cost, 'profit': profit}

    def get_monthly_summary(self, year, month):
        return self.calculate_monthly_summary(year, month)

    def calculate_yearly_summary(self, year):
        """
        Tính revenue, cost, profit cho 1 năm, lưu vào collection YearlySummary
        """
        revenue = 0
        cost = 0
        for month in range(1, 13):
            monthly = self.calculate_monthly_summary(year, month)
            revenue += monthly['revenue']
            cost += monthly['cost']
            buyer_quantity+=monthly["buyer_quantity"]
        profit = revenue - cost
        doc_id = str(year)
        summary_ref = db.collection('YearlySummary').document(doc_id)
        summary_ref.set({
            'buyer_quantity': buyer_quantity,
            'year': doc_id,
            'revenue': revenue,
            'cost': cost,
            'profit': profit
        })
        return {'buyer_quantity': buyer_quantity,'year': doc_id, 'revenue': revenue, 'cost': cost, 'profit': profit}

    def get_yearly_summary(self, year):
        return self.calculate_yearly_summary(year)
