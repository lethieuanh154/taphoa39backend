
from firebase.init_firebase import init_firestore

# Cloud Firestore (nguồn)
db_products_cloud = init_firestore("FIREBASE_SERVICE_ACCOUNT_HANGHOA", app_name="hanghoa_app")
db_invoices_cloud = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON", app_name="hoadon_app")
# Local Firestore (đích)
db_local = init_firestore("FIREBASE_SERVICE_ACCOUNT_LOCAL", app_name="local_app")

def download_all_products():
    products_ref = db_products_cloud.collection("products")
    docs = products_ref.stream()
    products = [doc.to_dict() | {"id": doc.id} for doc in docs]
    return products

def download_all_invoices():
    invoices_ref = db_invoices_cloud.collection("invoices")
    docs = invoices_ref.stream()
    invoices = [doc.to_dict() | {"id": doc.id} for doc in docs]
    return invoices

def save_to_local_firestore(collection_name, items):
    batch = db_local.batch()
    for item in items:
        doc_id = str(item.get("id"))
        doc_ref = db_local.collection(collection_name).document(doc_id)
        batch.set(doc_ref, item)
    batch.commit()

if __name__ == "__main__":
    products = download_all_products()
    invoices = download_all_invoices()
    print(f"Tổng số sản phẩm: {len(products)}")
    print(f"Tổng số hóa đơn: {len(invoices)}")
    save_to_local_firestore("products", products)
    save_to_local_firestore("invoices", invoices)
    print("Đã lưu dữ liệu vào Firestore local!")