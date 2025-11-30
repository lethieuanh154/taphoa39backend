from __future__ import annotations

import requests
from flask import Blueprint, jsonify, request
from google.api_core.exceptions import ResourceExhausted
from unidecode import unidecode

from FromKiotViet.get_all_customer import get_entire_customer
from FromKiotViet.get_all_product_by_category import get_items_category
from FromKiotViet.get_category import get_category
from FromKiotViet.get_entire_product import get_all as get_all_products_from_kiotviet
from FromKiotViet.get_all_out_of_stock import get_out_of_stock_master_products_data
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
        return jsonify(all_items)

    @bp.route("/categories", methods=["GET"])
    @handle_api_errors
    def get_categories_from_kiotviet():
        categories = get_category()
        return jsonify(categories)

    @bp.route("/items/out_of_stock", methods=["GET"])
    @handle_api_errors
    def get_items_out_of_stock_route():
        api_items = get_out_of_stock_master_products_data()
        sanitized_items = []
        for item in api_items or []:
            if item.get("Id") in (-1, "-1"):
                continue
            sanitized_items.append({
                "Id": item.get("Id"),
                "MasterProductId": item.get("Id"),
                "Code": item.get("Code"),
                "Image": item.get("Image"),
                "FullName": item.get("FullName"),
                "Cost": item.get("Cost"),
                "BasePrice": item.get("BasePrice"),
                "OnHand": item.get("OnHand"),
                "Unit": item.get("Unit"),
                "AttributeLabel": item.get("AttributeLabel"),
            })

        sanitized_items.sort(key=lambda x: x.get("OnHand", 0.0))

        return jsonify({"items": sanitized_items, "total_items": len(sanitized_items)})

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

    return bp
