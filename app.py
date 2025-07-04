from flask import Flask, jsonify, request,send_from_directory
import os
from unidecode import unidecode
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# KiotViet Dependencies
from FromKiotViet.get_entire_product import get_all as get_all_products_from_kiotviet
from Utility.get_env import LatestBranchId, retailer
from FromKiotViet.get_all_product_by_category import get_items_category, get_items_out_of_stock
from FromKiotViet.get_category import get_category
from FromKiotViet.get_one_product import get_item
from FromKiotViet.get_all_customer import get_entire_customer
from FromKiotViet.get_authorization import auth_token

# Firebase Dependencies
from firebase.firebase_service.cache import Cache
from firebase.firebase_service.product_service import FirestoreProductService
from firebase.firebase_service.invoice_service import FirestoreInvoiceService
from firebase.firebase_service.customer_service import FirestoreCustomerService
from firebase.firebase_service.order_service import FirestoreorderService
# Data Sync Dependencies
from firebase.firebase_khachhang.import_to_firestore import update_customer_from_kiotviet_to_firestore
from firebase.firebase_hanghoa.import_to_firestore import update_products_from_banhang_app_to_firestore, update_products_from_kiotviet_to_firestore
from firebase.firebase_hoadon.import_to_firestore import update_invoices_from_banhang_app_to_firestore

app = Flask(__name__)
CORS(app, origins="*")

# Initialize Firebase Services
firebase_service_product = FirestoreProductService(Cache())
firebase_service_invoice = FirestoreInvoiceService(Cache())
firebase_service_customer = FirestoreCustomerService(Cache())
firebase_service_order = FirestoreorderService(Cache())

# Khởi tạo SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

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
        # Get username and password from request body
        data = request.get_json()
        if not data or 'username' not in data or 'password' not in data:
            return jsonify({"status": "error", "message": "Username and password are required"}), 400
        
        username = data['username']
        password = data['password']
        
        # Import the authentication function
        from FromKiotViet.get_authorization import get_authen as kiotviet_auth
        
        # Call the authentication function with provided credentials
        auth_url = "https://api-man1.kiotviet.vn/api/account/login?quan-ly=true"
        body = {
            "model": {
                "RememberMe": "true",
                "ShowCaptcha": "false",
                "UserName": username,
                "Password": password,
                "Language": "vi-VN",
                "LatestBranchId": LatestBranchId
            },
            "IsManageSide": "true",
            "FingerPrintKey": "211d1f5bb8cc08a94863d2291f1c866d_Chrome_Desktop_Máy tính Windows"
        }
        params = {"quan-ly": "true"}
        headers = {
            "retailer": retailer
        }
        
        import requests
        response = requests.post(auth_url, json=body, headers=headers, params=params)
        
        if response.status_code == 200:
            token_data = response.json().get("token", "")
            if token_data:
                auth_token = "Bearer " + token_data
                auth_data = {"retailer": retailer, "LatestBranchId": LatestBranchId, "access_token": auth_token}
                return jsonify(auth_data), 200
            else:
                return jsonify({"status": "error", "message": "Invalid credentials"}), 401
        else:
            return jsonify({"status": "error", "message": "Authentication failed"}), 401
            
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
    
@app.route('/api/kiotviet/items/out_of_stock', methods=['GET'])
def get_items_out_of_stock():
    try:
        all_items = get_all_products_from_kiotviet()
        # Lọc các sản phẩm master (MasterUnitId == None), OnHand < 10, không bị xóa và đang hoạt động
        out_of_stock_items = [
            {
                "Code": item.get("Code"),
                "Image": item.get("Image"),
                "FullName": item.get("FullName"),
                "Cost": item.get("Cost"),
                "BasePrice": item.get("BasePrice"),
                "OnHand": item.get("OnHand")
            }
            for item in all_items
            if (
                (item.get("MasterUnitId") is None)
                and (item.get("OnHand", 0) < 10)
                and (not item.get("isDeleted", False))
                and (item.get("isActive", True))
            )
        ]
        return jsonify(out_of_stock_items)
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

@app.route("/api/firebase/get/customers", methods=["GET"])
def get_all_customers():
    return jsonify(firebase_service_customer.read_all_customers())

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

@app.route("/api/firebase/products/update_onhand_batch", methods=["PUT"])
def update_onhand_from_invoice():
    invoice_obj = request.json
    result = update_products_from_banhang_app_to_firestore(invoice_obj)
    # Phát WebSocket cho client khác nếu muốn
    for p in result.get('updated_products', []):
        notify_product_onhand_updated(p['Id'], p['new_OnHand'])
    return jsonify(result)


