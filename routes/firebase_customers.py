from __future__ import annotations

from flask import Blueprint, jsonify, request
from google.api_core.exceptions import ResourceExhausted

from FromKiotViet.Model.customer import Customer
from FromKiotViet.add_customer import add_customer_to_kiotviet
from Utility.get_env import LatestBranchId
from routes.shared import (
    broadcast_customer_updates,
    create_fetch_handler,
    handle_api_errors,
    notify_customer_created,
)


def create_firebase_customers_bp(customer_service, socketio) -> Blueprint:
    bp = Blueprint("firebase_customers", __name__, url_prefix="/api/firebase")

    def _build_customer(payload, require_id: bool, allow_frontend_shape: bool = False) -> Customer:
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")

        use_frontend_shape = allow_frontend_shape and ("name" in payload or "phone" in payload)
        if use_frontend_shape:
            customer = Customer.from_frontend_payload(payload, default_branch_id=LatestBranchId)
        else:
            customer = Customer.from_dict(payload, default_branch_id=LatestBranchId)

        if require_id and customer.Id is None:
            raise ValueError("Customer ID is required")
        return customer

    def _customer_to_firestore_payload(customer: Customer) -> dict:
        data = customer.to_dict(include_none=False, include_id_alias=True)
        if customer.Id is not None:
            data.setdefault("Id", customer.Id)
            data.setdefault("id", str(customer.Id))
        return data

    def _sync_customer_with_kiotviet(customer: Customer) -> dict:
        kiot_response = add_customer_to_kiotviet(customer.to_kiotviet_payload())
        customer.apply_kiotviet_response(kiot_response)
        if customer.Id is None:
            raise ValueError("KiotViet response missing customer Id")
        return kiot_response

    def _coerce_numeric_ids(records):
        for item in records or []:
            if not isinstance(item, dict):
                continue
            id_value = item.get("Id")
            if isinstance(id_value, str) and id_value.isdigit():
                item["Id"] = int(id_value)
        return records

    @bp.route("/get/customers", methods=["GET"])
    @handle_api_errors
    def get_all_customers():
        customers = customer_service.read_all_customers()
        _coerce_numeric_ids(customers)
        return jsonify(customers)

    @bp.route("/customers/invoices/<customer_id>", methods=["GET"])
    @handle_api_errors
    def get_invoices_for_customer(customer_id: str):
        if not customer_id:
            return jsonify({"error": "Customer ID is required"}), 400

        result = customer_service.get_invoices_by_customer_id(customer_id)
        return jsonify(result)

    @bp.route("/add_customer", methods=["POST"])
    def add_customer():
        try:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"status": "error", "message": "JSON body is required"}), 400

            customer = _build_customer(payload, require_id=False, allow_frontend_shape=True)
            kiotviet_response = _sync_customer_with_kiotviet(customer)
            normalized = _customer_to_firestore_payload(customer)

            result = customer_service.add_customer(normalized)

            broadcast_customer_updates(socketio, [
                {"applied": True, "customer": normalized}
            ])
            notify_customer_created(socketio, normalized)

            response = dict(result)
            response["customer"] = normalized
            response["kiotviet"] = kiotviet_response
            return jsonify(response), 201
        except ResourceExhausted as exc:
            return jsonify({"status": "error", "message": "Firestore quota exceeded", "detail": str(exc)}), 429
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 502
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc)}), 500

    @bp.route("/customers/<customer_id>", methods=["PUT"])
    def update_customer(customer_id: str):
        try:
            if not customer_id:
                return jsonify({"status": "error", "message": "Customer ID is required"}), 400

            payload = request.get_json(silent=True)
            if payload is None:
                return jsonify({"status": "error", "message": "JSON body is required"}), 400

            if not isinstance(payload, dict):
                return jsonify({"status": "error", "message": "Body must be a JSON object"}), 400

            customer = _build_customer(payload, require_id=False, allow_frontend_shape=True)
            customer.ensure_id(customer_id)
            kiotviet_response = _sync_customer_with_kiotviet(customer)
            normalized = _customer_to_firestore_payload(customer)

            result = customer_service.update_customer(str(customer.Id), normalized)
            if result.get("updated"):
                response = dict(result)
                response["customer"] = normalized
                response["kiotviet"] = kiotviet_response
                return jsonify(response), 200

            status_code = 404 if result.get("reason") == "not_found" else 400
            return jsonify(result), status_code
        except ResourceExhausted as exc:
            return jsonify({"status": "error", "message": "Firestore quota exceeded", "detail": str(exc)}), 429
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 502
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc)}), 500

    @bp.route("/customers/<customer_id>/recalculate", methods=["POST"])
    def recalculate_customer(customer_id: str):
        try:
            if not customer_id:
                return jsonify({"status": "error", "message": "Customer ID is required"}), 400

            result = customer_service.recalculate_customer_totals(customer_id)
            if result.get("updated"):
                broadcast_customer_updates(socketio, [
                    {"applied": True, "customer": result.get("customer")}
                ])
                return jsonify(result)

            status_code = 404 if result.get("reason") == "not_found" else 400
            return jsonify(result), status_code
        except ResourceExhausted as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": "Firestore quota exceeded", "details": str(exc)}), 429
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc)}), 500

    @bp.route("/customers/batch_delete", methods=["POST"])
    def delete_customers():
        try:
            payload = request.get_json(silent=True)
            if payload is None:
                return jsonify({"status": "error", "message": "JSON body is required"}), 400

            if isinstance(payload, dict):
                customer_ids = payload.get("ids") or payload.get("customerIds")
            elif isinstance(payload, list):
                customer_ids = payload
            else:
                return jsonify({"status": "error", "message": "Body must be a list or an object with 'ids'"}), 400

            if customer_ids is None:
                return jsonify({"status": "error", "message": "customer_ids is required"}), 400

            result = customer_service.delete_customers(customer_ids)

            if result.get("requested", 0) == 0:
                return jsonify(result), 400

            status_code = 200 if result.get("deleted_count", 0) > 0 else 400
            return jsonify(result), status_code
        except ResourceExhausted as exc:
            return jsonify({"status": "error", "message": "Firestore quota exceeded", "detail": str(exc)}), 429
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc)}), 500

    @bp.route("/customers/fetch", methods=["POST"])
    def fetch_customers_changed():
        """
        Accepts JSON: { "id": "123" } or { "ids": ["1","2"] }
        Returns the latest customer document(s) from Firestore.
        """
        return create_fetch_handler(customer_service, "read_all_customers")()

    return bp
