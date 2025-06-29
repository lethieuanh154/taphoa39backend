import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv
import json

load_dotenv()

# Khởi tạo Firebase

service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_HANGHOA")
if not service_account_json:
    raise Exception("Missing FIREBASE_SERVICE_ACCOUNT_HANGHOA environment variable.")

# Chuyển chuỗi JSON thành dict và tạo credential
cred_dict = json.loads(service_account_json)

cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)

db = firestore.client()


class FirestoreProductService:
    def __init__(self, cache):
        self.cache = cache
        self.products_ref = db.collection("products")

    def read_all_products(self):
        # Kiểm tra cache
        if self.cache.has("all_products"):
            return self.cache.get("all_products")

        docs = self.products_ref.stream()
        result = [
            doc.to_dict() | {"id": doc.id}
            for doc in docs
            if not doc.to_dict().get("isDeleted", False) and doc.to_dict().get("isActive", True)
        ]
        self.cache.set("all_products", result, ttl=300)  # Cache 5 phút
        return result

    def read_product(self, product_id):
        if self.cache.has(product_id):
            return self.cache.get(product_id)

        doc = self.products_ref.document(product_id).get()
        if doc.exists:
            product = doc.to_dict()
            self.cache.set(product_id, product, ttl=300)
            return product
        return None

    def add_product(self, product):
        doc_ref = self.products_ref.document(str(product["Id"]))
        doc_ref.set(product)
        self.cache.invalidate("all_products")
        return {"message": "Product added"}

    def update_product(self, product_id, updates):
        doc_ref = self.products_ref.document(product_id)
        doc_ref.update(updates)
        self.cache.invalidate(product_id)
        self.cache.invalidate("all_products")
        return {"message": "Product updated"}

    def delete_product(self, product_id):
        self.products_ref.document(product_id).delete()
        self.cache.invalidate(product_id)
        self.cache.invalidate("all_products")
        return {"message": "Product deleted"}
