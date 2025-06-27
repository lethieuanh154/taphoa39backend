from flask import Flask, jsonify, request,send_from_directory
import os
from unidecode import unidecode
from flask_cors import CORS

# KiotViet Dependencies
from FromKiotViet.get_entire_product import get_all as get_all_products_from_kiotviet
from Utility.get_env import LatestBranchId, retailer
from FromKiotViet.get_all_product_by_category import get_items_category
from FromKiotViet.get_category import get_category
from FromKiotViet.get_one_product import get_item
from FromKiotViet.get_all_customer import get_entire_customer
from FromKiotViet.get_authorization import auth_token

# Firebase Dependencies
from firebase.firebase_service.cache import Cache
from firebase.firebase_service.product_service import FirestoreProductService
from firebase.firebase_service.invoice_service import FirestoreInvoiceService
from firebase.firebase_service.customer_service import FirestoreCustomerService

# Data Sync Dependencies
from firebase.firebase_khachhang.import_to_firestore import update_customer_from_kiotviet_to_firestore
from firebase.firebase_hanghoa.import_to_firestore import update_products_from_kiotviet_to_firestore
from firebase.firebase_hoadon.import_to_firestore import update_invoices_from_banhang_app_to_firestore

app = Flask(__name__)
CORS(app, origins="*")

# Initialize Firebase Services
firebase_service_product = FirestoreProductService(Cache())
firebase_service_invoice = FirestoreInvoiceService(Cache())
firebase_service_customer = FirestoreCustomerService(Cache())


# === Static Files and Index ===
@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:path>")
def serve_static_files(path):
    if os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")

# ============================
# === KiotViet API Routes ====
# ============================

