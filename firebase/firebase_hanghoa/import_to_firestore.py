from dotenv import load_dotenv
from firebase.init_firebase import init_firestore
from google.cloud import firestore
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

COLLECTION_NAME = "products"

# service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PRODUCT")
# if not service_account_json:
#     raise Exception("Missing FIREBASE_SERVICE_ACCOUNT_PRODUCT environment variable.")

# # Chuyển chuỗi JSON thành dict và tạo credential
# cred_dict = json.loads(service_account_json)

# # # Khởi tạo kết nối Firebase Admin
# cred = credentials.Certificate(cred_dict)
# firebase_admin.initialize_app(cred)
# db = firestore.client()
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_PRODUCT")

def _parse_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_number(value):
    """Parse value as float, preserving decimals for OnHandNV."""
    try:
        return float(value)
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

            # Determine the product type using expanded clone detection
            # matching the frontend's logic for consistency
            is_clone_product = False
            if product_doc.get("isClone") is True or product_doc.get("isClone") == "true":
                is_clone_product = True
            # Fallback: product có OnHandNV > 0 và OnHand === 0 là clone
            elif (product_doc.get("OnHandNV") or 0) > 0 and (product_doc.get("OnHand") or 0) == 0:
                is_clone_product = True
            # Fallback: KiotVietSync === false là local product, dùng OnHandNV
            elif product_doc.get("KiotVietSync") is False:
                is_clone_product = True

            # Get the requested update type from the client, default to OnHand
            requested_update_type = item.get("updateType", "OnHand")

            # Trust the client's updateType if it says OnHandNV — the frontend has
            # additional context (cart item snapshot with OnHandNV/OnHand values at
            # checkout time) that the backend cannot see from the current Firestore doc
            # (e.g. after a full deduction, OnHandNV may be 0 in Firestore but the
            # frontend knows it was originally an NV product).
            if is_clone_product:
                update_type = "OnHandNV"
            elif requested_update_type == "OnHandNV":
                # Frontend explicitly requested OnHandNV — trust it
                update_type = "OnHandNV"
            else:
                update_type = "OnHand"

            is_nv_update = update_type == "OnHandNV"

            # Log if we corrected the client's request
            if requested_update_type != update_type:
                print(f"   sanitized: Corrected update type from '{requested_update_type}' to '{update_type}' for product {doc.id} (isClone={is_clone_product})")

            # Lấy giá trị current tương ứng
            if is_nv_update:
                current_value = product_doc.get("OnHandNV", 0) or 0
            else:
                current_value = product_doc.get("OnHand", 0) or 0

            # For OnHandNV (clone products): use float to preserve decimals (e.g. 20.08333)
            # For OnHand (KiotViet products): use int (KiotViet always uses integers)
            if is_nv_update:
                minus_value = _parse_number(item.get("minus", 0)) or 0
                plus_value = _parse_number(item.get("plus", 0)) or 0
            else:
                minus_value = _parse_int(item.get("minus", 0)) or 0
                plus_value = _parse_int(item.get("plus", 0)) or 0

            # If proc_ref (event marker) exists, skip to make it idempotent
            if proc_ref is not None:
                proc_doc = proc_ref.get(transaction=transaction)
                if proc_doc.exists:
                    # Already applied
                    return {
                        "Id": str(item.get("productId") or item.get("Id") or item.get("id")),
                        "skipped": True,
                        "updateType": update_type,
                    }

            # ✅ Always compute target using current value inside the transaction for atomicity.
            # This ignores any target value sent from the client, making the backend authoritative.
            # ✅ FIX: Handle both minus (decrease) and plus (increase) for edit invoice restore
            if is_nv_update:
                # OnHandNV: preserve decimals, round to 1 decimal place
                target_value = round(float(current_value) - float(minus_value) + float(plus_value), 1)
            else:
                # OnHand: preserve decimals for child units (e.g. "10 lon" = 1.4)
                target_value = round(float(current_value) - float(minus_value) + float(plus_value), 1)

            # ✅ Update product OnHand hoặc OnHandNV tùy theo loại
            # Cập nhật SyncTimestamp và ModifiedDate để:
            # - realtime listener có thể bắt được thay đổi (SyncTimestamp)
            # - Quick Sync (modified-since) có thể tìm thấy products đã thay đổi (ModifiedDate)
            sync_timestamp = datetime.utcnow().isoformat()
            if is_nv_update:
                transaction.update(doc_ref, {"OnHandNV": target_value, "SyncTimestamp": sync_timestamp, "ModifiedDate": sync_timestamp})
            else:
                transaction.update(doc_ref, {"OnHand": target_value, "SyncTimestamp": sync_timestamp, "ModifiedDate": sync_timestamp})

            # Create processed marker if available — use transaction.set
            if proc_ref is not None:
                try:
                    transaction.set(proc_ref, {
                        "applied": True,
                        "productId": str(item.get("productId") or item.get("Id") or item.get("id")),
                        "minus": minus_value,
                        "updateType": update_type
                    })
                except Exception:
                    # best-effort: ignore set errors inside transaction wrapper
                    pass

            return {
                "Id": str(item.get("productId") or item.get("Id") or item.get("id")),
                "old_OnHand": current_value,
                "new_OnHand": target_value,
                "updateType": update_type,
            }

        def _process_item(item):
            product_id = item.get("productId") or item.get("Id") or item.get("id")
            if not product_id:
                return None

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
                if result and isinstance(result, dict) and not result.get("skipped"):
                    return result
            except Exception as exc:
                print(f"Error processing product {product_id}: {exc}")
            return None

        # Run all product transactions in parallel
        with ThreadPoolExecutor(max_workers=min(len(update_payload), 20)) as executor:
            futures = [executor.submit(_process_item, item) for item in update_payload]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    updated_products.append(result)

        return {
            "message": f"Đã cập nhật số lượng {len(updated_products)} sản phẩm",
            "updated_products": updated_products,
        }
    except Exception as e:
        print(f"Lỗi khi cập nhật sản phẩm từ hóa đơn: {e}")
        return {"error": str(e)}
    