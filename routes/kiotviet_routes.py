from __future__ import annotations

import requests
from flask import Blueprint, jsonify, request
from google.api_core.exceptions import ResourceExhausted
from unidecode import unidecode

from FromKiotViet.get_all_customer import get_entire_customer
from FromKiotViet.get_all_product_by_category import get_items_category
from FromKiotViet.get_category import get_category
from FromKiotViet.get_entire_product import get_all as get_all_products_from_kiotviet
from FromKiotViet.get_one_product import get_item
from routes.shared import handle_api_errors
from Utility.get_env import LatestBranchId, retailer


def create_kiotviet_routes_bp() -> Blueprint:
    bp = Blueprint("kiotviet_routes", __name__, url_prefix="/api/kiotviet")

    @bp.route("/authentication", methods=["POST"])
    @handle_api_errors
    def get_authen():
        data = request.get_json()
        if not data or 'username' not in data or 'password' not in data:
            return jsonify({"status": "error", "message": "Username and password are required"}), 400

        username = data['username']
        password = data['password']

        auth_url = "https://api-man1.kiotviet.vn/api/account/login?quan-ly=true"
        body = {
            "model": {
                "RememberMe": "true",
                "ShowCaptcha": "false",
                "UserName": username,
                "Password": password,
                "Language": "vi-VN",
                "LatestBranchId": LatestBranchId,
            },
            "IsManageSide": "true",
            "FingerPrintKey": "211d1f5bb8cc08a94863d2291f1c866d_Chrome_Desktop_Máy tính Windows",
        }
        params = {"quan-ly": "true"}
        headers = {"retailer": retailer}

        response = requests.post(auth_url, json=body, headers=headers, params=params)

        if response.status_code == 200:
            token_data = response.json().get("token", "")
            if token_data:
                auth_token = "Bearer " + token_data
                auth_data = {
                    "retailer": retailer,
                    "LatestBranchId": LatestBranchId,
                    "access_token": auth_token,
                }
                return jsonify(auth_data), 200
            return jsonify({"status": "error", "message": "Invalid credentials"}), 401
        return jsonify({"status": "error", "message": "Authentication failed"}), 401

    @bp.route("/item/<term>", methods=["GET"])
    @handle_api_errors
    def get_item_by_term_from_kiotviet(term: str):
        product_detail = get_item(term)
        if product_detail:
            return jsonify(product_detail), 200
        return jsonify({"status": "error", "message": f"Product not found with term: {term}"}), 404

    @bp.route("/items/all", methods=["GET"])
    @handle_api_errors
    def get_all_items_from_kiotviet():
        all_items = get_all_products_from_kiotviet()
        if all_items is None:
            return jsonify({"status": "error", "message": "KiotViet API trả về lỗi. Kiểm tra token hoặc kết nối."}), 502
        return jsonify(all_items)

    @bp.route("/categories", methods=["GET"])
    @handle_api_errors
    def get_categories_from_kiotviet():
        categories = get_category()
        if categories is None:
            return jsonify({"status": "error", "message": "Không lấy được danh mục từ KiotViet. Kiểm tra token hoặc kết nối."}), 502
        return jsonify(categories)


    @bp.route("/items/category/<category_name>", methods=["GET"])
    @handle_api_errors
    def get_items_by_category_from_kiotviet(category_name: str):
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

    @bp.route("/customers", methods=["GET"])
    @handle_api_errors
    def get_all_customers_from_kiotviet_route():
        customers = get_entire_customer()
        return jsonify(customers)

    @bp.route("/product-images/<int:product_id>", methods=["GET"])
    @handle_api_errors
    def get_product_images(product_id: int):
        """Proxy KiotViet product images API. Returns list of image URLs."""
        from FromKiotViet.get_authorization import get_token
        url = f"https://api-man1.kiotviet.vn/api/productimage/{product_id}?limit=10"
        headers = {
            "Authorization": get_token(),
            "retailer": retailer,
            "branchid": LatestBranchId,
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            images = [item.get("Image") for item in data.get("Data", []) if item.get("Image")]
            return jsonify({"images": images, "total": data.get("Total", 0), "productId": product_id})
        return jsonify({"images": [], "total": 0, "productId": product_id})

    @bp.route("/products/addmany", methods=["POST"])
    @handle_api_errors
    def add_original_products():
        """Create new products in KiotViet via addmany API."""
        import json as _json
        from FromKiotViet.get_authorization import get_token as _get_token

        data = request.get_json()
        name = data.get("name", "")
        code = data.get("code", "")
        category_id = data.get("categoryId", 0)
        trademark_id = data.get("trademarkId", None)
        tax_rate = int(data.get("taxRate", 0))
        units = data.get("units", [])
        description = data.get("description", "")
        order_template = data.get("orderTemplate", "")

        if not name or not units:
            return jsonify({"error": "name and units are required"}), 400

        tax_id_map = {0: 1, 5: 2, 8: 3, 10: 4}
        tax_id = tax_id_map.get(tax_rate, 1)

        def price_include_vat(price):
            if tax_rate == 0:
                return float(price)
            return round(float(price) / (1 + tax_rate / 100), 2)

        base_units = [u for u in units if u.get("isBase")]
        child_units = [u for u in units if not u.get("isBase")]

        if not base_units:
            return jsonify({"error": "Missing base unit"}), 400
        base = base_units[0]

        def repeat_guarantee():
            return {"Uuid": -1, "TimeType": 2, "ProductId": 0, "RetailerId": 0, "Description": "Toàn bộ sản phẩm"}

        def base_fields(unit, done_created, product_units, max_quantity, unit_code=""):
            return {
                "Id": 0, "ProductType": 2, "CategoryId": category_id, "CategoryName": "",
                "isActive": False, "HasVariants": False, "VariantCount": 0, "AllowsSale": True,
                "isDeleted": False, "Code": unit_code or code, "BasePrice": unit["price"], "Cost": unit["cost"],
                "LatestPurchasePrice": 0, "OnHand": unit.get("onHand", 0), "OnOrder": 0,
                "MinQuantity": 0, "MaxQuantity": max_quantity, "CustomId": 0, "CustomValue": 0,
                "MasterProductId": 0, "Unit": unit["unit"], "ConversionValue": unit.get("conversion", 1),
                "OrderTemplate": order_template, "IsLotSerialControl": False, "IsRewardPoint": True,
                "FormulaCount": 0, "Barcode": "", "PageSize": 0, "TaxId": tax_id,
                "PriceIncludeVat": price_include_vat(unit["price"]), "Type4": 2, "oldBaseUnit": "",
                "Description": description, "GenuineGuarantees": [], "StoreGuarantees": [],
                "RepeatGuarantee": repeat_guarantee(), "ProductFormulas": [], "Name": name,
                "ProductAttributes": [], "isDraft": False, "showEditButton": True, "IsNewUnit": True,
                "ProductUnits": product_units, "ProductUnit": [], "doneCreated": done_created,
                "ListPriceBookDetail": [], "FullName": f"{name} ({unit['unit']})", "MasterCode": "",
                "CompareFullName": f"{name} ({unit['unit']})", "ListUnitPriceBookDetail": None if done_created is False else [],
                "RewardPoint": 0, "MasterUnitIdClone": None, "TradeMarkId": trademark_id,
                "ProductFormulasOld": [], "ProductImages": []
            }

        def build_unit_ref(child, done, child_code=""):
            return {
                "Id": 0, "Unit": child["unit"], "Code": child_code, "BasePrice": child["price"],
                "AllowsSale": True, "PriceIncludeVat": price_include_vat(child["price"]),
                "isDraft": False, "showEditButton": True, "IsNewUnit": True,
                "ConversionValue": child.get("conversion", 1), "doneCreated": done
            }

        products_list = [base_fields(base, False, [], 999999999, unit_code=code)]

        for i, child in enumerate(child_units):
            child_code = f"{code}-{i + 1}" if code else ""
            pus = [build_unit_ref(child_units[j], done=(j < i), child_code=(f"{code}-{j + 1}" if code else "")) for j in range(i + 1)]
            products_list.append(base_fields(child, True, pus, 0, unit_code=child_code))

        kv_url = "https://api-man1.kiotviet.vn/api/products/addmany?apiversion=5"
        headers = {"Authorization": _get_token(), "branchid": LatestBranchId, "retailer": retailer}
        branch_info = [{"Id": int(LatestBranchId), "Name": "Chi nhánh trung tâm"}]
        payload = {
            "ListProductsString": _json.dumps(products_list, ensure_ascii=False),
            "CloneProductId": "0",
            "BranchForProductCostss": _json.dumps(branch_info, ensure_ascii=False)
        }

        resp = requests.post(kv_url, headers=headers, data=payload, timeout=30)
        resp_data = resp.json()

        if resp.status_code != 200:
            import logging
            logging.error(f"[addmany] KiotViet returned {resp.status_code}: {resp_data}")

        return jsonify(resp_data), resp.status_code

    return bp
