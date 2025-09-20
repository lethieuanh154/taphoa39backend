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
        # Xóa các sản phẩm trong Firestore có isDeleted: true hoặc isActive: false
    to_delete = [
        item_id for item_id, item in firestore_items.items()
        if item['data'].get('isDeleted', False) or not item['data'].get('isActive', True)
    ]
    for item_id in to_delete:
        doc_ref = db.collection(COLLECTION_NAME).document(str(item_id))
        doc_ref.delete()
    print(f"Đã xóa {len(to_delete)} sản phẩm isDeleted:true hoặc isActive:false khỏi Firestore.")

    api_items = fetch_api_items()
    api_items = [item for item in api_items if not getattr(item, 'isDeleted', False) and getattr(item, 'isActive', True)]
    update_changed_items(api_items, firestore_items)

  
    return {"message": "All products have already been updated from kiotviet to firestore"}

def update_products_from_banhang_app_to_firestore(update_payload):
    # update_payload: list of {productId, minus}
    try:
        updated_products = []
        BATCH_SIZE = 500
        for i in range(0, len(update_payload), BATCH_SIZE):
            batch = db.batch()
            batch_items = update_payload[i:i+BATCH_SIZE]
            for item in batch_items:
                product_id = item.get("productId")
                minus = item.get("minus", 0)
                if not product_id:
                    continue
                doc_ref = db.collection(COLLECTION_NAME).document(str(product_id))
                doc = doc_ref.get()
                if doc.exists:
                    product_doc = doc.to_dict()
                    old_onhand = product_doc.get("OnHand", 0)
                    new_onhand = old_onhand - minus
                    batch.update(doc_ref, {"OnHand": new_onhand})
                    updated_products.append({
                        "Id": product_id,
                        "old_OnHand": old_onhand,
                        "new_OnHand": new_onhand
                    })
            batch.commit()
        return {
            "message": f"Đã cập nhật số lượng {len(updated_products)} sản phẩm",
            "updated_products": updated_products
        }
    except Exception as e:
        print(f"Lỗi khi cập nhật sản phẩm từ hóa đơn: {e}")
        return {"error": str(e)}

def get_products_by_master_unit_id(master_unit_id):
    # Hàm này cần implement để lấy tất cả sản phẩm có cùng MasterUnitId
    # Từ Firestore collection
    products = []
    docs = db.collection(COLLECTION_NAME).where("MasterUnitId", "==", master_unit_id).stream()
    for doc in docs:
        product_data = doc.to_dict()
        product_data["Id"] = doc.id
        products.append(product_data)
    return products

def sync_products_if_firestore_empty():
    products_ref = db.collection(COLLECTION_NAME)
    docs = list(products_ref.stream())
    if len(docs) == 0:
        print("Firestore chưa có dữ liệu, đang tải toàn bộ sản phẩm từ API...")
        api_items = fetch_api_items()
        BATCH_SIZE = 500
        for i in range(0, len(api_items), BATCH_SIZE):
            batch = db.batch()
            for item in api_items[i:i+BATCH_SIZE]:
                doc_ref = db.collection(COLLECTION_NAME).document(str(item.Id))
                batch.set(doc_ref, item.__dict__)
            batch.commit()
        print(f"Đã lưu {len(api_items)} sản phẩm vào Firestore.")
    else:
        print(f"Firestore đã có {len(docs)} sản phẩm, không cần tải lại.")