@app.route("/api/firebase/get/products", methods=["GET"])
def get_all_products():
    return jsonify(firebase_service_product.read_all_products())

@app.route("/api/firebase/get/grouped_products", methods=["GET"])
def get_grouped_products():
    grouped = firebase_service_product.group_product()
    return jsonify(grouped)

@app.route("/api/firebase/get/products/<product_id>", methods=["GET"])
def get_product(product_id):
    product = firebase_service_product.read_product(product_id)
    if product:
        return jsonify(product)
    return jsonify({"error": "Product not found"}), 404

@app.route("/api/firebase/add/product", methods=["POST"])
def add_product():
    product = request.json
    return jsonify(firebase_service_product.add_product(product))

@app.route("/api/firebase/update/products", methods=["PUT"])
def update_product():
    products = request.json  # [{Id:..., OnHand:...}, ...]
    results = []
    for prod in products:
        product_id = str(prod["Id"])
        updates = {"OnHand": prod["OnHand"]}
        result = firebase_service_product.update_product(product_id, updates)
        results.append({ "id": product_id, "result": result })
    return jsonify({"message": f"Updated {len(products)} products", "results": results})

@app.route("/api/firebase/products/del/<product_id>", methods=["DELETE"])
def delete_product(product_id):
    return jsonify(firebase_service_product.delete_product(product_id))

@app.route("/api/firebase/update/products/batch", methods=["PUT"])
def update_products_batch():
    products_dict = request.json  # Nhận dict từ frontend
    result = firebase_service_product.update_products(products_dict)
    return jsonify(result)


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
    result = firebase_service_invoice.add_invoice(invoice)
    notify_invoice_created(invoice)  # Phát sự kiện cho client
    return jsonify(result)

@app.route("/api/firebase/invoices/<invoice_id>", methods=["PUT"])
def update_invoice(invoice_id):
    updates = request.json
    result = firebase_service_invoice.update_invoice(invoice_id, updates)
    # Lấy lại hóa đơn đã cập nhật để gửi cho client
    updated_invoice = firebase_service_invoice.read_invoice(invoice_id)
    if updated_invoice:
        notify_invoice_updated(updated_invoice)
    return jsonify(result)


