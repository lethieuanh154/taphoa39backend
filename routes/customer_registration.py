from __future__ import annotations

import re

from flask import Blueprint, jsonify, request
from google.api_core.exceptions import ResourceExhausted

from FromKiotViet.Model.customer import Customer
from FromKiotViet.add_customer import add_customer_to_kiotviet
from Utility.get_env import LatestBranchId
from routes.shared import broadcast_customer_updates, notify_customer_created

VN_PHONE_RE = re.compile(r"^0[35789]\d{8}$")


def create_customer_registration_bp(customer_service, socketio) -> Blueprint:
    bp = Blueprint("customer_registration", __name__, url_prefix="/api/customer")

    def _validate_phone(phone: str) -> bool:
        return bool(VN_PHONE_RE.match(phone))

    def _phone_exists(phone: str) -> bool:
        customers = customer_service.read_all_customers()
        for c in customers:
            if not isinstance(c, dict):
                continue
            contact = c.get("ContactNumber") or ""
            if contact.strip() == phone:
                return True
        return False

    def _generate_customer_code() -> str:
        customers = customer_service.read_all_customers()
        max_num = 0
        for c in customers:
            if not isinstance(c, dict):
                continue
            code = c.get("Code") or ""
            if code.startswith("KH") and code[2:].isdigit():
                num = int(code[2:])
                if num > max_num:
                    max_num = num
        return f"KH{max_num + 1:05d}"

    @bp.route("/register", methods=["POST"])
    def register_customer():
        try:
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"success": False, "message": "JSON body is required"}), 400

            name = (payload.get("name") or "").strip()
            phone = (payload.get("phone") or "").strip()

            if not name:
                return jsonify({"success": False, "message": "Tên là bắt buộc"}), 400
            if not phone:
                return jsonify({"success": False, "message": "Số điện thoại là bắt buộc"}), 400
            if not _validate_phone(phone):
                return jsonify({"success": False, "message": "Số điện thoại không hợp lệ"}), 400
            if _phone_exists(phone):
                return jsonify({"success": False, "message": "Số điện thoại đã được đăng ký"}), 409

            customer_code = _generate_customer_code()

            customer = Customer.from_frontend_payload(
                {"name": name, "phone": phone},
                default_branch_id=LatestBranchId,
            )
            customer.Code = customer_code
            customer.CompareCode = customer_code

            kiot_response = add_customer_to_kiotviet(customer.to_kiotviet_payload())
            customer.apply_kiotviet_response(kiot_response)

            if customer.Id is None:
                raise ValueError("KiotViet response missing customer Id")

            data = customer.to_dict(include_none=False, include_id_alias=True)
            if customer.Id is not None:
                data.setdefault("Id", customer.Id)
                data.setdefault("id", str(customer.Id))

            customer_service.add_customer(data)

            broadcast_customer_updates(socketio, [{"applied": True, "customer": data}])
            notify_customer_created(socketio, data)

            return jsonify({
                "success": True,
                "customer_code": customer_code,
                "barcode_value": customer_code,
                "name": name,
                "phone": phone,
            }), 201

        except ResourceExhausted as exc:
            return jsonify({"success": False, "message": "Firestore quota exceeded", "detail": str(exc)}), 429
        except ValueError as exc:
            return jsonify({"success": False, "message": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"success": False, "message": str(exc)}), 502
        except Exception as exc:
            import traceback
            print(traceback.format_exc())
            return jsonify({"success": False, "message": str(exc)}), 500

    return bp
