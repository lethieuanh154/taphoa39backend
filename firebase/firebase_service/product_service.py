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
from typing import Any, List, Optional, Set

load_dotenv()

# Khởi tạo Firebase
API_BASE_URL = "https://api-kvsync1.kiotviet.vn/api/resource/fetch"
API_CLIENT_ID = "WebAppWN-3e31c9b0-cd4a-43e6-be25-a5d1330372fd-500111210-878979"
API_RESOURCE = "Products"
API_PAGE_SIZE = 500
API_SINGLE_FETCH_LIMIT = 20000
API_HEADERS = {
    "Authorization": auth_token,
    "retailer": retailer,
    "branchid": LatestBranchId,
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

    @staticmethod
    def _coerce_bool(value, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
        return default

    @classmethod
    def _should_store_product(cls, record: Any) -> bool:
        if record is None:
            return False
        if hasattr(record, "__dict__"):
            record = record.__dict__
        if not isinstance(record, dict):
            return False
        # is_active = cls._coerce_bool(record.get("isActive"), True)
        is_deleted = cls._coerce_bool(record.get("isDeleted"), False)
        return not is_deleted

    def read_all_products(self, include_inactive: bool = False, include_deleted: bool = False):
        """Read products from Firestore.

        By default, only active and not-deleted products are returned (backwards-compatible).
        Set `include_inactive=True` to include products with `isActive=false`.
        Set `include_deleted=True` to include products with `isDeleted=true`.
        """
        cache_key = f"all_products:inactive={include_inactive}:deleted={include_deleted}"
        if self.cache.has(cache_key):
            return self.cache.get(cache_key)

        docs = self.products_ref.stream()
        result = []
        for doc in docs:
            data = doc.to_dict() or {}

            # Determine item flags
            is_active = self._coerce_bool(data.get("isActive"), True)
            is_deleted = self._coerce_bool(data.get("isDeleted"), False)

            # Apply filters based on function args
            if (not include_inactive) and (not is_active):
                continue
            if (not include_deleted) and is_deleted:
                continue

            enriched = dict(data)
            enriched["id"] = doc.id
            result.append(enriched)

        self.cache.set(cache_key, result, ttl=300)  # Cache 5 phút
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
        if not isinstance(product, dict):
            raise ValueError("product must be a dict")

        product_id = product.get("Id") or product.get("id")
        if product_id is None:
            raise ValueError("product Id is required")

        doc_ref = self.products_ref.document(str(product_id))

        if not self._should_store_product(product):
            doc_ref.delete()
            self.cache.invalidate(str(product_id))
            self.cache.invalidate("all_products")
            return {"message": "Product skipped because inactive or deleted", "skipped": True}

        doc_ref.set(product)
        self.cache.invalidate(str(product_id))
        self.cache.invalidate("all_products")
        return {"message": "Product added"}

    def update_product(self, product_id, updates):
        doc_ref = self.products_ref.document(product_id)
        doc_ref.update(updates)
        self.cache.invalidate(product_id)
        self.cache.invalidate("all_products")

        current_doc = doc_ref.get()
        if current_doc.exists and not self._should_store_product(current_doc.to_dict()):
            doc_ref.delete()
            self.cache.invalidate(product_id)
            self.cache.invalidate("all_products")
            return {"message": "Product removed because inactive or deleted"}

        return {"message": "Product updated"}
    
    def update_products(self, products_dict):
        updated = []
        removed = []
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
            if not self._should_store_product(prod):
                doc_ref.delete()
                removed.append(product_id)
                self.cache.invalidate(product_id)
                continue
            doc_ref.set(prod, merge=True)
            updated.append(product_id)
            self.cache.invalidate(product_id)
        self.cache.invalidate("all_products")
        response = {"message": f"Updated {len(updated)} products", "updated": updated}
        if removed:
            response["removed"] = removed
            response["message"] += f", removed {len(removed)} products"
        return response


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
            active_ids: Set[str] = set()
            deleted_count = 0
            inactive_count = 0

            for item in api_items:
                product_dict = item.__dict__ if hasattr(item, "__dict__") else dict(item)
                doc_id = str(product_dict.get("Id"))
                if not doc_id:
                    continue

                # Determine flags from API
                is_deleted = self._coerce_bool(product_dict.get("isDeleted"), False)
                is_active = self._coerce_bool(product_dict.get("isActive"), True)

                # Count for reporting
                if is_deleted:
                    deleted_count += 1
                if not is_active:
                    inactive_count += 1

                # Keep track of ids present in API
                active_ids.add(doc_id)

                checksum = self.hash_item(product_dict)
                if existing_checksums.get(doc_id) == checksum:
                    continue

                # Prepare payload to store in Firestore (include flags so clients can act)
                product_to_store = dict(product_dict)
                product_to_store["SyncChecksum"] = checksum
                if not is_active:
                    product_to_store["StoreForIndexedDB"] = True
                if is_deleted:
                    product_to_store["KiotVietDeleted"] = True

                to_upsert.append((doc_id, product_to_store))

            # Thực thi batch để hạn chế số round-trip (chỉ upsert, KHÔNG xóa)
            BATCH_SIZE = 500
            for i in range(0, len(to_upsert), BATCH_SIZE):
                batch = db.batch()
                for doc_id, payload in to_upsert[i : i + BATCH_SIZE]:
                    doc_ref = self.products_ref.document(doc_id)
                    batch.set(doc_ref, payload)
                batch.commit()

            # Không xóa các sản phẩm trong Firestore nếu chúng không xuất hiện trong KiotViet.
            # Giữ nguyên các sản phẩm chỉ có trong Firestore (firebase-only).

            # Invalidate cache for affected documents
            self.cache.invalidate("all_products")
            for doc_id, _ in to_upsert:
                self.cache.invalidate(doc_id)

            if inactive_count or deleted_count:
                print(f"Đã bao gồm {inactive_count} sản phẩm inactive và {deleted_count} sản phẩm deleted từ KiotViet.")

            print(f"Đồng bộ hoàn tất: cập nhật/thêm {len(to_upsert)} sản phẩm. (Không xóa sản phẩm Firestore)")
            return {
                "message": "Đã đồng bộ sản phẩm (upsert only, no deletes)",
                "updated_or_created": len(to_upsert),
                "total_api_items": len(api_items),
                "inactive_included": inactive_count,
                "deleted_included": deleted_count,
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
        print("Đang gọi API đồng bộ sản phẩm (single fetch)...")
        single_batch = self._fetch_single_batch()
        if single_batch is not None:
            print(f"Đã nhận {len(single_batch)} sản phẩm từ API (single batch).")
            return [Product.from_dict(item) for item in single_batch]

        print("Single batch không đủ, chuyển sang phân trang...")
        return self._fetch_paginated_items()

    def _fetch_single_batch(self) -> Optional[List[dict]]:
        params = {
            "clientId": API_CLIENT_ID,
            "resourceName": API_RESOURCE,
            "pageSize": API_SINGLE_FETCH_LIMIT,
        }

        response = requests.get(API_BASE_URL, params=params, headers=API_HEADERS, timeout=60)
        response.raise_for_status()
        payload = response.json() or {}
        items = payload.get("Data", []) or []

        total = payload.get("Total") or payload.get("total")
        if total and total > len(items):
            return None
        if len(items) >= API_SINGLE_FETCH_LIMIT:
            return None
        return items

    def _fetch_paginated_items(self) -> List[Product]:
        products: List[Product] = []
        page_index = 0
        total_returned = 0
        seen_ids: Set[str] = set()
        duplicate_pages = 0
        MAX_DUPLICATE_PAGES = 3

        while True:
            params = {
                "clientId": API_CLIENT_ID,
                "resourceName": API_RESOURCE,
                "pageSize": API_PAGE_SIZE,
                "pageIndex": page_index,
            }

            response = requests.get(API_BASE_URL, params=params, headers=API_HEADERS, timeout=30)
            response.raise_for_status()
            payload = response.json() or {}
            items = payload.get("Data", [])

            if not items:
                break

            unique_items = []
            for item in items:
                product_id_raw = item.get("Id") if isinstance(item, dict) else None
                product_id = str(product_id_raw) if product_id_raw is not None else None
                if product_id is None:
                    continue
                if product_id in seen_ids:
                    continue
                seen_ids.add(product_id)
                unique_items.append(item)

            if not unique_items:
                duplicate_pages += 1
                print(
                    f"  Trang {page_index} chỉ chứa sản phẩm trùng Id đã nhận ({duplicate_pages}/{MAX_DUPLICATE_PAGES})."
                )
                if duplicate_pages >= MAX_DUPLICATE_PAGES:
                    print("  Đã gặp quá nhiều trang trùng lặp liên tiếp, dừng phân trang.")
                    break
                page_index += 1
                continue

            duplicate_pages = 0

            try:
                batch_products = [Product.from_dict(item) for item in unique_items]
            except KeyError as exc:
                missing_key = str(exc)
                print(f"Thiếu khóa {missing_key} trong dữ liệu sản phẩm trang {page_index}, bỏ qua trang này")
                page_index += 1
                continue

            products.extend(batch_products)
            total_returned += len(batch_products)

            print(
                f"  Đã nhận {len(batch_products)} sản phẩm mới ở trang {page_index} (tổng duy nhất {total_returned})."
            )

            if len(items) < API_PAGE_SIZE:
                break

            page_index += 1

        print(f"Đã nhận tổng cộng {len(products)} sản phẩm từ API (phân trang).")
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
