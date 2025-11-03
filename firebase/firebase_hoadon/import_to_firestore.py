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