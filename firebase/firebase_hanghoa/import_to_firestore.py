import json
import firebase_admin
import requests
from firebase_admin import credentials, firestore
from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer
import requests
import hashlib
import os
from dotenv import load_dotenv
from firebase.firebase_hanghoa.product_class import Product
from firebase.init_firebase import init_firestore

load_dotenv()

API_URL = f"https://api-kvsync1.kiotviet.vn/api/resource/fetch?clientId=WebAppWN-3e31c9b0-cd4a-43e6-be25-a5d1330372fd-500111210-878979&resourceName=Products&pageSize=20000"
API_HEADERS = {
    "Authorization": auth_token,
    "retailer": retailer,
    "branchid": LatestBranchId
}
COLLECTION_NAME = "products"

# service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_HANGHOA")
# if not service_account_json:
#     raise Exception("Missing FIREBASE_SERVICE_ACCOUNT_HANGHOA environment variable.")

# # Chuyển chuỗi JSON thành dict và tạo credential
# cred_dict = json.loads(service_account_json)

# # # Khởi tạo kết nối Firebase Admin
# cred = credentials.Certificate(cred_dict)
# firebase_admin.initialize_app(cred)
# db = firestore.client()
db= init_firestore("FIREBASE_SERVICE_ACCOUNT_HANGHOA")

def hash_item(item):
    def default_serializer(obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
    item_copy = dict(item)
    return hashlib.md5(json.dumps(item_copy, sort_keys=True, default=default_serializer).encode()).hexdigest()


def fetch_firestore_items():
    print("Đang tải dữ liệu từ Firestore...")
    products_ref = db.collection(COLLECTION_NAME)
    docs = products_ref.stream()
    firestore_items = {}
    for doc in docs:
        data = doc.to_dict()
        item_id = data.get('Id')
        if item_id:
            firestore_items[item_id] = {
                'data': data,
                'hash': hash_item(data)
            }
    print(f"Đã tải {len(firestore_items)} sản phẩm từ Firestore.")
    return firestore_items


def fetch_api_items():
    print("Đang gọi API /api/all...")
    response = requests.get(API_URL, headers=API_HEADERS)  # Sửa lại URL phù hợp
    response.raise_for_status()
    items = response.json().get("Data", [])
    print(f"Đã nhận {len(items)} sản phẩm từ API.")
    products = [Product.from_dict(item) for item in items]
    return products


def update_changed_items(api_items, firestore_items):
    changed_items = []
    deleted_items = []

    for item in api_items:
        item_id = item.Id
        if not item_id:
            continue

        if getattr(item, 'isDeleted', False):
            deleted_items.append(item_id)
            continue

        # Convert Product object to dict for hashing and saving
        item_dict = item.__dict__
        new_hash = hash_item(item_dict)
        old_hash = firestore_items.get(item_id, {}).get('hash')

        if new_hash != old_hash:
            changed_items.append(item_dict)

    print(f"Phát hiện {len(changed_items)} sản phẩm thay đổi. Đang cập nhật...")
    print(f"Phát hiện {len(deleted_items)} sản phẩm cần xóa khỏi Firestore.")

    # Ghi theo batch (500 item mỗi batch)
    BATCH_SIZE = 500
    for i in range(0, len(changed_items), BATCH_SIZE):
        batch = db.batch()
        for item in changed_items[i:i + BATCH_SIZE]:
            doc_ref = db.collection(COLLECTION_NAME).document(str(item['Id']))
            batch.set(doc_ref, item)
        batch.commit()
        print(f"Đã cập nhật batch {i // BATCH_SIZE + 1}")

    # Xóa theo batch (500 item mỗi batch)
    for i in range(0, len(deleted_items), BATCH_SIZE):
        batch = db.batch()
        for item_id in deleted_items[i:i + BATCH_SIZE]:
            doc_ref = db.collection(COLLECTION_NAME).document(str(item_id))
            batch.delete(doc_ref)
        batch.commit()
        print(f"Đã xóa batch {i // BATCH_SIZE + 1}")

    print("Đã hoàn tất cập nhật và xóa.")


def update_products_from_kiotviet_to_firestore():
    firestore_items = fetch_firestore_items()
    api_items = fetch_api_items()
    update_changed_items(api_items, firestore_items)
    return {"message": "All products have already been updated from kiotviet to firestore"}

def update_products_from_banhang_app_to_firestore(invoice_obj):
    # invoice_obj: {"id":1, "name":"Hóa đơn 1", "cartItems":[{product, quantity, ...}, ...]}
    try:
        cart_items = invoice_obj.get("cartItems", [])
        updated_products = []
        for item in cart_items:
            product_data = item.get("product")
            quantity = item.get("quantity", 0)
            if not product_data or "Id" not in product_data:
                continue
            product_id = product_data["Id"]
            doc_ref = db.collection(COLLECTION_NAME).document(str(product_id))
            doc = doc_ref.get()
            if doc.exists:
                product_doc = doc.to_dict()
                print(product_doc)
                # Trừ số lượng OnHand
                old_onhand = product_doc.get("OnHand", 0)
                new_onhand = old_onhand - quantity
                doc_ref.update({"OnHand": new_onhand})
                updated_products.append({"Id": product_id, "old_OnHand": old_onhand, "new_OnHand": new_onhand})
            else:
                # Nếu sản phẩm chưa có trên Firestore, có thể tạo mới hoặc bỏ qua
                continue
        return {
            "message": f"Đã cập nhật số lượng {len(updated_products)} sản phẩm từ hóa đơn {invoice_obj.get('id')}",
            "updated_products": updated_products
        }
    except Exception as e:
        print(f"Lỗi khi cập nhật sản phẩm từ hóa đơn: {e}")
        return {"error": str(e)}