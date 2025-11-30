from dotenv import load_dotenv
from firebase.init_firebase import init_firestore
from google.cloud import firestore

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

        # We'll persist processed event markers when an event/invoice id is provided
        processed_collection = db.collection("product_updates_processed")

        @firestore.transactional
        def _process_single(transaction, doc_ref, proc_ref, item):
            # Use doc_ref.get() with transaction parameter (correct Firestore Python SDK usage)
            doc = doc_ref.get(transaction=transaction)
            if not doc.exists:
                return None
            product_doc = doc.to_dict() or {}
            current_onhand = product_doc.get("OnHand", 0) or 0

            # Determine explicit target if provided
            target_onhand = None
            for key in ("OnHand", "onHand", "onhand"):
                if key in item:
                    target_onhand = _parse_int(item.get(key))
                    break

            minus_value = _parse_int(item.get("minus", 0)) or 0

            # If proc_ref (event marker) exists, skip to make it idempotent
            if proc_ref is not None:
                proc_doc = proc_ref.get(transaction=transaction)
                if proc_doc.exists:
                    # Already applied
                    return {
                        "Id": str(item.get("productId") or item.get("Id") or item.get("id")),
                        "skipped": True,
                    }

            if target_onhand is None:
                # Compute target using current_onhand inside transaction for atomicity
                target_onhand = int(current_onhand) - int(minus_value)

            # Update product OnHand
            transaction.update(doc_ref, {"OnHand": target_onhand})

            # Create processed marker if available — use transaction.set
            if proc_ref is not None:
                try:
                    transaction.set(proc_ref, {"applied": True, "productId": str(item.get("productId") or item.get("Id") or item.get("id")), "minus": minus_value})
                except Exception:
                    # best-effort: ignore set errors inside transaction wrapper
                    pass

            return {
                "Id": str(item.get("productId") or item.get("Id") or item.get("id")),
                "old_OnHand": current_onhand,
                "new_OnHand": target_onhand,
            }

        for item in update_payload:
            product_id = item.get("productId") or item.get("Id") or item.get("id")
            if not product_id:
                continue

            doc_ref = db.collection(COLLECTION_NAME).document(str(product_id))

            # Use event id (invoiceId, eventId) to create idempotent marker when available
            event_id = item.get("eventId") or item.get("invoiceId") or item.get("billId") or item.get("receiptId")
            proc_ref = None
            if event_id:
                proc_ref = processed_collection.document(f"{str(event_id)}_{str(product_id)}")

            try:
                # Create a transaction and pass it to the decorated function
                transaction = db.transaction()
                result = _process_single(transaction, doc_ref, proc_ref, item)
                if result:
                    # result may be dict or None
                    if isinstance(result, dict) and not result.get("skipped"):
                        updated_products.append(result)
            except Exception as exc:
                # Best-effort logging; continue with next item
                print(f"Error processing product {product_id}: {exc}")

        return {
            "message": f"Đã cập nhật số lượng {len(updated_products)} sản phẩm",
            "updated_products": updated_products,
        }
    except Exception as e:
        print(f"Lỗi khi cập nhật sản phẩm từ hóa đơn: {e}")
        return {"error": str(e)}
    