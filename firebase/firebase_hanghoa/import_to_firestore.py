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

# Hàm băm item để so sánh nhanh
def hash_item(item):
    # Đảm bảo thứ tự khóa và bỏ qua các trường không cần so sánh
    item_copy = dict(item)
    return hashlib.md5(json.dumps(item_copy, sort_keys=True).encode()).hexdigest()


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
        item_id = item.get('Id')
        if not item_id:
            continue

        if item.get('isDeleted', False):
            deleted_items.append(item_id)
            continue

        new_hash = hash_item(item)
        old_hash = firestore_items.get(item_id, {}).get('hash')

        if new_hash != old_hash:
            changed_items.append(item)

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


