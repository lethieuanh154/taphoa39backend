from dotenv import load_dotenv
from firebase.init_firebase import init_firestore

load_dotenv()

COLLECTION_NAME = "invoices"

# Đặt tên app duy nhất cho mỗi service account
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON")

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

db2 = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON2")
def migrate_collection_between_projects(source_account_env, target_account_env, collection_name=COLLECTION_NAME):
    try:
        source_db = init_firestore(source_account_env)
        target_db = init_firestore(target_account_env)
    except Exception as exc:
        return {"error": str(exc)}

    source_ref = source_db.collection(collection_name)
    target_ref = target_db.collection(collection_name)

    try:
        documents = list(source_ref.stream())
    except Exception as exc:
        return {"error": f"Không đọc được dữ liệu từ nguồn: {exc}"}

    batch = target_db.batch()
    batch_size = 0
    total_copied = 0

    for snapshot in documents:
        data = snapshot.to_dict() or {}
        doc_ref = target_ref.document(snapshot.id)
        batch.set(doc_ref, data)
        batch_size += 1
        total_copied += 1
        if batch_size == 500:
            batch.commit()
            batch = target_db.batch()
            batch_size = 0

    if batch_size:
        batch.commit()

    return {
        "collection": collection_name,
        "copied": total_copied,
        "source_account": source_account_env,
        "target_account": target_account_env,
    }
# migrate_collection_between_projects("FIREBASE_SERVICE_ACCOUNT_HOADON", "FIREBASE_SERVICE_ACCOUNT_HOADON2")