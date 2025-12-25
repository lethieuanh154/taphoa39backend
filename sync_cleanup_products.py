"""
Script để đồng bộ và dọn dẹp sản phẩm giữa KiotViet và Firebase.
Xóa các sản phẩm trong Firebase mà không còn tồn tại trong KiotViet.

Chạy: python sync_cleanup_products.py
"""

import time
from dotenv import load_dotenv

load_dotenv()

from FromKiotViet.get_entire_product import get_all as get_all_kiotviet_products
from firebase.firebase_service.product_service import db, COLLECTION_NAME


def get_firebase_product_ids():
    """Lấy tất cả product IDs từ Firebase."""
    print("📥 Đang lấy danh sách sản phẩm từ Firebase...")

    products_ref = db.collection(COLLECTION_NAME)
    docs = products_ref.stream()

    firebase_ids = set()
    for doc in docs:
        data = doc.to_dict() or {}
        product_id = data.get("Id") or data.get("id")
        if product_id:
            firebase_ids.add(str(product_id))

    print(f"✅ Firebase có {len(firebase_ids)} sản phẩm")
    return firebase_ids


def get_kiotviet_product_ids():
    """Lấy tất cả product IDs từ KiotViet (chỉ active, không deleted)."""
    print("📥 Đang lấy danh sách sản phẩm từ KiotViet...")

    products = get_all_kiotviet_products()
    if products is None:
        print("❌ Không thể lấy dữ liệu từ KiotViet API")
        return None

    kiotviet_ids = set()
    for product in products:
        product_id = product.get("Id") or product.get("id")
        if product_id:
            kiotviet_ids.add(str(product_id))

    print(f"✅ KiotViet có {len(kiotviet_ids)} sản phẩm (active)")
    return kiotviet_ids


def find_orphan_products(firebase_ids, kiotviet_ids):
    """Tìm các sản phẩm có trong Firebase nhưng không có trong KiotViet."""
    orphan_ids = firebase_ids - kiotviet_ids
    print(f"🔍 Tìm thấy {len(orphan_ids)} sản phẩm cần xóa (có trong Firebase, không có trong KiotViet)")
    return orphan_ids


def delete_orphan_products(orphan_ids, dry_run=True):
    """
    Xóa các sản phẩm orphan khỏi Firebase.

    Args:
        orphan_ids: Set các product IDs cần xóa
        dry_run: Nếu True, chỉ in ra danh sách mà không xóa thật
    """
    if not orphan_ids:
        print("✅ Không có sản phẩm nào cần xóa")
        return {"deleted": 0, "ids": []}

    products_ref = db.collection(COLLECTION_NAME)

    if dry_run:
        print(f"\n🔍 [DRY RUN] Danh sách {len(orphan_ids)} sản phẩm sẽ bị xóa:")
        for idx, product_id in enumerate(list(orphan_ids)[:20], 1):
            print(f"   {idx}. ID: {product_id}")
        if len(orphan_ids) > 20:
            print(f"   ... và {len(orphan_ids) - 20} sản phẩm khác")
        print("\n⚠️  Chạy lại với dry_run=False để xóa thật")
        return {"deleted": 0, "ids": list(orphan_ids), "dry_run": True}

    # Xóa thật - batch delete (max 500 per batch)
    print(f"\n🗑️  Đang xóa {len(orphan_ids)} sản phẩm khỏi Firebase...")

    BATCH_SIZE = 500
    deleted_count = 0
    orphan_list = list(orphan_ids)

    for i in range(0, len(orphan_list), BATCH_SIZE):
        batch = db.batch()
        batch_ids = orphan_list[i:i + BATCH_SIZE]

        for product_id in batch_ids:
            doc_ref = products_ref.document(str(product_id))
            batch.delete(doc_ref)

        batch.commit()
        deleted_count += len(batch_ids)
        print(f"   📦 Đã xóa batch {i // BATCH_SIZE + 1}: {len(batch_ids)} sản phẩm (tổng: {deleted_count})")

    print(f"✅ Đã xóa {deleted_count} sản phẩm khỏi Firebase")
    return {"deleted": deleted_count, "ids": orphan_list}


def sync_cleanup(dry_run=True):
    """
    Thực hiện đồng bộ và dọn dẹp sản phẩm.

    Args:
        dry_run: Nếu True, chỉ kiểm tra và in ra danh sách, không xóa thật
    """
    start_time = time.time()
    print("=" * 60)
    print("🔄 BẮT ĐẦU ĐỒNG BỘ VÀ DỌN DẸP SẢN PHẨM")
    print("=" * 60)

    # Bước 1: Lấy IDs từ cả hai nguồn
    firebase_ids = get_firebase_product_ids()
    kiotviet_ids = get_kiotviet_product_ids()

    if kiotviet_ids is None:
        print("❌ Không thể tiếp tục do lỗi kết nối KiotViet")
        return None

    # Bước 2: Tìm sản phẩm orphan
    orphan_ids = find_orphan_products(firebase_ids, kiotviet_ids)

    # Bước 3: Thống kê
    print("\n📊 THỐNG KÊ:")
    print(f"   - Sản phẩm trong Firebase: {len(firebase_ids)}")
    print(f"   - Sản phẩm trong KiotViet: {len(kiotviet_ids)}")
    print(f"   - Sản phẩm chung (OK): {len(firebase_ids & kiotviet_ids)}")
    print(f"   - Sản phẩm cần xóa: {len(orphan_ids)}")

    # Sản phẩm có trong KiotViet nhưng chưa có trong Firebase (nếu có)
    missing_in_firebase = kiotviet_ids - firebase_ids
    if missing_in_firebase:
        print(f"   - Sản phẩm thiếu trong Firebase: {len(missing_in_firebase)}")

    # Bước 4: Xóa sản phẩm orphan
    result = delete_orphan_products(orphan_ids, dry_run=dry_run)

    elapsed_time = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"✅ HOÀN TẤT trong {elapsed_time:.2f} giây")
    print("=" * 60)

    return {
        "firebase_count": len(firebase_ids),
        "kiotviet_count": len(kiotviet_ids),
        "orphan_count": len(orphan_ids),
        "deleted": result.get("deleted", 0),
        "dry_run": dry_run,
        "elapsed_seconds": round(elapsed_time, 2)
    }


if __name__ == "__main__":
    import sys

    # Mặc định là dry_run=True (an toàn)
    # Chạy với argument --execute để xóa thật
    dry_run = "--execute" not in sys.argv

    if dry_run:
        print("⚠️  Chế độ DRY RUN - Chỉ kiểm tra, không xóa thật")
        print("   Chạy với --execute để xóa thật: python sync_cleanup_products.py --execute\n")
    else:
        print("🚨 CHẾ ĐỘ EXECUTE - Sẽ xóa sản phẩm thật khỏi Firebase!\n")
        confirm = input("Bạn có chắc chắn muốn tiếp tục? (yes/no): ")
        if confirm.lower() != "yes":
            print("❌ Đã hủy thao tác")
            sys.exit(0)

    result = sync_cleanup(dry_run=dry_run)

    if result:
        print(f"\n📋 KẾT QUẢ: {result}")
