from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from google.api_core.exceptions import ResourceExhausted

from FromKiotViet.Model.customer import Customer
from FromKiotViet.add_customer import add_customer_to_kiotviet
from Utility.get_env import LatestBranchId
from routes.shared import broadcast_customer_updates, notify_customer_created
from routes.zalo_routes import rate_limit_check, send_zalo_cs_message

logger = logging.getLogger(__name__)

VN_PHONE_RE = re.compile(r"^0[35789]\d{8}$")
FRONTEND_DOMAIN = os.getenv("FRONTEND_DOMAIN", "https://songminh-dangky.web.app")


def _firestore_transaction_run(db, func):
    """Run func inside a Firestore transaction."""
    transaction = db.transaction()
    result = func(transaction)
    transaction.commit()
    return result


def create_customer_registration_bp(customer_service, socketio) -> Blueprint:
    bp = Blueprint("customer_registration", __name__, url_prefix="/api/customer")

    def _validate_phone(phone: str) -> bool:
        return bool(VN_PHONE_RE.match(phone))

    def _find_by_phone(phone: str) -> dict | None:
        customers = customer_service.read_all_customers()
        for c in customers:
            if not isinstance(c, dict):
                continue
            contact = (c.get("ContactNumber") or "").strip()
            if contact == phone:
                return c
        return None

    def _find_by_zalo_id(zalo_user_id: str) -> dict | None:
        customers = customer_service.read_all_customers()
        for c in customers:
            if not isinstance(c, dict):
                continue
            if (c.get("ZaloUserId") or "") == zalo_user_id:
                return c
        return None

    def _generate_customer_code_transaction() -> str:
        """Generate KH code using Firestore transaction to prevent race conditions."""
        from firebase.init_firebase import init_firestore
        from google.cloud.firestore_v1 import transactional

        db = init_firestore("FIREBASE_SERVICE_ACCOUNT_CUSTOMER")
        counter_ref = db.collection("counters").document("customer_counter")

        @transactional
        def _update_counter(transaction):
            snapshot = counter_ref.get(transaction=transaction)
            if snapshot.exists:
                current = snapshot.to_dict().get("last_number", 0)
            else:
                current = 0
            next_num = current + 1
            transaction.set(counter_ref, {"last_number": next_num}, merge=True)
            return f"KH{next_num:05d}"

        return _update_counter(db.transaction())

    def _generate_customer_code_fallback() -> str:
        """Fallback: scan all customers for max KH code."""
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

    def _generate_customer_code() -> str:
        try:
            return _generate_customer_code_transaction()
        except Exception as exc:
            logger.warning("Transaction code gen failed, using fallback: %s", exc)
            return _generate_customer_code_fallback()

    @bp.route("/register", methods=["POST"])
    def register_customer():
        try:
            # Rate limit
            client_ip = request.remote_addr or "unknown"
            if rate_limit_check(client_ip):
                return jsonify({"success": False, "message": "Vui lòng chờ trước khi đăng ký lại"}), 429

            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"success": False, "message": "JSON body is required"}), 400

            name = (payload.get("name") or "").strip()
            phone = (payload.get("phone") or "").strip()
            zalo_user_id = (payload.get("zalo_user_id") or "").strip()

            if not phone:
                return jsonify({"success": False, "message": "Số điện thoại là bắt buộc"}), 400
            if not _validate_phone(phone):
                return jsonify({"success": False, "message": "Số điện thoại không hợp lệ"}), 400

            # Check duplicate Zalo → return existing
            if zalo_user_id:
                existing_zalo = _find_by_zalo_id(zalo_user_id)
                if existing_zalo:
                    code = existing_zalo.get("Code") or ""
                    return jsonify({
                        "success": True,
                        "customer_code": code,
                        "barcode_value": code,
                        "name": existing_zalo.get("Name") or name,
                        "phone": existing_zalo.get("ContactNumber") or phone,
                        "existing": True,
                    }), 200

            # Check duplicate phone → return existing
            existing = _find_by_phone(phone)
            if existing:
                code = existing.get("Code") or ""
                return jsonify({
                    "success": True,
                    "customer_code": code,
                    "barcode_value": code,
                    "name": existing.get("Name") or name,
                    "phone": phone,
                    "existing": True,
                }), 200

            # Default name if not provided
            if not name:
                name = f"KH {phone[-4:]}"

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

            if zalo_user_id:
                data["ZaloUserId"] = zalo_user_id
            data["CreatedDate"] = datetime.now(timezone.utc).isoformat()

            customer_service.add_customer(data)

            broadcast_customer_updates(socketio, [{"applied": True, "customer": data}])
            notify_customer_created(socketio, data)

            # Send Zalo CS message (best-effort, non-blocking)
            if zalo_user_id:
                try:
                    card_url = f"{FRONTEND_DOMAIN}/card/{customer_code}"
                    msg = (
                        f"🎉 Đăng ký thành công!\n\n"
                        f"Mã khách hàng: {customer_code}\n"
                        f"Xem thẻ thành viên:\n{card_url}"
                    )
                    send_zalo_cs_message(zalo_user_id, msg)
                except Exception as exc:
                    logger.error("Zalo CS message failed (non-fatal): %s", exc)

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
            logger.error(traceback.format_exc())
            return jsonify({"success": False, "message": str(exc)}), 500

    @bp.route("/card/<customer_code>", methods=["GET"])
    def get_customer_card(customer_code: str):
        """Return customer info for the membership card page."""
        if not customer_code:
            return jsonify({"error": "Customer code is required"}), 400

        customers = customer_service.read_all_customers()
        for c in customers:
            if not isinstance(c, dict):
                continue
            if (c.get("Code") or "") == customer_code:
                return jsonify({
                    "success": True,
                    "customer_code": c.get("Code"),
                    "name": c.get("Name") or "",
                    "phone": c.get("ContactNumber") or "",
                    "barcode_value": c.get("Code"),
                })
        return jsonify({"success": False, "message": "Không tìm thấy khách hàng"}), 404

    return bp
