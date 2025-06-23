from dotenv import load_dotenv

from firebase.init_firebase import init_firestore

load_dotenv()

# Khởi tạo Firebase
COLLECTION_NAME = "invoices"

# Đặt tên app duy nhất cho mỗi service account
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON")
invoices_ref = db.collection(COLLECTION_NAME)
# Chuyển chuỗi JSON thành dict và tạo credential



class FirestoreInvoiceservice:
    def __init__(self, cache):
        self.cache = cache
        self.invoices_ref = db.collection("invoices")

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

    def add_invoice(self, invoice):
        doc_ref = self.invoices_ref.document(str(invoice["Id"]))
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
