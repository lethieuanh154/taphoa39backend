from firebase.init_firebase import init_firestore

COLLECTION_NAME = "customers"

db = init_firestore("FIREBASE_SERVICE_ACCOUNT_CUSTOMER")
customers_ref = db.collection(COLLECTION_NAME)

class FirestoreCustomerService:
    def __init__(self, cache):
        self.cache = cache
        self.customers_ref = customers_ref

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
    
    def read_all_customers(self):
    # Nếu có cache thì dùng, không thì lấy từ Firestore
        if self.cache.has("all_customers"):
            return self.cache.get("all_customers")
        docs = self.customers_ref.stream()
        result = [doc.to_dict() | {"id": doc.id} for doc in docs]
        self.cache.set("all_customers", result, ttl=300)  # Cache 5 phút
        return result