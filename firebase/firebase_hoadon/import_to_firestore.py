import json
from firebase_admin import credentials, firestore
import hashlib
from dotenv import load_dotenv
from firebase.init_firebase import init_firestore

load_dotenv()

COLLECTION_NAME = "invoices"

# Đặt tên app duy nhất cho mỗi service account
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON")

def hash_item(item):
    item_copy = dict(item)
    return hashlib.md5(json.dumps(item_copy, sort_keys=True).encode()).hexdigest()

def fetch_firestore_items():
    print("Đang tải dữ liệu từ Firestore...")
    invoices_ref = db.collection(COLLECTION_NAME)
    docs = invoices_ref.stream()
    firestore_items = {}
    for doc in docs:
        data = doc.to_dict()
        item_id = data.get('Id')
        if item_id:
            firestore_items[item_id] = {
                'data': data,
                'hash': hash_item(data)
            }
    print(f"Đã tải {len(firestore_items)} hóa đơn từ Firestore.")
    return firestore_items

def update_invoices_from_banhang_app_to_firestore(invoice_obj):
    # invoice_obj là 1 dict, ví dụ: {"id":1, "name":"Hóa đơn 1", "cartItems":[...]}
    item_id = invoice_obj.get('id')
    if not item_id:
        return {"error": "Thiếu trường id trong hóa đơn."}
    try:
        doc_ref = db.collection(COLLECTION_NAME).document(str(item_id))
        doc_ref.set(invoice_obj)
        print(f"Đã lưu hóa đơn {item_id} lên Firestore.")
        return {"message": f"Đã lưu hóa đơn {item_id} lên Firestore"}
    except Exception as e:
        print(f"Lỗi khi lưu hóa đơn: {e}")
        return {"error": str(e)}