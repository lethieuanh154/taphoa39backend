from __future__ import annotations

from flask import Blueprint, jsonify, request
from google.api_core.exceptions import ResourceExhausted

from routes.shared import broadcast_customer_updates, notify_customer_created


def create_firebase_customers_bp(customer_service, socketio) -> Blueprint:
    bp = Blueprint("firebase_customers", __name__, url_prefix="/api/firebase")

    @bp.route("/get/customers", methods=["GET"])
    def get_all_customers():
        try:
            customers = customer_service.read_all_customers()
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
            return jsonify({"status": "error", "message": str(exc)}), 500

    @bp.route("/customers/invoices/<customer_id>", methods=["GET"])
    def get_invoices_for_customer(customer_id: str):
        try:
            if not customer_id:
                return jsonify({"error": "Customer ID is required"}), 400

            result = customer_service.get_invoices_by_customer_id(customer_id)
            return jsonify(result)
        except ResourceExhausted as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": "Firestore quota exceeded", "details": str(exc)}), 429
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": str(exc)}), 500

    @bp.route("/add_customer", methods=["POST"])
    def add_customer():
        try:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"status": "error", "message": "JSON body is required"}), 400

            customer_id = payload.get("id") or payload.get("Id")
            if not customer_id:
                return jsonify({"status": "error", "message": "Customer ID is required"}), 400

            normalized = dict(payload)
            normalized["id"] = str(customer_id).strip()
            normalized.setdefault("Id", normalized["id"])

            result = customer_service.add_customer(normalized)

            broadcast_customer_updates(socketio, [
                {"applied": True, "customer": normalized}
            ])
            notify_customer_created(socketio, normalized)

            response = dict(result)
            response["customer"] = normalized
            return jsonify(response), 201
        except ResourceExhausted as exc:
            return jsonify({"status": "error", "message": "Firestore quota exceeded", "detail": str(exc)}), 429
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

            result = customer_service.update_customer(customer_id, payload)
            if result.get("updated"):
                return jsonify(result), 200

            status_code = 404 if result.get("reason") == "not_found" else 400
            return jsonify(result), status_code
        except ResourceExhausted as exc:
            return jsonify({"status": "error", "message": "Firestore quota exceeded", "detail": str(exc)}), 429
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

    return bp
