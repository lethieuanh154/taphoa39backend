import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv
import json
import requests
from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer
import hashlib
from firebase.firebase_hanghoa.product_class import Product
from dateutil.parser import parse as parse_date

load_dotenv()

# Khởi tạo Firebase
API_URL = f"https://api-kvsync1.kiotviet.vn/api/resource/fetch?clientId=WebAppWN-3e31c9b0-cd4a-43e6-be25-a5d1330372fd-500111210-878979&resourceName=Products&pageSize=20000"
API_HEADERS = {
    "Authorization": auth_token,
    "retailer": retailer,
    "branchid": LatestBranchId
}
COLLECTION_NAME = "products"
service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_HANGHOA")
if not service_account_json:
    raise Exception("Missing FIREBASE_SERVICE_ACCOUNT_HANGHOA environment variable.")

# Chuyển chuỗi JSON thành dict và tạo credential
cred_dict = json.loads(service_account_json)

cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)

db = firestore.client()
COLLECTION_NAME = "products"

class FirestoreProductService:
    def __init__(self, cache):
        self.cache = cache
        self.products_ref = db.collection(COLLECTION_NAME)

    def read_all_products(self):
        # Kiểm tra cache
        if self.cache.has("all_products"):
            return self.cache.get("all_products")

        docs = self.products_ref.stream()
        result = [
            doc.to_dict() | {"id": doc.id}
            for doc in docs
            if not doc.to_dict().get("isDeleted", False) and doc.to_dict().get("isActive", True)
        ]
        self.cache.set("all_products", result, ttl=300)  # Cache 5 phút
        return result

    def read_product(self, product_id):
        if self.cache.has(product_id):
            return self.cache.get(product_id)

        doc = self.products_ref.document(product_id).get()
        if doc.exists:
            product = doc.to_dict()
            self.cache.set(product_id, product, ttl=300)
            return product
        return None

    def add_product(self, product):
        doc_ref = self.products_ref.document(str(product["Id"]))
        doc_ref.set(product)
        self.cache.invalidate("all_products")
        return {"message": "Product added"}

    def update_product(self, product_id, updates):
        doc_ref = self.products_ref.document(product_id)
        doc_ref.update(updates)
        self.cache.invalidate(product_id)
        self.cache.invalidate("all_products")
        return {"message": "Product updated"}
    
    def update_products(self, products_dict):
        updated = []
        # Gộp tất cả sản phẩm từ các group lại thành 1 list
        all_products = []
        for group in products_dict.values():
            if isinstance(group, list):
                all_products.extend(group)
        for prod in all_products:
            if not isinstance(prod, dict):
                continue
            product_id = str(prod.get("Id") or prod.get("id"))
            if not product_id:
                continue
            doc_ref = self.products_ref.document(product_id)
            doc_ref.set(prod, merge=True)
            updated.append(product_id)
            self.cache.invalidate(product_id)
        self.cache.invalidate("all_products")
        return {"message": f"Updated {len(updated)} products", "updated": updated}


    def delete_product(self, product_id):
        self.products_ref.document(product_id).delete()
        self.cache.invalidate(product_id)
        self.cache.invalidate("all_products")
        return {"message": "Product deleted"}
    
    def group_product(self):
        """
        Group products by Master Item (MasterUnitId=None) and their Child Items (MasterUnitId=Id of Master Item).
        Returns a dict: {master_id: {"master": master_product, "children": [child_products]}}
        """
        all_products = self.read_all_products()
        masters = {}
        children = []
        # Phân loại master và child
        for prod in all_products:
            if prod.get("MasterUnitId") is None:
                masters[str(prod.get("Id") or prod.get("id"))] = {"master": prod, "children": []}
            else:
                children.append(prod)
        # Gán child vào master tương ứng
        for child in children:
            master_id = str(child.get("MasterUnitId"))
            if master_id in masters:
                masters[master_id]["children"].append(child)
        return masters
    
    def update_products_from_kiotviet_to_firestore(self):
        """Backwards-compatible wrapper for legacy callers."""
        return self.sync_products_from_kiotviet()

    def sync_products_from_kiotviet(self):
        try:
            print("Bắt đầu đồng bộ sản phẩm từ KiotViet (tối ưu)...")
            existing_checksums = {}
            existing_ids = set()
            # Lấy tối thiểu dữ liệu từ Firestore (chỉ checksum) để giảm tải bộ nhớ.
            for doc in self.products_ref.select(["SyncChecksum"]).stream():
                data = doc.to_dict() or {}
                existing_checksums[doc.id] = data.get("SyncChecksum")
                existing_ids.add(doc.id)

            api_items = self.fetch_api_items()

            to_upsert = []
            seen_ids = set()

            for item in api_items:
                product_dict = item.__dict__ if hasattr(item, "__dict__") else dict(item)
                doc_id = str(product_dict.get("Id"))
                if not doc_id:
                    continue
                seen_ids.add(doc_id)

                checksum = self.hash_item(product_dict)
                if existing_checksums.get(doc_id) == checksum:
                    continue

                # Gắn checksum để lần sau so sánh nhanh.
                product_to_store = dict(product_dict)
                product_to_store["SyncChecksum"] = checksum
                to_upsert.append((doc_id, product_to_store))

            to_delete = [doc_id for doc_id in existing_ids if doc_id not in seen_ids]

            # Thực thi batch để hạn chế số round-trip
            BATCH_SIZE = 500
            for i in range(0, len(to_upsert), BATCH_SIZE):
                batch = db.batch()
                for doc_id, payload in to_upsert[i : i + BATCH_SIZE]:
                    doc_ref = self.products_ref.document(doc_id)
                    batch.set(doc_ref, payload)
                batch.commit()

            for i in range(0, len(to_delete), BATCH_SIZE):
                batch = db.batch()
                for doc_id in to_delete[i : i + BATCH_SIZE]:
                    doc_ref = self.products_ref.document(doc_id)
                    batch.delete(doc_ref)
                batch.commit()

            self.cache.invalidate("all_products")
            for doc_id, _ in to_upsert:
                self.cache.invalidate(doc_id)
            for doc_id in to_delete:
                self.cache.invalidate(doc_id)

            print(
                f"Đồng bộ hoàn tất: cập nhật/thêm {len(to_upsert)} sản phẩm, xóa {len(to_delete)} sản phẩm."
            )
            return {
                "message": "Đã đồng bộ sản phẩm",
                "updated_or_created": len(to_upsert),
                "deleted": len(to_delete),
                "total_api_items": len(api_items),
            }
        except Exception as exc:
            print("Lỗi khi đồng bộ sản phẩm từ KiotViet:", exc)
            import traceback
            print(traceback.format_exc())
            return {"message": "sync_failed", "error": str(exc)}

    def fetch_firestore_items(self):
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
                    'hash': self.hash_item(data)
                }
        print(f"Đã tải {len(firestore_items)} sản phẩm từ Firestore.")
        return firestore_items

    def fetch_api_items(self):
        print("Đang gọi API /api/all...")
        response = requests.get(API_URL, headers=API_HEADERS, timeout=30)
        response.raise_for_status()
        items = response.json().get("Data", [])
        print(f"Đã nhận {len(items)} sản phẩm từ API.")
        products = [Product.from_dict(item) for item in items]
        return products
    
    def update_changed_items(self,api_items, firestore_items):
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
           new_hash = self.hash_item(item_dict)
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

    def hash_item(self, item):
        def default_serializer(obj):
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
        item_copy = dict(item)
        item_copy.pop("SyncChecksum", None)
        return hashlib.md5(json.dumps(item_copy, sort_keys=True, default=default_serializer).encode()).hexdigest()

def is_newer(api_mod, fs_mod):
    try:
        if not api_mod:
            return False
        if not fs_mod:
            return True
        return parse_date(api_mod) > parse_date(fs_mod)
    except Exception:
        return False
