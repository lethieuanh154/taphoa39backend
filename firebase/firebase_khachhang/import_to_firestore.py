import json
import firebase_admin
import requests
from firebase_admin import credentials, firestore
from FromKiotViet.get_all_customer import get_entire_customer
from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer
import requests
import hashlib
import os
from dotenv import load_dotenv

from firebase.init_firebase import init_firestore

load_dotenv()

# API_URL = f"http://127.0.0.1:5000/api/customers"

COLLECTION_NAME = "customers"


db = init_firestore("FIREBASE_SERVICE_ACCOUNT_CUSTOMER")


# Hàm băm item để so sánh nhanh
def hash_item(item):
    # Đảm bảo thứ tự khóa và bỏ qua các trường không cần so sánh
    item_copy = dict(item)
    return hashlib.md5(json.dumps(item_copy, sort_keys=True).encode()).hexdigest()


def fetch_firestore_customers():
    print("Đang tải dữ liệu từ Firestore...")
    customers_ref = db.collection(COLLECTION_NAME)
    docs = customers_ref.stream()
    firestore_items = {}
    for doc in docs:
        data = doc.to_dict()
        item_id = data.get('Id')
        if item_id:
            firestore_items[item_id] = {
                'data': data,
                'hash': hash_item(data)
            }
    print(f"Đã tải {len(firestore_items)} khách hàng từ Firestore.")
    return firestore_items


def fetch_api_customers():
    print("Đang gọi API /api/customers...")
    items=get_entire_customer()
    # response = requests.get(API_URL)  # Sửa lại URL phù hợp
    # response.raise_for_status()
    # items = response.json()
    print(f"Đã nhận {len(items)} khách hàng từ API.")
    return items


def update_changed_customer(api_items, firestore_items):
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

    print(f"Phát hiện {len(changed_items)} khách hàng thay đổi. Đang cập nhật...")
    print(f"Phát hiện {len(deleted_items)} khách hàng cần xóa khỏi Firestore.")

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


def update_customer_from_kiotviet_to_firestore():
    firestore_customers = fetch_firestore_customers()
    api_customers = fetch_api_customers()
    update_changed_customer(api_customers, firestore_customers)
    return {"message": "All customers have already been updated from kiotviet to firestore"}

# update_customer_from_kiotviet_to_firestore()

