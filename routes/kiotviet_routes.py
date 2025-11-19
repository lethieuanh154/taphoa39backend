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
from Utility.get_env import LatestBranchId, retailer


def create_kiotviet_routes_bp() -> Blueprint:
    bp = Blueprint("kiotviet_routes", __name__, url_prefix="/api/kiotviet")

    @bp.route("/authentication", methods=["POST"])
    def get_authen():
        try:
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
        except Exception as exc:  # pragma: no cover - best effort logging
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    @bp.route("/item/<term>", methods=["GET"])
    def get_item_by_term_from_kiotviet(term: str):
        try:
            product_detail = get_item(term)
            if product_detail:
                return jsonify(product_detail), 200
            return jsonify({"status": "error", "message": f"Product not found with term: {term}"}), 404
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    @bp.route("/items/all", methods=["GET"])
    def get_all_items_from_kiotviet():
        try:
            all_items = get_all_products_from_kiotviet()
            return jsonify(all_items)
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    @bp.route("/categories", methods=["GET"])
    def get_categories_from_kiotviet():
        try:
            categories = get_category()
            return jsonify(categories)
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    @bp.route("/items/out_of_stock", methods=["GET"])
    def get_items_out_of_stock_route():
        try:
            all_items = get_all_products_from_kiotviet() or []
            out_of_stock_items = [
                {
                    "Code": item.get("Code"),
                    "Image": item.get("Image"),
                    "FullName": item.get("FullName"),
                    "Cost": item.get("Cost"),
                    "BasePrice": item.get("BasePrice"),
                    "OnHand": item.get("OnHand"),
                }
                for item in all_items
                if (item.get("MasterUnitId") is None) and (item.get("OnHand", 0) < 10)
            ]
            out_of_stock_items.sort(key=lambda x: x.get("OnHand", 0))

            total_items = len(out_of_stock_items)
            return jsonify({"items": out_of_stock_items, "total_items": total_items})
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    @bp.route("/items/category/<category_name>", methods=["GET"])
    def get_items_by_category_from_kiotviet(category_name: str):
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
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    @bp.route("/customers", methods=["GET"])
    def get_all_customers_from_kiotviet_route():
        try:
            customers = get_entire_customer()
            return jsonify(customers)
        except ResourceExhausted as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({
                "status": "error",
                "message": "Firestore quota exceeded during customer refresh",
                "details": str(exc),
            }), 429
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc), "trace": traceback.format_exc()}), 500

    return bp
