from flask import Flask, jsonify,send_from_directory
import os
import json
from unidecode import unidecode  # Thêm thư viện unidecode để loại bỏ dấu tiếng Việt
from flask_cors import CORS
from Utility.get_env import  LatestBranchId, retailer
from FromKiotViet.get_all_product_by_category import get_items_category
from FromKiotViet.get_category import get_category
from FromKiotViet.get_one_product import get_item
from FromKiotViet.get_authorization import auth_token
app = Flask(__name__)
CORS(app) 

@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:path>")
def serve_static_files(path):
    if os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")
    
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
    
@app.route('/api/items/all', methods=['GET'])
def get_all_items():

    category_id_list = get_category()
    all_items = []
    try:
        # Duyệt qua tất cả các file JSON trong thư mục
        for category_id in category_id_list:
            id = category_id["Id"]
            all_items.extend(get_items_category(id))
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

if __name__ == "__main__":
    env = os.getenv("e", "prod")

    if env != "prod":
        print("Running in LOCAL mode", env)
        app.run(host="0.0.0.0", port=5000)
    else:
        
        print("Running in PRODUCTION mode")
        app.run(host='0.0.0.0', port=8000)
      