@app.route('/api/kiotviet/authentication', methods=['POST'])
def get_authen():
    try:
        if auth_token:
            auth_data = {"retailer": retailer, "LatestBranchId": LatestBranchId, "access_token": auth_token}
            return jsonify(auth_data), 200
        else:
            return jsonify({"status": "error", "message": "Authentication token not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/kiotviet/item/<term>', methods=['GET'])
def get_item_by_term_from_kiotviet(term):
    try:
        product_detail = get_item(term)
        if product_detail:
            return jsonify(product_detail), 200
        else:
            return jsonify({"status": "error", "message": f"Product not found with term: {term}"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/kiotviet/items/all', methods=['GET'])
def get_all_items_from_kiotviet():
    try:
        all_items = get_all_products_from_kiotviet()
        return jsonify(all_items)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/kiotviet/categories', methods=['GET'])
def get_categories_from_kiotviet():
    try:
        categories = get_category()
        return jsonify(categories)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/kiotviet/items/category/<category_name>', methods=['GET'])
def get_items_by_category_from_kiotviet(category_name):
    try:
        categories = get_category()
        category_id = None
        for cat in categories:
            if unidecode(cat["Path"]).lower() == unidecode(category_name).lower():
                category_id = cat["Id"]
                break
        if not category_id:
            return jsonify({"status": "error", "message": f"Category not found: {category_name}"}), 404
        items = get_items_category(category_id)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/kiotviet/customers", methods=["GET"])
def get_all_customers_from_kiotviet():
    try:
        customers = get_entire_customer()
        return jsonify(customers)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================
# === Data Sync API Routes ===
# ============================

@app.route("/api/sync/kiotviet/firebase/customers", methods=["PUT"])
def sync_customers_from_kiotviet():
    return jsonify(update_customer_from_kiotviet_to_firestore())

@app.route("/api/sync/kiotviet/firebase/products", methods=["PUT"])
def sync_products_from_kiotviet():
    return jsonify(update_products_from_kiotviet_to_firestore())

# ============================
# ==== Firebase API Routes ===
# ============================

# --- Product CRUD ---
@app.route("/api/firebase/products", methods=["GET"])
def get_all_products():
    return jsonify(firebase_service_product.read_all_products())

@app.route("/api/firebase/products/<product_id>", methods=["GET"])
def get_product(product_id):
    product = firebase_service_product.read_product(product_id)
    if product:
        return jsonify(product)
    return jsonify({"error": "Product not found"}), 404

@app.route("/api/firebase/products", methods=["POST"])
def add_product():
    product = request.json
    return jsonify(firebase_service_product.add_product(product))

@app.route("/api/firebase/products/<product_id>", methods=["PUT"])
def update_product(product_id):
    updates = request.json
    return jsonify(firebase_service_product.update_product(product_id, updates))

@app.route("/api/firebase/products/<product_id>", methods=["DELETE"])
def delete_product(product_id):
    return jsonify(firebase_service_product.delete_product(product_id))

# --- Invoice CRUD & Queries ---
@app.route("/api/firebase/all_invoices", methods=["GET"])
def get_all_invoices():
    try:
        invoices = firebase_service_invoice.read_all_invoices()
        return jsonify(invoices)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/invoices/<invoice_id>", methods=["GET"])
def get_invoice_by_id(invoice_id):
    try:
        invoice = firebase_service_invoice.read_invoice(invoice_id)
        if invoice:
            return jsonify(invoice)
        return jsonify({"status": "error", "message": "Invoice not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route("/api/firebase/add_invoice", methods=["POST"])
def add_invoice():
    invoice = request.json
    return jsonify(firebase_service_invoice.add_invoice(invoice))

@app.route("/api/firebase/invoices/<invoice_id>", methods=["PUT"])
def update_invoice(invoice_id):
    updates = request.json
    return jsonify(firebase_service_invoice.update_invoice(invoice_id, updates))

@app.route("/api/firebase/invoices/<invoice_id>", methods=["DELETE"])
def delete_invoice(invoice_id):
    return jsonify(firebase_service_invoice.delete_invoice(invoice_id))

@app.route("/api/firebase/invoices/date", methods=["GET"])
def get_invoices_by_date():
    try:
        date = request.args.get('date')
       
        if not date:
            return jsonify({"status": "error", "message": "date is required"}), 400
        invoices = firebase_service_invoice.get_invoices_by_date(date)
        return jsonify(invoices)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/invoices/status/<status>", methods=["GET"])
def get_invoices_by_status(status):
    try:
        invoices = firebase_service_invoice.get_invoices_by_status(status)
        return jsonify(invoices)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/invoices/customer/<customer_id>", methods=["GET"])
def get_invoices_by_customer(customer_id):
    try:
        invoices = firebase_service_invoice.get_invoices_by_customer(customer_id)
        return jsonify(invoices)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/add_customer", methods=["POST"])
def add_customer():
    customer = request.json
    return jsonify(firebase_service_customer.add_customer(customer))

@app.route("/api/firebase/add_customers", methods=["POST"])
def add_customers():
    customers = request.json  # Nhận 1 list các customer
    return jsonify(firebase_service_customer.add_customers(customers))

@app.route("/api/firebase/daily_summary", methods=["GET"])
def get_daily_summary():
    date = request.args.get('date')
    if not date:
        return jsonify({"status": "error", "message": "date is required (YYYY-MM-DD)"}), 400
    try:
        summary = firebase_service_invoice.get_daily_summary(date)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/monthly_summary", methods=["GET"])
def get_monthly_summary():
    year = request.args.get('year')
    month = request.args.get('month')
    if not year or not month:
        return jsonify({"status": "error", "message": "year and month are required"}), 400
    try:
        summary = firebase_service_invoice.get_monthly_summary(year, month)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/yearly_summary", methods=["GET"])
def get_yearly_summary():
    year = request.args.get('year')
    if not year:
        return jsonify({"status": "error", "message": "year is required"}), 400
    try:
        summary = firebase_service_invoice.get_yearly_summary(year)
        return jsonify(summary)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/top_products", methods=["GET"])
def get_top_products():
    try:
        date = request.args.get('date')
        year = request.args.get('year')
        month = request.args.get('month')
        # Lọc hóa đơn theo ngày/tháng/năm
        if date:
            invoices = firebase_service_invoice.get_invoices_by_date(date)
        elif year and month:
            from calendar import monthrange
            days_in_month = monthrange(int(year), int(month))[1]
            invoices = []
            for day in range(1, days_in_month + 1):
                date_str = f"{year}-{str(month).zfill(2)}-{str(day).zfill(2)}"
                invoices.extend(firebase_service_invoice.get_invoices_by_date(date_str))
        elif year:
            invoices = []
            for m in range(1, 13):
                from calendar import monthrange
                days_in_month = monthrange(int(year), m)[1]
                for day in range(1, days_in_month + 1):
                    date_str = f"{year}-{str(m).zfill(2)}-{str(day).zfill(2)}"
                    invoices.extend(firebase_service_invoice.get_invoices_by_date(date_str))
        else:
            invoices = firebase_service_invoice.read_all_invoices()
        product_sales = {}
        for invoice in invoices:
            cart_items = invoice.get('cartItems', [])
            for item in cart_items:
                product = item.get('product', {})
                product_id = product.get('Id')
                product_name = product.get('Name', 'Unknown')
                price = item.get('price', product.get('BasePrice', 0))
                quantity = item.get('quantity', 0)
                total_price = price * quantity
                if product_id is not None:
                    if product_id not in product_sales:
                        product_sales[product_id] = {
                            'productId': product_id,
                            'productName': product_name,
                            'totalRevenue': 0,
                            'totalQuantity': 0
                        }
                    product_sales[product_id]['totalRevenue'] += total_price
                    product_sales[product_id]['totalQuantity'] += quantity
        # Sắp xếp theo doanh thu giảm dần và lấy top 20
        top_products = sorted(product_sales.values(), key=lambda x: x['totalRevenue'], reverse=True)[:20]
        return jsonify(top_products)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ============================
# ===== App Entry Point ======
# ============================

if __name__ == "__main__":
    env = os.getenv("e", "prod")
    port = 8000 if env == "prod" else 5000
    print(f"Running in {env.upper()} mode on port {port}")
    app.run(host="0.0.0.0", port=port)
      