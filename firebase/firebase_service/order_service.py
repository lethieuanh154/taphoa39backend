from dotenv import load_dotenv

from firebase.init_firebase import init_firestore

load_dotenv()

# Khởi tạo Firebase
COLLECTION_NAME = "orders"

# Đặt tên app duy nhất cho mỗi service account
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON")
# Chuyển chuỗi JSON thành dict và tạo credential



class FirestoreorderService:
    def __init__(self, cache):
        self.cache = cache
        self.orders_ref = db.collection(COLLECTION_NAME)

    def read_all_orders(self):
        # Kiểm tra cache
        if self.cache.has("all_orders"):
            return self.cache.get("all_orders")

        docs = self.orders_ref.stream()
        result = [doc.to_dict() | {"id": doc.id} for doc in docs]
        self.cache.set("all_orders", result, ttl=300)  # Cache 5 phút
        return result

    def read_order(self, order_id):
        if self.cache.has(order_id):
            return self.cache.get(order_id)

        doc = self.orders_ref.document(order_id).get()
        if doc.exists:
            order = doc.to_dict()
            self.cache.set(order_id, order, ttl=300)
            return order
        return None

    def get_orders_by_date(self, date):
        """
        Get orders for a specific date (full day)
        Expected date format: YYYY-MM-DD (e.g., "2025-06-17")
        """
        try:
            # Create string for comparison in ISO format for start and end of day
            start_str = f"{date}T00:00:00.000Z"
            end_str = f"{date}T23:59:59.999Z"

            # Query Firestore with string
            query = self.orders_ref \
                .where('createdDate', '>=', start_str) \
                .where('createdDate', '<=', end_str)
            orders = query.stream()
            return [order.to_dict() for order in orders]
        except Exception as e:
            raise Exception(f"Error getting orders by date: {str(e)}")

    def get_orders_by_status(self, status: str):
        """
        Get orders by status
        """
        try:
            query = self.orders_ref.where('status', '==', status)
            orders = query.stream()
            return [order.to_dict() for order in orders]
        except Exception as e:
            raise Exception(f"Error getting orders by status: {str(e)}")

    def get_orders_by_customer(self, customer_id: str):
        """
        Get orders by customer ID
        """
        try:
            # Assuming customerId is stored in 'customerId' field
            query = self.orders_ref.where('customerId', '==', customer_id)
            orders = query.stream()
            return [order.to_dict() for order in orders]
        except Exception as e:
            raise Exception(f"Error getting orders by customer: {str(e)}")

    def add_order(self, order):
        doc_ref = self.orders_ref.document(str(order["id"]))
        doc_ref.set(order)
        self.cache.invalidate("all_orders")
        return {"message": "order added"}

    def update_order(self, order_id, updates):
        doc_ref = self.orders_ref.document(order_id)
        doc_ref.update(updates)
        self.cache.invalidate(order_id)
        self.cache.invalidate("all_orders")
        return {"message": "order updated"}

    def delete_order(self, order_id):
        self.orders_ref.document(order_id).delete()
        self.cache.invalidate(order_id)
        self.cache.invalidate("all_orders")
        return {"message": "order deleted"}

    