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
from typing import Any, Dict, List, Optional, Set
from datetime import datetime
from firebase.init_firebase import init_firestore

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

# Sử dụng init_firestore thay vì khởi tạo trực tiếp
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HANGHOA", app_name="hanghoa_app")



class FirestoreProductService:
    def __init__(self, cache):
        """
        Initialize FirestoreProductService.
        
        Args:
            cache: Cache object (from firebase.firebase_service.cache.Cache)
        """
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
        is_deleted = cls._coerce_bool(record.get("isDeleted"), False)
        return not is_deleted

    def read_all_products(self, include_inactive: bool = False, include_deleted: bool = False):
        """Read products from Firestore."""
        cache_key = f"all_products:inactive={include_inactive}:deleted={include_deleted}"
        if self.cache.has(cache_key):
            return self.cache.get(cache_key)

        docs = self.products_ref.stream()
        result = []
        for doc in docs:
            data = doc.to_dict() or {}

            is_active = self._coerce_bool(data.get("isActive"), True)
            is_deleted = self._coerce_bool(data.get("isDeleted"), False)

            if (not include_inactive) and (not is_active):
                continue
            if (not include_deleted) and is_deleted:
                continue

            enriched = dict(data)
            result.append(enriched)

        self.cache.set(cache_key, result, ttl=300)
        return result

    def read_product(self, product_id):
        if self.cache.has(product_id):
            return self.cache.get(product_id)

        doc = self.products_ref.document(str(product_id)).get()
        if doc.exists:
            product = doc.to_dict()
            self.cache.set(product_id, product, ttl=300)
            return product
        return None

    def add_product(self, product):
        """Add a single product to Firestore."""
        if not isinstance(product, dict):
            raise ValueError("product must be a dict")

        product_id = product.get("Id") or product.get("id")
        if product_id is None:
            raise ValueError("product Id is required")

        doc_ref = self.products_ref.document(str(product_id))

        if not self._should_store_product(product):
            doc_ref.delete()
            self.cache.invalidate(str(product_id))
            self.invalidate_all_product_caches()
            return {"message": "Product skipped because inactive or deleted", "skipped": True}

        # Add sync metadata
        product["SyncChecksum"] = self.hash_item(product)
        product["SyncTimestamp"] = datetime.utcnow().isoformat()

        doc_ref.set(product)
        self.cache.invalidate(str(product_id))
        self.invalidate_all_product_caches()
        return {"message": "Product added", "product_id": str(product_id)}

    def add_products_batch(self, products: List[Dict]) -> Dict:
        """
        Add multiple products to Firestore in batch.
        Uses Firestore batch writes for efficiency (max 500 per batch).
        """
        if not products:
            return {"status": "error", "message": "No products provided"}

        if not isinstance(products, list):
            return {"status": "error", "message": "Products must be a list"}

        try:
            batch = db.batch()
            added_count = 0
            skipped_count = 0
            errors = []

            for idx, product_data in enumerate(products):
                if not isinstance(product_data, dict):
                    errors.append({"index": idx, "error": "Product must be a dict"})
                    continue

                product_id = product_data.get("Id") or product_data.get("id")
                if not product_id:
                    errors.append({"index": idx, "error": "Missing Id"})
                    continue

                # Check if should store (not deleted)
                if not self._should_store_product(product_data):
                    skipped_count += 1
                    continue

                # Add sync metadata
                product_data["SyncChecksum"] = self.hash_item(product_data)
                product_data["SyncTimestamp"] = datetime.utcnow().isoformat()

                # Add to batch
                doc_ref = self.products_ref.document(str(product_id))
                batch.set(doc_ref, product_data)
                added_count += 1

                # Firestore batch limit is 500 operations
                if added_count % 500 == 0:
                    batch.commit()
                    batch = db.batch()
                    print(f"📦 Committed batch of 500 products...")

            # Commit remaining
            if added_count % 500 != 0:
                batch.commit()

            # Invalidate cache
            self.invalidate_all_product_caches()

            print(f"✅ Added {added_count} products in batch, skipped {skipped_count}")

            result = {
                "status": "success",
                "message": f"Added {added_count} products successfully",
                "added_count": added_count,
                "skipped_count": skipped_count,
                "total_requested": len(products)
            }

            if errors:
                result["errors"] = errors
                result["error_count"] = len(errors)

            return result

        except Exception as e:
            import traceback
            print(f"❌ Error in batch add: {e}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def update_product(self, product_id, updates):
        doc_ref = self.products_ref.document(str(product_id))
        doc_ref.update(updates)
        self.cache.invalidate(product_id)
        self.invalidate_all_product_caches()

        current_doc = doc_ref.get()
        if current_doc.exists and not self._should_store_product(current_doc.to_dict()):
            doc_ref.delete()
            self.cache.invalidate(product_id)
            self.invalidate_all_product_caches()
            return {"message": "Product removed because inactive or deleted"}

        return {"message": "Product updated"}
    
    def update_products(self, products_dict):
        updated = []
        removed = []
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
        self.invalidate_all_product_caches()
        response = {"message": f"Updated {len(updated)} products", "updated": updated}
        if removed:
            response["removed"] = removed
            response["message"] += f", removed {len(removed)} products"
        return response

    def delete_product(self, product_id):
        self.products_ref.document(str(product_id)).delete()
        self.cache.invalidate(product_id)
        self.invalidate_all_product_caches()
        return {"message": "Product deleted"}
    
    def group_product(self):
        """
        Group products by Master Item (MasterUnitId=None or 0) and their Child Items.
        """
        all_products = self.read_all_products()
        masters = {}
        children = []
        for prod in all_products:
            master_unit_id = prod.get("MasterUnitId")
            if master_unit_id is None or master_unit_id == 0:
                masters[str(prod.get("Id") or prod.get("id"))] = {"master": prod, "children": []}
            else:
                children.append(prod)
        for child in children:
            master_id = str(child.get("MasterUnitId"))
            if master_id in masters:
                masters[master_id]["children"].append(child)
        return masters
    
    def get_products_by_master(self, master_id: int) -> List[Dict]:
        """Get all products that have the given master product ID."""
        all_products = self.read_all_products(include_inactive=True, include_deleted=True)
        return [
            p for p in all_products 
            if p.get("MasterProductId") == master_id or p.get("MasterUnitId") == master_id
        ]

    def get_product_variants(self, product_id: int) -> Dict:
        """Get a product and all its variants (by unit and attributes)."""
        master = self.read_product(str(product_id))
        if not master:
            return {"master": None, "variants": [], "total": 0}

        variants = self.get_products_by_master(product_id)
        
        return {
            "master": master,
            "variants": variants,
            "total": 1 + len(variants)
        }
    
    def update_products_from_kiotviet_to_firestore(self):
        """Backwards-compatible wrapper for legacy callers."""
        return self.sync_products_from_kiotviet()

    def sync_products_from_kiotviet(self):
        """
        Optimized sync that:
        1. Fetches checksums from Firestore in one go
        2. Fetches products from KiotViet with timeout
        3. Compares and updates only changed products
        4.Returns stats without re-fetching all data
        """
        import time
        start_time = time.time()

        try:
            print("🔄 Bắt đầu đồng bộ sản phẩm từ KiotViet (tối ưu)...")

            # Step 1: Fetch checksums from Firestore (fast, minimal data)
            print("  📥 Lấy checksums từ Firestore...")
            checksum_start = time.time()
            existing_checksums = {}
            existing_ids = set()

            for doc in self.products_ref.select(["SyncChecksum"]).stream():
                data = doc.to_dict() or {}
                existing_checksums[doc.id] = data.get("SyncChecksum")
                existing_ids.add(doc.id)

            checksum_time = time.time() - checksum_start
            print(f"  ✅ Đã lấy {len(existing_checksums)} checksums trong {checksum_time:.2f}s")

            # Step 2: Fetch products from KiotViet API
            print("  📥 Lấy sản phẩm từ KiotViet API...")
            api_start = time.time()
            api_items = self.fetch_api_items()
            api_time = time.time() - api_start
            print(f"  ✅ Đã lấy {len(api_items)} sản phẩm từ KiotViet trong {api_time:.2f}s")

            # Step 3: Compare and prepare updates
            print("  🔍 So sánh và chuẩn bị cập nhật...")
            compare_start = time.time()
            to_upsert = []
            active_ids: Set[str] = set()
            deleted_count = 0
            inactive_count = 0
            unchanged_count = 0

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

                # Check if changed
                checksum = self.hash_item(product_dict)
                if existing_checksums.get(doc_id) == checksum:
                    unchanged_count += 1
                    continue

                # Prepare payload to store in Firestore
                product_to_store = dict(product_dict)
                product_to_store["SyncChecksum"] = checksum
                product_to_store["SyncTimestamp"] = datetime.utcnow().isoformat()
                if not is_active:
                    product_to_store["StoreForIndexedDB"] = True
                if is_deleted:
                    product_to_store["KiotVietDeleted"] = True

                to_upsert.append((doc_id, product_to_store))

            compare_time = time.time() - compare_start
            print(f"  ✅ So sánh hoàn tất trong {compare_time:.2f}s: {len(to_upsert)} cần cập nhật, {unchanged_count} không đổi")

            # Step 4: Batch update to Firestore
            update_time = 0
            if to_upsert:
                print(f"  📤 Cập nhật {len(to_upsert)} sản phẩm lên Firestore...")
                update_start = time.time()
                BATCH_SIZE = 500
                batch_count = 0

                for i in range(0, len(to_upsert), BATCH_SIZE):
                    batch = db.batch()
                    for doc_id, payload in to_upsert[i : i + BATCH_SIZE]:
                        doc_ref = self.products_ref.document(doc_id)
                        batch.set(doc_ref, payload, merge=True)
                    batch.commit()
                    batch_count += 1
                    if batch_count % 5 == 0:
                        print(f"    Đã ghi {batch_count * BATCH_SIZE} sản phẩm...")

                update_time = time.time() - update_start
                print(f"  ✅ Cập nhật hoàn tất trong {update_time:.2f}s ({batch_count} batches)")
            else:
                print("  ℹ️ Không có sản phẩm nào cần cập nhật")

            # Step 5: Invalidate cache
            print("  🗑️ Xóa cache...")
            self.invalidate_all_product_caches()
            for doc_id, _ in to_upsert:
                self.cache.invalidate(doc_id)

            total_time = time.time() - start_time

            print(f"\n✅ Đồng bộ hoàn tất trong {total_time:.2f}s:")
            print(f"   - Tổng sản phẩm từ KiotViet: {len(api_items)}")
            print(f"   - Cập nhật/thêm mới: {len(to_upsert)}")
            print(f"   - Không thay đổi: {unchanged_count}")
            print(f"   - Inactive: {inactive_count}")
            print(f"   - Deleted: {deleted_count}")

            return {
                "success": True,
                "message": "Đồng bộ thành công",
                "version": "optimized_v2",
                "stats": {
                    "total_api_items": len(api_items),
                    "updated_or_created": len(to_upsert),
                    "unchanged": unchanged_count,
                    "inactive_included": inactive_count,
                    "deleted_included": deleted_count,
                    "total_time_seconds": round(total_time, 2),
                    "breakdown": {
                        "checksum_fetch": round(checksum_time, 2),
                        "api_fetch": round(api_time, 2),
                        "compare": round(compare_time, 2),
                        "update": round(update_time, 2)
                    }
                }
            }
        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ Lỗi khi đồng bộ sản phẩm từ KiotViet: {exc}")
            print(error_trace)
            return {
                "success": False,
                "message": "Đồng bộ thất bại",
                "error": str(exc),
                "error_type": type(exc).__name__
            }

    def fetch_firestore_items(self):
        print("Đang tải dữ liệu từ Firestore...")
        docs = self.products_ref.stream()
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
        """Fetch all products in a single batch with retry logic."""
        params = {
            "clientId": API_CLIENT_ID,
            "resourceName": API_RESOURCE,
            "pageSize": API_SINGLE_FETCH_LIMIT,
        }

        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                response = requests.get(
                    API_BASE_URL,
                    params=params,
                    headers=API_HEADERS,
                    timeout=90
                )
                response.raise_for_status()
                payload = response.json() or {}
                items = payload.get("Data", []) or []

                total = payload.get("Total") or payload.get("total")
                if total and total > len(items):
                    return None
                if len(items) >= API_SINGLE_FETCH_LIMIT:
                    return None
                return items

            except requests.exceptions.Timeout:
                print(f"⚠️ Timeout khi fetch single batch (lần {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(retry_delay)
                    continue
                raise

            except requests.exceptions.RequestException as e:
                print(f"⚠️ Lỗi khi fetch single batch (lần {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(retry_delay)
                    continue
                raise

        return None

    def _fetch_paginated_items(self) -> List[Product]:
        """Fetch products with pagination and retry logic."""
        import time
        products: List[Product] = []
        page_index = 0
        total_returned = 0
        seen_ids: Set[str] = set()
        duplicate_pages = 0
        MAX_DUPLICATE_PAGES = 3
        max_retries = 3
        retry_delay = 2

        while True:
            params = {
                "clientId": API_CLIENT_ID,
                "resourceName": API_RESOURCE,
                "pageSize": API_PAGE_SIZE,
                "pageIndex": page_index,
            }

            page_fetched = False
            for attempt in range(max_retries):
                try:
                    response = requests.get(
                        API_BASE_URL,
                        params=params,
                        headers=API_HEADERS,
                        timeout=45
                    )
                    response.raise_for_status()
                    payload = response.json() or {}
                    items = payload.get("Data", [])
                    page_fetched = True
                    break

                except requests.exceptions.Timeout:
                    print(f"⚠️ Timeout khi fetch trang {page_index} (lần {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        print(f"❌ Không thể fetch trang {page_index} sau {max_retries} lần thử")
                        items = []
                        page_fetched = True
                        break

                except requests.exceptions.RequestException as e:
                    print(f"⚠️ Lỗi khi fetch trang {page_index} (lần {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        print(f"❌ Không thể fetch trang {page_index} sau {max_retries} lần thử")
                        items = []
                        page_fetched = True
                        break

            if not page_fetched or not items:
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
                print(f"  Trang {page_index} chỉ chứa sản phẩm trùng ({duplicate_pages}/{MAX_DUPLICATE_PAGES}).")
                if duplicate_pages >= MAX_DUPLICATE_PAGES:
                    print("  Đã gặp quá nhiều trang trùng lặp, dừng phân trang.")
                    break
                page_index += 1
                continue

            duplicate_pages = 0

            try:
                batch_products = [Product.from_dict(item) for item in unique_items]
            except KeyError as exc:
                missing_key = str(exc)
                print(f"Thiếu khóa {missing_key} trong dữ liệu trang {page_index}, bỏ qua")
                page_index += 1
                continue

            products.extend(batch_products)
            total_returned += len(batch_products)

            print(f"  Đã nhận {len(batch_products)} sản phẩm mới ở trang {page_index} (tổng {total_returned}).")

            if len(items) < API_PAGE_SIZE:
                break

            page_index += 1

        print(f"Đã nhận tổng cộng {len(products)} sản phẩm từ API (phân trang).")
        return products
    
    def update_changed_items(self, api_items, firestore_items):
        changed_items = []
        deleted_items = []
    
        for item in api_items:
            item_id = item.Id
            if not item_id:
                continue
            
            if getattr(item, 'isDeleted', False):
                deleted_items.append(item_id)
                continue
            
            item_dict = item.__dict__
            new_hash = self.hash_item(item_dict)
            old_hash = firestore_items.get(item_id, {}).get('hash')
    
            if new_hash != old_hash:
                changed_items.append(item_dict)
    
        print(f"Phát hiện {len(changed_items)} sản phẩm thay đổi. Đang cập nhật...")
        print(f"Phát hiện {len(deleted_items)} sản phẩm cần xóa khỏi Firestore.")
    
        BATCH_SIZE = 500
        for i in range(0, len(changed_items), BATCH_SIZE):
            batch = db.batch()
            for item in changed_items[i:i + BATCH_SIZE]:
                doc_ref = self.products_ref.document(str(item['Id']))
                batch.set(doc_ref, item, merge=True)
            batch.commit()
            print(f"Đã cập nhật batch {i // BATCH_SIZE + 1}")
    
        for i in range(0, len(deleted_items), BATCH_SIZE):
            batch = db.batch()
            for item_id in deleted_items[i:i + BATCH_SIZE]:
                doc_ref = self.products_ref.document(str(item_id))
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
        item_copy.pop("SyncTimestamp", None)
        return hashlib.md5(json.dumps(item_copy, sort_keys=True, default=default_serializer).encode()).hexdigest()

    @staticmethod
    def is_newer(api_mod, fs_mod):
        try:
            if not api_mod:
                return False
            if not fs_mod:
                return True
            return parse_date(api_mod) > parse_date(fs_mod)
        except Exception:
            return False

    def read_all_products_fresh(self, include_inactive: bool = False, include_deleted: bool = False):
        """Đọc TẤT CẢ products trực tiếp từ Firestore, KHÔNG dùng cache."""
        print(f"🔄 read_all_products_fresh (include_inactive={include_inactive}, include_deleted={include_deleted})")

        docs = self.products_ref.stream()
        result = []

        for doc in docs:
            data = doc.to_dict() or {}

            is_active = self._coerce_bool(data.get("isActive"), True)
            is_deleted = self._coerce_bool(data.get("isDeleted"), False)

            if (not include_inactive) and (not is_active):
                continue
            if (not include_deleted) and is_deleted:
                continue

            result.append(dict(data))

        print(f"✅ Fetched {len(result)} products from Firestore (fresh)")
        return result

    def invalidate_all_product_caches(self):
        """Invalidate tất cả các cache keys liên quan đến products"""
        cache_keys_to_invalidate = [
            "all_products",
            "all_products:inactive=False:deleted=False",
            "all_products:inactive=True:deleted=False",
            "all_products:inactive=False:deleted=True",
            "all_products:inactive=True:deleted=True",
        ]

        for key in cache_keys_to_invalidate:
            self.cache.invalidate(key)

        print(f"🗑️ Invalidated {len(cache_keys_to_invalidate)} product cache keys")