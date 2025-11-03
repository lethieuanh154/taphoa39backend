from dotenv import load_dotenv
from firebase.init_firebase import init_firestore

load_dotenv()

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
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HANGHOA")

def _parse_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def update_products_from_banhang_app_to_firestore(update_payload):
    try:
        if not isinstance(update_payload, list):
            return {"error": "Payload must be a list of products"}

        updated_products = []
        BATCH_SIZE = 500
        for i in range(0, len(update_payload), BATCH_SIZE):
            batch = db.batch()
            batch_items = update_payload[i:i+BATCH_SIZE]
            for item in batch_items:
                product_id = item.get("productId") or item.get("Id") or item.get("id")
                if not product_id:
                    continue
                doc_ref = db.collection(COLLECTION_NAME).document(str(product_id))
                doc = doc_ref.get()
                if doc.exists:
                    product_doc = doc.to_dict()
                    old_onhand = product_doc.get("OnHand", 0)
                    target_onhand = None

                    for key in ("OnHand", "onHand", "onhand"):
                        if key in item:
                            target_onhand = _parse_int(item.get(key))
                            break

                    if target_onhand is None:
                        minus_value = _parse_int(item.get("minus", 0)) or 0
                        target_onhand = old_onhand - minus_value

                    if target_onhand is None:
                        continue

                    batch.update(doc_ref, {"OnHand": target_onhand})
                    updated_products.append({
                        "Id": str(product_id),
                        "old_OnHand": old_onhand,
                        "new_OnHand": target_onhand
                    })
            batch.commit()
        return {
            "message": f"Đã cập nhật số lượng {len(updated_products)} sản phẩm",
            "updated_products": updated_products
        }
    except Exception as e:
        print(f"Lỗi khi cập nhật sản phẩm từ hóa đơn: {e}")
        return {"error": str(e)}
    