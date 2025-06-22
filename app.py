from flask import Flask, jsonify, request,send_from_directory
import os
import json
from unidecode import unidecode  # Thêm thư viện unidecode để loại bỏ dấu tiếng Việt
from flask_cors import CORS
from FromKiotViet.get_entire_product import get_all
from Utility.get_env import  LatestBranchId, retailer
from FromKiotViet.get_all_product_by_category import get_items_category
from FromKiotViet.get_category import get_category
from FromKiotViet.get_one_product import get_item
from FromKiotViet.get_all_customer import get_entire_customer
from FromKiotViet.get_authorization import auth_token

from firebase.firebase_service.cache import Cache
from firebase.firebase_service.get_product_service import FirestoreProductService
from firebase.firebase_khachhang.import_to_firestore import update_customer_from_kiotviet_to_firestore
from firebase.firebase_hanghoa.import_to_firestore import update_products_from_banhang_app_to_firestore, update_products_from_kiotviet_to_firestore
from firebase.firebase_hoadon.import_to_firestore import update_invoices_from_banhang_app_to_firestore

app = Flask(__name__)
CORS(app,origins="*") 
firebase_service = FirestoreProductService(Cache())

@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:path>")
def serve_static_files(path):
    if os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")
    
    
    #---------------kiot viet-------start------------------------
@app.route('/api/authentication', methods=['POST'])
def get_authen():
    try:
        if auth_token:
            au={"retailer":retailer,"LatestBranchId":LatestBranchId,"access_token":auth_token, }

            return jsonify(au), 200
        else:
            return jsonify({"status": "error", "message": f"Không tìm thấy sản phẩm với authen: {auth_token}"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
@app.route('/api/item/<term>', methods=['GET'])
def get_item_by_term(term):
    """
    API trả về thông tin chi tiết của sản phẩm dựa trên term.
    """
    try:
        product_detail = get_item(term)
        if product_detail:
            return jsonify(product_detail), 200
        else:
            return jsonify({"status": "error", "message": f"Không tìm thấy sản phẩm với term: {term}"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
@app.route('/api/kiotviet/items/all', methods=['GET'])
def get_all_items():
    all_items = []
    try:
        # Duyệt qua tất cả các file JSON trong thư mục
        all_items=get_all()
        return jsonify(all_items)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/categories', methods=['GET'])
def get_categories():
    
    try:
        categories = get_category()  # Hàm từ get_category.py

        return jsonify(categories)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
@app.route('/api/items/<category>', methods=['GET'])
def get_items_by_category(category):
    """
    API trả về danh sách sản phẩm theo tên danh mục.
    """
    try:
        # Gọi API /api/categories để lấy danh sách danh mục
        categories = get_category()  # Hàm từ get_category.py

        # Tìm CategoryId dựa trên tên danh mục
        category_id = None
        for cat in categories:
            if unidecode(cat["Path"]).lower() == unidecode(category).lower():
                category_id = cat["Id"]
                break

        if not category_id:
            return jsonify({"status": "error", "message": f"Không tìm thấy danh mục: {category}"}), 404

        # Gọi hàm get_items_category để lấy danh sách sản phẩm theo CategoryId
        items = get_items_category(category_id)
        return jsonify(items), 200

    except Exception as e:
        app.logger.error(f"Lỗi khi lấy sản phẩm theo danh mục {category}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    
@app.route("/api/customers", methods=["GET"])
def get_all_customer():
    try:
        customers = get_entire_customer()  # Hàm từ get_category.py
        return jsonify(customers)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

#---------------kiot viet----------end---------------------






# #---------------firebase-data----------start---------------------
# # firebase crud product
# @app.route("/firebase/products", methods=["GET"])
# def get_all_products():
#     return jsonify(firebase_service.read_all_products())

# @app.route("/firebase/products/<product_id>", methods=["GET"])
# def get_product(product_id):
#     product = firebase_service.read_product(product_id)
#     if product:
#         return jsonify(product)
#     return jsonify({"error": "Not found"}), 404

# @app.route("/firebase/products", methods=["POST"])
# def add_product():
#     product = request.json
#     return jsonify(firebase_service.add_product(product))

# @app.route("/firebase/products/<product_id>", methods=["PUT"])
# def update_product(product_id):
#     updates = request.json
#     return jsonify(firebase_service.update_product(product_id, updates))

# @app.route("/firebase/products/<product_id>", methods=["DELETE"])
# def delete_product(product_id):
#     return jsonify(firebase_service.delete_product(product_id))

# #kiotviet
# @app.route("/kiotviet/firebase/customers", methods=["PUT"])
# def update_customer_from_kiotviet():
#     return jsonify(update_customer_from_kiotviet_to_firestore())

# @app.route("/kiotviet/firebase/products", methods=["PUT"])
# def update_products_from_kiotviet():
#     return jsonify(update_products_from_kiotviet_to_firestore())
# #---------------firebase-data----------end---------------------










#banhang app
@app.route("/api/firebase/invoices", methods=["POST"])
def update_invoices_to_firebase():
    invoices = request.json
    invoices_result = update_invoices_from_banhang_app_to_firestore(invoices)
    # products_result = update_products_from_banhang_app_to_firestore(invoices)
    return jsonify({
        "invoices_result": invoices_result
        # "products_result": products_result
    })

# Get all invoices
@app.route("/api/firebase/get_invoices", methods=["GET"])
def get_all_invoices():
    try:
        from firebase.firebase_hoadon.get_hoadon_from_firestore import get_all_invoices
        invoices = get_all_invoices()
        return jsonify(invoices)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Get invoice by ID
@app.route("/api/firebase/invoices/<invoice_id>", methods=["GET"])
def get_invoice_by_id(invoice_id):
    try:
        from firebase.firebase_hoadon.get_hoadon_from_firestore import get_invoice_by_id
        invoice = get_invoice_by_id(invoice_id)
        if invoice:
            return jsonify(invoice)
        return jsonify({"status": "error", "message": "Invoice not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Get invoices by date range
@app.route("/api/firebase/invoices/date", methods=["GET"])
def get_invoices_by_date():
    try:
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
       
        if not start_date or not end_date:
            return jsonify({"status": "error", "message": "startDate and endDate are required"}), 400
        
        from firebase.firebase_hoadon.get_hoadon_from_firestore import get_invoices_by_date
        invoices = get_invoices_by_date(start_date, end_date)
        
        return jsonify(invoices)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# Get invoices by customer
@app.route("/api/firebase/invoices/customer/<customer_name>", methods=["GET"])
def get_invoices_by_customer(customer_name):
    try:
        from firebase.firebase_hoadon.get_hoadon_from_firestore import get_invoices_by_customer
        invoices = get_invoices_by_customer(customer_name)
        return jsonify(invoices)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500













if __name__ == "__main__":
    env = os.getenv("e", "prod")

    if env != "prod":
        print("Running in LOCAL mode", env)
        app.run(host="0.0.0.0", port=5000)
    else:
        
        print("Running in PRODUCTION mode")
        app.run(host='0.0.0.0', port=8000)
      