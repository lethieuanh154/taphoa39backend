import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv
import json
import requests
from FromKiotViet.get_authorization import get_token
from FromKiotViet.get_category import get_category
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
    "Authorization": get_token(),
    "retailer": retailer,
    "branchid": LatestBranchId,
}
COLLECTION_NAME = "products"

# Cache TTL: 1 giờ cho tất cả product cache
CACHE_TTL = 3600
CACHE_TTL_CLONE_STOCK = 3600

# Sử dụng init_firestore thay vì khởi tạo trực tiếp
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_PRODUCT", app_name="product_app")



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
    def _normalize_string(s: str) -> str:
        """
        Normalize string for search (remove diacritics, uppercase).
        Used for NormalizedCode and NormalizedName fields.
        """
        if not s:
            return ""
        import unicodedata
        import re
        # Remove diacritics (accents)
        normalized = unicodedata.normalize('NFD', s)
        normalized = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
        # Replace đ/Đ
        normalized = normalized.replace('đ', 'd').replace('Đ', 'D')
        # Uppercase
        normalized = normalized.upper()
        # Replace non-alphanumeric with underscore
        normalized = re.sub(r'[^A-Z0-9]', '_', normalized)
        # Collapse multiple underscores
        normalized = re.sub(r'_+', '_', normalized)
        return normalized

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

    CATEGORIES_CACHE_KEY = "categories_list"
    CATEGORIES_TTL = 21600  # 6h - danh muc it thay doi
    CATEGORIES_DOC = "categories"
    CONFIG_COLLECTION = "app_config"

    def read_categories(self) -> List[Dict]:
        """Danh sach danh muc [{Id, Name, Path}] - DUONG PHUC VU REQUEST KHACH.

        TUYET DOI khong goi KiotViet o day: `get_category()` la HTTP ra ngoai, cham/treo
        thi giu luon thread gunicorn (--workers=1) -> nginx 504 ca cac API khac. KiotViet
        chi duoc goi trong `refresh_categories_from_kiotviet()` chay o thread nen.
        Thu tu: cache RAM -> snapshot Firestore (1 doc, co deadline) -> KiotViet (chi khi
        chua he co snapshot, tuc lan chay dau tien).
        """
        if self.cache.has(self.CATEGORIES_CACHE_KEY):
            return self.cache.get(self.CATEGORIES_CACHE_KEY)

        categories = self._read_categories_snapshot()
        if not categories:
            # Bootstrap: chua co snapshot nao -> danh phai goi KiotViet 1 lan
            categories = self.refresh_categories_from_kiotviet() or []

        self.cache.set(self.CATEGORIES_CACHE_KEY, categories, ttl=self.CATEGORIES_TTL)
        return categories

    def refresh_categories_from_kiotviet(self) -> Optional[List[Dict]]:
        """Lay danh muc moi tu KiotViet roi ghi snapshot. Goi tu thread nen, KHONG tu request."""
        try:
            categories = get_category()
        except Exception as e:
            print(f"[Categories] KiotViet error: {e}")
            return None

        if not categories:
            print("[Categories] KiotViet khong tra du lieu -> giu snapshot cu")
            return None

        self._save_categories_snapshot(categories)
        self.cache.set(self.CATEGORIES_CACHE_KEY, categories, ttl=self.CATEGORIES_TTL)
        print(f"[Categories] Refreshed {len(categories)} danh muc tu KiotViet")
        return categories

    def get_cached_all_products(self) -> Optional[List[Dict]]:
        """Tra products dang nam trong cache, KHONG bao gio tu di fetch.

        `read_all_products()` stream ca collection -> tren prod da tung 503 "Query timed
        out". Endpoint public chi duoc dung ban cache san, khong duoc keo them full scan.
        """
        cache_key = "all_products:inactive=False:deleted=False"
        if self.cache.has(cache_key):
            return self.cache.get(cache_key)
        return None

    def _save_categories_snapshot(self, categories: List[Dict]) -> None:
        try:
            db.collection(self.CONFIG_COLLECTION).document(self.CATEGORIES_DOC).set({
                "items": categories,
                "updatedAt": datetime.now().isoformat(),
            })
        except Exception as e:
            print(f"[read_categories] Save snapshot failed: {e}")

    def _read_categories_snapshot(self) -> List[Dict]:
        try:
            doc = db.collection(self.CONFIG_COLLECTION).document(self.CATEGORIES_DOC).get()
            if doc.exists:
                return (doc.to_dict() or {}).get("items") or []
        except Exception as e:
            print(f"[read_categories] Read snapshot failed: {e}")
        return []

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

        self.cache.set(cache_key, result, ttl=CACHE_TTL)
        return result

    def read_product(self, product_id):
        if self.cache.has(product_id):
            return self.cache.get(product_id)

        doc = self.products_ref.document(str(product_id)).get()
        if doc.exists:
            product = doc.to_dict()
            self.cache.set(product_id, product, ttl=CACHE_TTL)
            return product
        return None

    def get_products_by_master_unit_id(self, master_unit_id: str) -> List[Dict]:
        """
        Get all products (siblings) that share the same MasterUnitId.
        This includes:
        1. The master product itself (where Id == MasterUnitId or MasterUnitId is None/0)
        2. All child products that have this MasterUnitId

        Args:
            master_unit_id: The MasterUnitId to search for

        Returns:
            List of product dicts that belong to this product group
        """
        if not master_unit_id:
            return []

        try:
            results = []
            master_id_str = str(master_unit_id)
            master_id_int = int(master_unit_id) if master_unit_id.isdigit() else None

            # Query 1: Products where MasterUnitId equals the given value
            query1 = self.products_ref.where("MasterUnitId", "==", master_id_int).stream()
            for doc in query1:
                data = doc.to_dict()
                if data:
                    results.append(data)

            # Query 2: The master product itself (where Id == master_unit_id)
            master_doc = self.products_ref.document(master_id_str).get()
            if master_doc.exists:
                master_data = master_doc.to_dict()
                # Add if not already in results
                if master_data and not any(r.get('Id') == master_data.get('Id') for r in results):
                    results.append(master_data)

            print(f"  📦 get_products_by_master_unit_id({master_unit_id}): Found {len(results)} products")
            return results

        except Exception as e:
            print(f"  ❌ Error in get_products_by_master_unit_id: {e}")
            return []

    def _sanitize_inventory_fields(self, product: dict) -> dict:
        """
        Removes inappropriate inventory fields based on whether the product is a clone.
        - Clones should only have onHandNV.
        - Originals should only have onHand.
        """
        if not isinstance(product, dict):
            return product

        is_clone = self._coerce_bool(product.get("isClone"), False)

        if is_clone:
            # Clones should not have onHand
            if "onHand" in product:
                product.pop("onHand", None)
        else:
            # Originals should not have onHandNV
            if "onHandNV" in product:
                product.pop("onHandNV", None)
        
        return product

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
            self._smart_invalidate_product(product_id, is_delete=True,
                                           category_id=product.get("CategoryId"))
            return {"message": "Product skipped because inactive or deleted", "skipped": True}

        # Add sync metadata
        product["SyncChecksum"] = self.hash_item(product)
        product["SyncTimestamp"] = datetime.utcnow().isoformat()

        # ✅ Enforce inventory field rules
        product = self._sanitize_inventory_fields(product)

        doc_ref.set(product)
        # Add new product to cached lists
        self.cache.invalidate(str(product_id))
        self.cache.add_item_to_lists("all_products", product)
        self.cache.invalidate_prefix("featured_products:")
        if product.get("CategoryId"):
            self.cache.invalidate(f"products_by_category:{product['CategoryId']}:inactive=False")
            self.cache.invalidate(f"products_by_category:{product['CategoryId']}:inactive=True")
        return {"message": "Product added", "product_id": str(product_id)}

    def add_products_batch(self, products: List[Dict]) -> Dict:
        """
        Add multiple products to Firestore in batch.
        Uses Firestore batch writes for efficiency (max 500 per batch).

        ✅ DUPLICATE CHECK: Kiểm tra trùng Code trước khi thêm để ngăn tạo products duplicate.
        """
        if not products:
            return {"status": "error", "message": "No products provided"}

        if not isinstance(products, list):
            return {"status": "error", "message": "Products must be a list"}

        try:
            # ✅ Step 1: Check duplicate CHỈ cho các IDs/Codes cần thêm (không stream toàn bộ collection)
            existing_codes = set()
            existing_ids = set()
            try:
                # Batch get by document IDs - chỉ fetch các documents cần check
                candidate_ids = [str(p.get("Id") or p.get("id")) for p in products if p.get("Id") or p.get("id")]
                if candidate_ids:
                    doc_refs = [self.products_ref.document(pid) for pid in candidate_ids]
                    # Firestore getAll - fetch nhiều documents cùng lúc
                    docs = db.get_all(doc_refs)
                    for doc in docs:
                        if doc.exists:
                            doc_data = doc.to_dict()
                            doc_id = doc_data.get("Id")
                            if doc_id:
                                existing_ids.add(str(doc_id))
                            code = doc_data.get("Code", "")
                            if code:
                                existing_codes.add(code.upper())

                # Check duplicate Code cho non-clone products bằng query thay vì stream all
                non_clone_codes = [
                    p.get("Code", "")
                    for p in products
                    if p.get("Code") and not p.get("isClone", False) and str(p.get("Id") or "") not in existing_ids
                ]
                if non_clone_codes:
                    # Firestore 'in' query hỗ trợ tối đa 30 values, case-sensitive nên dùng code gốc
                    for i in range(0, len(non_clone_codes), 30):
                        chunk = [c for c in non_clone_codes[i:i+30] if c]
                        if not chunk:
                            continue
                        query = self.products_ref.where("Code", "in", chunk)
                        for doc in query.stream():
                            doc_data = doc.to_dict()
                            code = doc_data.get("Code", "")
                            if code:
                                existing_codes.add(code.upper())

                print(f"📋 Checked {len(candidate_ids)} candidate IDs: {len(existing_ids)} existing, {len(existing_codes)} existing codes")
            except Exception as e:
                print(f"⚠️ Could not fetch existing data: {e}")
                # Continue without duplicate check

            batch = db.batch()
            added_count = 0
            skipped_count = 0
            duplicate_count = 0
            errors = []

            for idx, product_data in enumerate(products):
                if not isinstance(product_data, dict):
                    errors.append({"index": idx, "error": "Product must be a dict"})
                    continue

                product_id = product_data.get("Id") or product_data.get("id")
                if not product_id:
                    errors.append({"index": idx, "error": "Missing Id"})
                    continue

                # ✅ Step 2: Check duplicate - CHỈ check nếu KHÔNG phải clone product
                # Clone products được phép có cùng Code với original products
                product_code = product_data.get("Code", "")
                is_clone = product_data.get("isClone", False)
                if isinstance(is_clone, str):
                    is_clone = is_clone.lower() == "true"

                # ✅ Check duplicate Id (product với cùng Id đã tồn tại)
                if str(product_id) in existing_ids:
                    duplicate_count += 1
                    errors.append({
                        "index": idx,
                        "error": f"Duplicate Id: {product_id}",
                        "product_id": product_id
                    })
                    print(f"⚠️ Skipping duplicate product Id: {product_id}")
                    continue

                # ✅ Với non-clone products: check duplicate Code
                # Clone products được phép có cùng Code với original
                if not is_clone and product_code and product_code.upper() in existing_codes:
                    duplicate_count += 1
                    errors.append({
                        "index": idx,
                        "error": f"Duplicate Code: {product_code}",
                        "product_id": product_id
                    })
                    print(f"⚠️ Skipping duplicate product Code: {product_code}")
                    continue

                # Check if should store (not deleted)
                if not self._should_store_product(product_data):
                    skipped_count += 1
                    continue

                # Add sync metadata
                product_data["SyncChecksum"] = self.hash_item(product_data)
                product_data["SyncTimestamp"] = datetime.utcnow().isoformat()

                # ✅ Enforce inventory field rules
                product_data = self._sanitize_inventory_fields(product_data)

                # Add to batch
                doc_ref = self.products_ref.document(str(product_id))
                batch.set(doc_ref, product_data)
                added_count += 1

                # ✅ Add to existing sets để không bị duplicate trong cùng batch
                existing_ids.add(str(product_id))
                if product_code:
                    existing_codes.add(product_code.upper())

                # Firestore batch limit is 500 operations
                if added_count % 500 == 0:
                    batch.commit()
                    batch = db.batch()
                    print(f"📦 Committed batch of 500 products...")

            # Commit remaining
            if added_count % 500 != 0:
                batch.commit()

            # Batch add → invalidate all (nhiều products mới, không thể patch từng cái)
            self.invalidate_all_product_caches()

            print(f"✅ Added {added_count} products in batch, skipped {skipped_count}, duplicates {duplicate_count}")

            result = {
                "status": "success",
                "message": f"Added {added_count} products successfully",
                "added_count": added_count,
                "skipped_count": skipped_count,
                "duplicate_count": duplicate_count,
                "total_requested": len(products)
            }

            if errors:
                result["errors"] = errors
                result["error_count"] = len(errors)

            # ✅ Cảnh báo nếu tất cả đều bị duplicate
            if duplicate_count > 0 and added_count == 0:
                result["status"] = "warning"
                result["message"] = f"All {duplicate_count} products already exist (duplicate Codes)"

            return result

        except Exception as e:
            import traceback
            print(f"❌ Error in batch add: {e}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def update_product(self, product_id, updates):
        # ✅ Debug log to see what's being sent to Firestore
        print(f"📝 [update_product] Product {product_id}: Updating with fields: {list(updates.keys())}")

        # ✅ Enforce inventory field rules before updating
        try:
            product_doc = self.read_product(product_id)
            if product_doc:
                is_clone = self._coerce_bool(product_doc.get("isClone"), False)
                if is_clone:
                    if "onHand" in updates:
                        updates.pop("onHand", None)
                        print(f"   sanitized: Removed onHand from clone {product_id}")
                else:
                    if "onHandNV" in updates:
                        updates.pop("onHandNV", None)
                        print(f"   sanitized: Removed onHandNV from original {product_id}")
        except Exception as e:
            print(f"   ⚠️ Could not sanitize product {product_id} before update: {e}")

        if "OnHand" in updates:
            print(f"   ⚠️ OnHand will be updated to: {updates['OnHand']}")
        if "OnHandNV" in updates:
            print(f"   ✅ OnHandNV will be updated to: {updates['OnHandNV']}")

        # Luôn cập nhật ModifiedDate để đảm bảo các client có thể đồng bộ thay đổi
        updates["ModifiedDate"] = datetime.utcnow().isoformat()

        doc_ref = self.products_ref.document(str(product_id))
        doc_ref.update(updates)

        affects_stock = "OnHand" in updates or "OnHandNV" in updates
        category_id = updates.get("CategoryId") or (product_doc.get("CategoryId") if product_doc else None)
        self._smart_invalidate_product(product_id, updated_data=updates,
                                       category_id=category_id, affects_stock=affects_stock)

        current_doc = doc_ref.get()
        if current_doc.exists and not self._should_store_product(current_doc.to_dict()):
            doc_ref.delete()
            self._smart_invalidate_product(product_id, is_delete=True, category_id=category_id)
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
            
            # ✅ Enforce inventory field rules
            prod = self._sanitize_inventory_fields(prod)

            # Luôn cập nhật ModifiedDate để đảm bảo đồng bộ
            prod["ModifiedDate"] = datetime.utcnow().isoformat()

            doc_ref.set(prod, merge=True)
            updated.append(product_id)
            self.cache.invalidate(product_id)
            # Patch cached lists in-place
            self.cache.update_item_in_lists("all_products", "Id", product_id, prod)
        # Invalidate category and featured caches (batch update may affect multiple categories)
        self.cache.invalidate_prefix("products_by_category:")
        self.cache.invalidate("clone_stock_map")
        if removed:
            self.cache.invalidate_prefix("featured_products:")
            for rid in removed:
                self.cache.remove_item_from_lists("all_products", "Id", rid)
        response = {"message": f"Updated {len(updated)} products", "updated": updated}
        if removed:
            response["removed"] = removed
            response["message"] += f", removed {len(removed)} products"
        return response

    def delete_product(self, product_id):
        # Read product before delete to get category info
        product_doc = self.read_product(str(product_id))
        category_id = product_doc.get("CategoryId") if product_doc else None
        self.products_ref.document(str(product_id)).delete()
        self._smart_invalidate_product(product_id, is_delete=True,
                                       category_id=category_id, affects_stock=True)
        return {"message": "Product deleted"}

    def delete_product_with_siblings(self, product_id) -> Dict:
        """
        Delete a product AND all its siblings (products with the same MasterUnitId).
        This is used for clone products where we want to delete the entire product group.

        Args:
            product_id: The ID of the product to delete (can be master or any sibling)

        Returns:
            Dict with deletion results
        """
        product_id_str = str(product_id)
        deleted_ids = []
        errors = []

        try:
            # First, read the product to get its MasterUnitId
            product_doc = self.read_product(product_id_str)
            if not product_doc:
                return {"message": "Product not found", "deleted_count": 0, "deleted_ids": []}

            # Get the MasterUnitId (if it's a child) or use its own Id (if it's the master)
            master_unit_id = product_doc.get('MasterUnitId') or product_doc.get('Id')
            master_unit_id_str = str(master_unit_id)

            print(f"🗑️ delete_product_with_siblings: Deleting product group for MasterUnitId={master_unit_id_str}")

            # Get all siblings (including the master)
            siblings = self.get_products_by_master_unit_id(master_unit_id_str)

            if not siblings:
                # Fallback: just delete the single product
                self.products_ref.document(product_id_str).delete()
                self.cache.invalidate(product_id_str)
                deleted_ids.append(product_id_str)
            else:
                # Delete all siblings
                for sibling in siblings:
                    sibling_id = str(sibling.get('Id'))
                    try:
                        self.products_ref.document(sibling_id).delete()
                        self.cache.invalidate(sibling_id)
                        deleted_ids.append(sibling_id)
                        print(f"  ✅ Deleted sibling: {sibling_id}")
                    except Exception as e:
                        print(f"  ❌ Error deleting sibling {sibling_id}: {e}")
                        errors.append({"id": sibling_id, "error": str(e)})

            # Smart invalidate for each deleted sibling
            for did in deleted_ids:
                self._smart_invalidate_product(did, is_delete=True, affects_stock=True)

            result = {
                "message": f"Deleted {len(deleted_ids)} products",
                "deleted_count": len(deleted_ids),
                "deleted_ids": deleted_ids
            }
            if errors:
                result["errors"] = errors

            print(f"✅ delete_product_with_siblings complete: {len(deleted_ids)} deleted")
            return result

        except Exception as e:
            print(f"❌ Error in delete_product_with_siblings: {e}")
            return {"message": f"Error: {str(e)}", "deleted_count": 0, "deleted_ids": [], "error": str(e)}
    
    def cleanup_deleted_products(self):
        """
        Tìm và xóa tất cả sản phẩm có isDeleted=true hoặc KiotVietDeleted=true khỏi Firebase.
        Returns dict với thông tin số lượng đã xóa và danh sách IDs.
        """
        print("🧹 Bắt đầu dọn dẹp sản phẩm đã xóa từ Firebase...")

        deleted_ids = []
        errors = []

        try:
            # Scan tất cả products, kiểm tra isDeleted và KiotVietDeleted
            for doc in self.products_ref.select(["isDeleted", "KiotVietDeleted", "Code", "Name"]).stream():
                data = doc.to_dict() or {}
                is_deleted = self._coerce_bool(data.get("isDeleted"), False)
                kv_deleted = self._coerce_bool(data.get("KiotVietDeleted"), False)

                if is_deleted or kv_deleted:
                    try:
                        self.products_ref.document(doc.id).delete()
                        deleted_ids.append({
                            "id": doc.id,
                            "code": data.get("Code"),
                            "name": data.get("Name"),
                            "isDeleted": is_deleted,
                            "KiotVietDeleted": kv_deleted,
                        })
                        self.cache.invalidate(doc.id)
                        print(f"  🗑️ Đã xóa: {doc.id} - {data.get('Code')} - {data.get('Name')}")
                    except Exception as e:
                        errors.append({"id": doc.id, "error": str(e)})
                        print(f"  ❌ Lỗi khi xóa {doc.id}: {e}")

            if deleted_ids:
                self.invalidate_all_product_caches()

            print(f"✅ Dọn dẹp hoàn tất: {len(deleted_ids)} sản phẩm đã xóa")

            result = {
                "success": True,
                "message": f"Đã xóa {len(deleted_ids)} sản phẩm đã bị xóa trên KiotViet",
                "deleted_count": len(deleted_ids),
                "deleted_products": deleted_ids,
            }
            if errors:
                result["errors"] = errors
            return result

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"Lỗi khi dọn dẹp: {str(e)}",
                "deleted_count": len(deleted_ids),
                "deleted_products": deleted_ids,
            }

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

            # Step 1: Fetch checksums AND isClone flag from Firestore (fast, minimal data)
            print("  📥 Lấy checksums và isClone từ Firestore...")
            checksum_start = time.time()
            existing_checksums = {}
            existing_ids = set()
            clone_product_ids = set()  # ✅ NEW: Track clone products

            for doc in self.products_ref.select(["SyncChecksum", "isClone"]).stream():
                data = doc.to_dict() or {}
                existing_checksums[doc.id] = data.get("SyncChecksum")
                existing_ids.add(doc.id)
                # ✅ NEW: Track if this product is a clone
                if data.get("isClone") is True or data.get("isClone") == "true":
                    clone_product_ids.add(doc.id)

            checksum_time = time.time() - checksum_start
            print(f"  ✅ Đã lấy {len(existing_checksums)} checksums trong {checksum_time:.2f}s")
            print(f"  📋 Phát hiện {len(clone_product_ids)} clone products (sẽ bỏ qua sync OnHand)")

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

                # Skip deleted products - không lưu vào Firebase
                if is_deleted:
                    # Nếu product đã tồn tại trong Firebase, xóa nó
                    if doc_id in existing_ids:
                        try:
                            self.products_ref.document(doc_id).delete()
                            self.cache.invalidate(doc_id)
                            print(f"  🗑️ Xóa sản phẩm đã bị xóa trên KiotViet: {doc_id}")
                        except Exception as e:
                            print(f"  ❌ Lỗi khi xóa {doc_id}: {e}")
                    continue

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

                # ✅ Enforce inventory rule: KiotViet products are originals, so they should not have onHandNV.
                # The 'isClone' flag is internal to our app, so we can't use the generic sanitizer here.
                if "onHandNV" in product_to_store:
                    product_to_store.pop("onHandNV", None)

                # ✅ NEW: For clone products, DO NOT sync OnHand from KiotViet
                # Clone products manage their own inventory via OnHandNV, not OnHand
                # KiotViet doesn't know about clones, so it may return incorrect OnHand values
                if doc_id in clone_product_ids:
                    # Remove OnHand from the update payload to preserve existing value
                    if "OnHand" in product_to_store:
                        product_to_store.pop("OnHand", None)
                    print(f"  ⏭️ Clone product {doc_id}: Skipping OnHand sync (preserving OnHandNV)")

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

            # Step 5: Sync clones with updated original products
            clone_sync_time = 0
            clones_updated = 0
            if to_upsert:
                print("  🔄 Đồng bộ clones với products gốc đã cập nhật...")
                clone_sync_start = time.time()
                clones_updated = self._sync_clones_with_originals(to_upsert)
                clone_sync_time = time.time() - clone_sync_start
                print(f"  ✅ Đã cập nhật {clones_updated} clones trong {clone_sync_time:.2f}s")

            # Step 6: Invalidate cache
            print("  🗑️ Xóa cache...")
            self.invalidate_all_product_caches()
            for doc_id, _ in to_upsert:
                self.cache.invalidate(doc_id)

            total_time = time.time() - start_time

            print(f"\n✅ Đồng bộ hoàn tất trong {total_time:.2f}s:")
            print(f"   - Tổng sản phẩm từ KiotViet: {len(api_items)}")
            print(f"   - Cập nhật/thêm mới: {len(to_upsert)}")
            print(f"   - Clones cập nhật: {clones_updated}")
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
                    "clones_updated": clones_updated,
                    "unchanged": unchanged_count,
                    "inactive_included": inactive_count,
                    "deleted_included": deleted_count,
                    "total_time_seconds": round(total_time, 2),
                    "breakdown": {
                        "checksum_fetch": round(checksum_time, 2),
                        "api_fetch": round(api_time, 2),
                        "compare": round(compare_time, 2),
                        "update": round(update_time, 2),
                        "clone_sync": round(clone_sync_time, 2)
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

    def _sync_clones_with_originals(self, updated_originals: List[tuple]) -> int:
        """
        Đồng bộ một số trường chọn lọc từ product gốc xuống các clones của nó.

        Khi một product gốc được cập nhật, hàm này sẽ tìm tất cả các clones liên quan
        và cập nhật các trường được cho phép. Các trường quan trọng như Cost, BasePrice,
        và inventory của clone sẽ được bảo vệ và không bị ghi đè.

        Args:
            updated_originals: List các tuple (doc_id, product_dict) của các product gốc đã được cập nhật.

        Returns:
            Số lượng clones đã được cập nhật thành công.
        """
        if not updated_originals:
            return 0

        # Các trường an toàn để đồng bộ từ gốc sang clone.
        # KHÔNG BAO GIỜ thêm 'Cost', 'BasePrice', 'onHand', 'onHandNV' vào đây.
        # ❌ KHÔNG thêm 'Description': mô tả của clone do user tự nhập riêng cho clone
        #    (Edit Product Dialog), SP gốc trên KiotViet thường không có Description
        #    → sync xuống sẽ xoá trắng mô tả user vừa lưu.
        SYNC_FIELDS = [
            "Code",  # ✅ IMPORTANT: Sync Code để đảm bảo clone luôn khớp với product gốc
            "Name",
            "FullName",  # ✅ Thêm FullName để đồng bộ
            "CategoryName",
            "Tax",
            "Unit",
            "isActive",
            "Attributes",
            "Brand",
            "ConversionValue",
            "Image"  # ✅ Thêm Image để đồng bộ
            # Thêm các trường khác cần đồng bộ ở đây nếu cần.
        ]

        # Chuẩn bị dữ liệu nguồn từ các product gốc đã cập nhật
        # ✅ CRITICAL: bỏ qua field mà SP gốc không có (None) hoặc rỗng ('').
        #    Nếu không, .get() trả None và batch.update() sẽ ghi None đè lên
        #    dữ liệu thật của clone (Tax, Unit, Image... bị rụng sau mỗi lần sync).
        source_data_map = {}
        for doc_id, product_dict in updated_originals:
            data_to_sync = {}
            for field in SYNC_FIELDS:
                value = product_dict.get(field)
                if value is None or value == "":
                    continue
                data_to_sync[field] = value
            source_data_map[str(doc_id)] = data_to_sync

        source_ids = set(source_data_map.keys())
        if not source_ids:
            return 0

        clones_to_update = []
        try:
            # Quét tất cả sản phẩm để tìm clones cần cập nhật
            all_docs = self.products_ref.stream()

            for doc in all_docs:
                clone_data = doc.to_dict()
                if not clone_data:
                    continue
                
                is_clone = self._coerce_bool(clone_data.get("isClone"), False)
                if not is_clone:
                    continue

                clone_source_id = str(clone_data.get("CloneSourceId", ""))
                if clone_source_id in source_ids:
                    original_data_to_sync = source_data_map[clone_source_id]
                    
                    # So sánh và xác định các trường thực sự thay đổi
                    updates = {}
                    for field, new_value in original_data_to_sync.items():
                        if clone_data.get(field) != new_value:
                            updates[field] = new_value
                    
                    # Nếu có thay đổi, đưa vào danh sách chờ cập nhật
                    if updates:
                        print(f"    📝 Chuẩn bị cập nhật clone {doc.id} với các trường: {list(updates.keys())}")

                        # ✅ Cập nhật NormalizedCode nếu Code thay đổi
                        if "Code" in updates and updates["Code"]:
                            updates["NormalizedCode"] = self._normalize_string(updates["Code"])

                        # ✅ Cập nhật NormalizedName nếu Name hoặc FullName thay đổi
                        if "Name" in updates and updates["Name"]:
                            updates["NormalizedName"] = self._normalize_string(updates["Name"])
                        elif "FullName" in updates and updates["FullName"]:
                            updates["NormalizedName"] = self._normalize_string(updates["FullName"])

                        updates["SyncTimestamp"] = datetime.utcnow().isoformat()
                        updates["ModifiedDate"] = datetime.utcnow().isoformat()
                        clones_to_update.append({"doc_id": doc.id, "updates": updates})

            if not clones_to_update:
                print("    ℹ️ Không có clone nào cần cập nhật từ các thay đổi của sản phẩm gốc.")
                return 0

            # Thực hiện cập nhật hàng loạt (batch update)
            BATCH_SIZE = 500
            updated_count = 0
            for i in range(0, len(clones_to_update), BATCH_SIZE):
                batch = db.batch()
                chunk = clones_to_update[i:i + BATCH_SIZE]
                for clone_update in chunk:
                    doc_ref = self.products_ref.document(clone_update["doc_id"])
                    batch.update(doc_ref, clone_update["updates"])
                batch.commit()
                updated_count += len(chunk)

            print(f"    ✅ Đã cập nhật thành công {updated_count} clones.")
            return updated_count

        except Exception as e:
            import traceback
            print(f"❌ Lỗi nghiêm trọng khi đồng bộ clones: {e}")
            traceback.print_exc()
            return 0

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

    def read_products_modified_since(self, since_timestamp: str, include_inactive: bool = True, include_deleted: bool = False) -> List[Dict]:
        """
        Đọc products đã được modified HOẶC created kể từ timestamp cho trước.
        Sử dụng Firestore query với điều kiện ModifiedDate > since_timestamp OR CreatedDate > since_timestamp.

        Args:
            since_timestamp: ISO 8601 timestamp string (e.g., "2024-01-15T10:30:00Z")
            include_inactive: Bao gồm products không active
            include_deleted: Bao gồm products đã xóa

        Returns:
            List of products modified or created since the given timestamp
        """
        print(f"🔄 read_products_modified_since (since={since_timestamp})")

        try:
            # Parse timestamp
            from datetime import datetime
            if isinstance(since_timestamp, str):
                # Handle ISO 8601 format
                since_dt = parse_date(since_timestamp)
            else:
                since_dt = since_timestamp

            since_iso = since_dt.isoformat()

            # ✅ FIX: Query BOTH ModifiedDate AND CreatedDate
            # Firestore không hỗ trợ OR query, nên chạy 2 queries và merge
            result_map = {}  # Use dict to dedupe by Id

            # Query 1: Products modified since timestamp
            print(f"  📥 Query 1: ModifiedDate > {since_iso}")
            query_modified = self.products_ref.where("ModifiedDate", ">", since_iso)
            for doc in query_modified.stream():
                data = doc.to_dict() or {}
                product_id = data.get("Id")
                if product_id and product_id not in result_map:
                    result_map[product_id] = data
            print(f"  ✅ Query 1 found {len(result_map)} products")

            # Query 2: Products created since timestamp (for new products)
            print(f"  📥 Query 2: CreatedDate > {since_iso}")
            query_created = self.products_ref.where("CreatedDate", ">", since_iso)
            created_count = 0
            for doc in query_created.stream():
                data = doc.to_dict() or {}
                product_id = data.get("Id")
                if product_id and product_id not in result_map:
                    result_map[product_id] = data
                    created_count += 1
            print(f"  ✅ Query 2 found {created_count} additional products")

            # Filter by isActive and isDeleted
            result = []
            for data in result_map.values():
                is_active = self._coerce_bool(data.get("isActive"), True)
                is_deleted = self._coerce_bool(data.get("isDeleted"), False)

                if (not include_inactive) and (not is_active):
                    continue
                if (not include_deleted) and is_deleted:
                    continue

                result.append(dict(data))

            print(f"✅ Found {len(result)} products modified/created since {since_timestamp}")
            return result

        except Exception as e:
            print(f"❌ Error reading products modified since {since_timestamp}: {e}")
            return []

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

    # ======================== DatHang Hybrid APIs ========================

    def read_products_by_category(self, category_id: int, include_inactive: bool = False) -> List[Dict]:
        """
        Lay products theo CategoryId tu Firestore.
        Dung cho DatHang app: click category -> load san pham category do.
        Loc bo clones va deleted products.
        """
        cache_key = f"products_by_category:{category_id}:inactive={include_inactive}"
        if self.cache.has(cache_key):
            return self.cache.get(cache_key)

        docs = self.products_ref.where("CategoryId", "==", category_id).stream()
        result = []
        for doc in docs:
            data = doc.to_dict() or {}
            is_deleted = self._coerce_bool(data.get("isDeleted"), False)
            is_active = self._coerce_bool(data.get("isActive"), True)
            is_clone = self._coerce_bool(data.get("isClone"), False)

            if is_deleted:
                continue
            if not include_inactive and not is_active:
                continue
            if is_clone:
                continue
            # Fallback clone detection: OnHandNV > 0 and OnHand == 0
            if (data.get("OnHandNV") or 0) > 0 and (data.get("OnHand") or 0) == 0:
                continue

            result.append(dict(data))

        self.cache.set(cache_key, result, ttl=CACHE_TTL)
        return result

    def search_products(self, query: str, limit: int = 80) -> List[Dict]:
        """
        Tim kiem san pham theo ten/code.
        Server-side search cho DatHang app.
        Dung NormalizedName de tim kiem khong dau.
        """
        if not query or not query.strip():
            return []

        # Normalize query
        normalized_query = self._normalize_string(query.strip()).upper()
        tokens = normalized_query.split("_")
        tokens = [t for t in tokens if t]  # Remove empty tokens

        if not tokens:
            return []

        # Read all products (cached) and filter in-memory
        # Firestore khong ho tro full-text search, nen phai filter sau khi doc
        all_products = self.read_all_products(include_inactive=False, include_deleted=False)

        results = []
        for product in all_products:
            # Skip clones
            is_clone = self._coerce_bool(product.get("isClone"), False)
            if is_clone:
                continue
            if (product.get("OnHandNV") or 0) > 0 and (product.get("OnHand") or 0) == 0:
                continue

            name = (product.get("NormalizedName") or product.get("Name") or "").upper()
            code = (product.get("NormalizedCode") or product.get("Code") or "").upper()

            if all(token in name or token in code for token in tokens):
                results.append(product)
                if len(results) >= limit:
                    break

        return results

    def get_featured_products(self) -> List[Dict]:
        """
        Lay tat ca san pham (non-clone, active) sort theo CreatedDate desc.
        Dung cho DatHang app: hien thi khi vao trang, phan trang o route level.
        Dung read_all_products (co cache 300s) roi sort/filter trong Python.
        Khong dung Firestore order_by("CreatedDate") vi docs co CreatedDate=null
        se bi Firestore loai khoi ket qua query.
        """
        cache_key = "featured_products:all"
        if self.cache.has(cache_key):
            return self.cache.get(cache_key)

        # Reuse cached read_all_products (already filters inactive/deleted)
        all_products = self.read_all_products(include_inactive=False, include_deleted=False)

        # Filter out clones
        filtered = []
        for data in all_products:
            is_clone = self._coerce_bool(data.get("isClone"), False)
            if is_clone:
                continue
            # Fallback clone detection
            if (data.get("OnHandNV") or 0) > 0 and (data.get("OnHand") or 0) == 0:
                continue
            filtered.append(data)

        # Sort by CreatedDate descending (None/missing goes to end)
        def _sort_key(p):
            cd = p.get("CreatedDate")
            if cd is None:
                return ""
            return str(cd)

        filtered.sort(key=_sort_key, reverse=True)

        self.cache.set(cache_key, filtered, ttl=CACHE_TTL)
        return filtered

    def invalidate_all_product_caches(self):
        """Invalidate tất cả các cache keys liên quan đến products.
        CHỈ dùng cho: KiotViet full sync, explicit refresh, cleanup batch."""
        cache_keys_to_invalidate = [
            "all_products",
            "all_products:inactive=False:deleted=False",
            "all_products:inactive=True:deleted=False",
            "all_products:inactive=False:deleted=True",
            "all_products:inactive=True:deleted=True",
            "clone_stock_map",
        ]

        for key in cache_keys_to_invalidate:
            self.cache.invalidate(key)

        # Invalidate dynamic cache keys (featured_products:*, products_by_category:*)
        self.cache.invalidate_prefix("featured_products:")
        self.cache.invalidate_prefix("products_by_category:")

        print(f"🗑️ Invalidated ALL product cache keys")

    def _smart_invalidate_product(self, product_id, updated_data=None, category_id=None, is_delete=False, affects_stock=False):
        """Smart invalidation: cập nhật cache in-place thay vì xóa toàn bộ.
        Tránh full collection scan (15k reads) mỗi khi update 1 product.

        Args:
            product_id: ID của product
            updated_data: Dict chứa dữ liệu đã update (dùng để patch cache)
            category_id: CategoryId nếu biết (để invalidate cache category cụ thể)
            is_delete: True nếu product bị xóa
            affects_stock: True nếu OnHand/OnHandNV thay đổi
        """
        product_id_str = str(product_id)

        # 1. Invalidate single product cache
        self.cache.invalidate(product_id_str)

        # 2. Patch all_products lists in-place (thay vì invalidate → re-fetch 15k docs)
        if is_delete:
            self.cache.remove_item_from_lists("all_products", "Id", product_id)
        elif updated_data:
            self.cache.update_item_in_lists("all_products", "Id", product_id, updated_data)

        # 3. Invalidate category cache chỉ cho category liên quan
        if category_id:
            self.cache.invalidate(f"products_by_category:{category_id}:inactive=False")
            self.cache.invalidate(f"products_by_category:{category_id}:inactive=True")
        else:
            # Không biết category → invalidate all category caches
            self.cache.invalidate_prefix("products_by_category:")

        # 4. Clone stock map chỉ invalidate khi stock thay đổi
        if affects_stock:
            self.cache.invalidate("clone_stock_map")

        # 5. Featured products chỉ invalidate khi add/delete (thay đổi danh sách)
        if is_delete:
            self.cache.invalidate_prefix("featured_products:")