@app.route("/api/firebase/invoices/<invoice_id>", methods=["DELETE"])
def delete_invoice(invoice_id):
    result = firebase_service_invoice.delete_invoice(invoice_id)
    notify_invoice_deleted(invoice_id)
    return jsonify(result)

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
        invoices = firebase_service_invoice.get_invoices_by_date(date)
        revenue = 0
        cost = 0
        for invoice in invoices:
            cart_items = invoice.get('cartItems', [])
            for item in cart_items:
                product = item.get('product', {})
                quantity = item.get('quantity', 0)
                price = item.get('price', product.get('BasePrice', 0))
                cost_price = product.get('Cost', 0)
                revenue += price * quantity
                cost += cost_price * quantity
        profit = revenue - cost
        return jsonify({
            'buyer_quantity': len(invoices),
            'date': date,
            'revenue': revenue,
            'cost': cost,
            'profit': profit
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/monthly_summary", methods=["GET"])
def get_monthly_summary():
    year = request.args.get('year')
    month = request.args.get('month')
    if not year or not month:
        return jsonify({"status": "error", "message": "year and month are required"}), 400
    try:
        from calendar import monthrange
        days_in_month = monthrange(int(year), int(month))[1]
        revenue = 0
        cost = 0
        total_invoices = 0
        for day in range(1, days_in_month + 1):
            date_str = f"{year}-{str(month).zfill(2)}-{str(day).zfill(2)}"
            invoices = firebase_service_invoice.get_invoices_by_date(date_str)
            total_invoices += len(invoices)
            for invoice in invoices:
                cart_items = invoice.get('cartItems', [])
                for item in cart_items:
                    product = item.get('product', {})
                    quantity = item.get('quantity', 0)
                    price = item.get('price', product.get('BasePrice', 0))
                    cost_price = product.get('Cost', 0)
                    revenue += price * quantity
                    cost += cost_price * quantity
        profit = revenue - cost
        return jsonify({
            'buyer_quantity': total_invoices,
            'month': f"{year}-{str(month).zfill(2)}",
            'revenue': revenue,
            'cost': cost,
            'profit': profit
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/yearly_summary", methods=["GET"])
def get_yearly_summary():
    year = request.args.get('year')
    if not year:
        return jsonify({"status": "error", "message": "year is required"}), 400
    try:
        revenue = 0
        cost = 0
        total_invoices = 0
        from calendar import monthrange
        for m in range(1, 13):
            days_in_month = monthrange(int(year), m)[1]
            for day in range(1, days_in_month + 1):
                date_str = f"{year}-{str(m).zfill(2)}-{str(day).zfill(2)}"
                invoices = firebase_service_invoice.get_invoices_by_date(date_str)
                total_invoices += len(invoices)
                for invoice in invoices:
                    cart_items = invoice.get('cartItems', [])
                    for item in cart_items:
                        product = item.get('product', {})
                        quantity = item.get('quantity', 0)
                        price = item.get('price', product.get('BasePrice', 0))
                        cost_price = product.get('Cost', 0)
                        revenue += price * quantity
                        cost += cost_price * quantity
        profit = revenue - cost
        return jsonify({
            'buyer_quantity': total_invoices,
            'year': year,
            'revenue': revenue,
            'cost': cost,
            'profit': profit
        })
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
                product_name = product.get('FullName', 'Unknown')
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

def notify_product_onhand_updated(product_id, onHand):
    socketio.emit('product_onhand_updated', {'productId': product_id, 'onHand': onHand}, namespace='/api/websocket/products')
# WebSocket endpoint cho invoices



@socketio.on('connect', namespace='/api/websocket/invoices')
def handle_connect():
    print('Client connected to invoices websocket')
    emit('message', {'data': 'Connected to invoices WebSocket'})

@socketio.on('disconnect', namespace='/api/websocket/invoices')
def handle_disconnect():
    print('Client disconnected from invoices websocket')

def notify_invoice_updated(invoice):
    socketio.emit('invoice_updated', {'data': invoice}, namespace='/api/websocket/invoices')

def notify_invoice_deleted(invoice_id):
    socketio.emit('invoice_deleted', {'data': invoice_id}, namespace='/api/websocket/invoices')
# Gửi dữ liệu hóa đơn mới cho tất cả client
def notify_invoice_created(invoice):
    socketio.emit('invoice_created', {'data': invoice}, namespace='/api/websocket/invoices')
    
    
    
    
#-------------------------------order---------------------------------------
@app.route("/api/firebase/orders", methods=["GET"])
def get_all_orders():
    try:
        orders = firebase_service_order.read_all_orders()
        return jsonify(orders)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/orders/<order_id>", methods=["GET"])
def get_order_by_id(order_id):
    try:
        order = firebase_service_order.read_order(order_id)
        if order:
            return jsonify(order)
        return jsonify({"status": "error", "message": "Order not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/firebase/add_order", methods=["POST"])
def add_order():
    order = request.json
    result = firebase_service_order.add_order(order)
    notify_order_created(order)  # Phát sự kiện cho client
    return jsonify(result)

@app.route("/api/firebase/update_order/<order_id>", methods=["PUT"])
def update_order(order_id):
    updates = request.json
    result = firebase_service_order.update_order(order_id, updates)
    updated_order = firebase_service_order.read_order(order_id)
    if updated_order:
        notify_order_updated(updated_order)
    return jsonify(result)

@app.route("/api/firebase/orders/<order_id>", methods=["DELETE"])
def delete_order(order_id):
    result = firebase_service_order.delete_order(order_id)
    notify_order_deleted(order_id)
    return jsonify(result)

@app.route("/api/firebase/orders/date", methods=["GET"])
def get_orders_by_date():
    try:
        date = request.args.get('date')
        if not date:
            return jsonify({"status": "error", "message": "date is required"}), 400
        orders = firebase_service_order.get_orders_by_date(date)
        return jsonify(orders)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
@socketio.on('connect', namespace='/api/websocket/orders')
def handle_order_connect():
    print('Client connected to orders websocket')
    emit('message', {'data': 'Connected to orders WebSocket'})

@socketio.on('disconnect', namespace='/api/websocket/orders')
def handle_order_disconnect():
    print('Client disconnected from orders websocket')

def notify_order_created(order):
    socketio.emit('order_created', {'data': order}, namespace='/api/websocket/orders')

def notify_order_updated(order):
    socketio.emit('order_updated', {'data': order}, namespace='/api/websocket/orders')

def notify_order_deleted(order_id):
    socketio.emit('order_deleted', {'data': order_id}, namespace='/api/websocket/orders')

if __name__ == "__main__":
    env = os.getenv("e", "prod")
    port = 8000 if env == "prod" else 5000
    print(f"Running in {env.upper()} mode on port {port}")
    socketio.run(app, host='0.0.0.0', port=port)
      