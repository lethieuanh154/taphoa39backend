from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from google.api_core.exceptions import ResourceExhausted

from FromKiotViet.Model.customer import Customer
from FromKiotViet.add_customer import add_customer_to_kiotviet
from FromKiotViet.delete_customer import delete_customers_from_kiotviet
from Utility.get_env import LatestBranchId
from routes.shared import (
    broadcast_customer_updates,
    create_fetch_handler,
    handle_api_errors,
    notify_customer_created,
)
from routes.zalo_routes import send_zalo_cs_message

logger = logging.getLogger(__name__)


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

    def _find_existing_customer(customer_id: str) -> Customer | None:
        all_customers = customer_service.read_all_customers()
        for c in all_customers:
            cid = c.get("Id") or c.get("id")
            if str(cid) == str(customer_id):
                return Customer.from_dict(c, default_branch_id=LatestBranchId)
        return None

    def _merge_customer_update(existing: Customer, updated: Customer) -> Customer:
        """Merge frontend form changes onto the existing customer, keeping fields the form doesn't touch."""
        # Fields that the frontend form can change
        if updated.Name:
            existing.Name = updated.Name
            existing.CompareName = updated.Name
        if updated.ContactNumber is not None:
            existing.ContactNumber = updated.ContactNumber
        if updated.Address is not None:
            existing.Address = updated.Address
        if updated.Email is not None:
            existing.Email = updated.Email
        if updated.GenderName is not None:
            existing.GenderName = updated.GenderName
        if updated.CustomerType is not None:
            existing.CustomerType = updated.CustomerType
        if updated.TaxCode is not None:
            existing.TaxCode = updated.TaxCode
        if updated.Organization is not None:
            existing.Organization = updated.Organization
        return existing

    def _update_customer_on_kiotviet(customer: Customer) -> dict:
        """Send full customer payload to KiotViet for update (requires Id, Code, __type)."""
        kv_payload = customer.to_kiotviet_payload()
        kv_payload["__type"] = "KiotViet.Persistence.OrmCustomer, KiotViet.Domain"
        kv_payload.setdefault("IsActive", True)
        kv_payload.setdefault("BranchId", LatestBranchId)

        kiot_response = add_customer_to_kiotviet(kv_payload)
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

            # Read existing customer from Firestore to get full data (Code, Id, etc.)
            existing = _find_existing_customer(customer_id)
            if existing is None:
                return jsonify({"status": "error", "message": "Customer not found"}), 404

            # Build customer from frontend payload then merge onto existing
            updated_fields = _build_customer(payload, require_id=False, allow_frontend_shape=True)
            merged = _merge_customer_update(existing, updated_fields)

            kiotviet_response = _update_customer_on_kiotviet(merged)
            merged.apply_kiotviet_response(kiotviet_response)
            normalized = _customer_to_firestore_payload(merged)

            result = customer_service.update_customer(str(merged.Id), normalized)
            if result.get("updated"):
                broadcast_customer_updates(socketio, [
                    {"applied": True, "customer": normalized}
                ])
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

    @bp.route("/customers/reset_points", methods=["POST"])
    @handle_api_errors
    def reset_customer_points():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"status": "error", "message": "JSON body is required"}), 400

        lunar_year = payload.get("lunarYear")
        if lunar_year is None or not isinstance(lunar_year, (int, float)):
            return jsonify({"status": "error", "message": "lunarYear is required (integer)"}), 400

        cutoff_date = payload.get("cutoffDate")  # Solar date of lunar Jan 1
        result = customer_service.reset_all_customer_points(int(lunar_year), cutoff_date)

        if result.get("reset_count", 0) > 0:
            broadcast_customer_updates(socketio, [{"applied": True, "reset": True}])

        return jsonify(result)

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

            # Xóa trên KiotViet trước
            kiotviet_result = None
            numeric_ids = [int(cid) for cid in customer_ids if str(cid).strip().isdigit()]
            if numeric_ids:
                try:
                    kiotviet_result = delete_customers_from_kiotviet(numeric_ids)
                    print(f"✅ KiotViet delete result: {kiotviet_result}")
                except Exception as kv_exc:
                    print(f"⚠️ KiotViet delete failed (continuing with Firebase): {kv_exc}")
                    kiotviet_result = {"error": str(kv_exc)}

            # Xóa trên Firebase
            result = customer_service.delete_customers(customer_ids)
            result["kiotviet"] = kiotviet_result

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

    @bp.route("/customers/<customer_id>/add_bonus", methods=["POST"])
    @handle_api_errors
    def add_bonus_point(customer_id: str):
        if not customer_id:
            return jsonify({"status": "error", "message": "Customer ID is required"}), 400

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"status": "error", "message": "JSON body is required"}), 400

        amount = payload.get("amount")
        if amount is None or not isinstance(amount, (int, float)) or amount <= 0:
            return jsonify({"status": "error", "message": "amount must be a positive number"}), 400

        amount = int(amount)

        # Read current customer
        all_customers = customer_service.read_all_customers()
        current_customer = None
        for c in all_customers:
            cid = c.get("Id") or c.get("id")
            if str(cid) == str(customer_id):
                current_customer = c
                break

        if current_customer is None:
            return jsonify({"status": "error", "message": "Customer not found"}), 404

        current_bonus = current_customer.get("BonusPoint") or 0
        new_bonus = int(current_bonus) + amount

        reason = payload.get("reason") or "điểm thưởng"

        result = customer_service.update_customer(str(customer_id), {"BonusPoint": new_bonus})
        if result.get("updated"):
            updated_customer = dict(current_customer)
            updated_customer["BonusPoint"] = new_bonus
            broadcast_customer_updates(socketio, [
                {"applied": True, "customer": updated_customer}
            ])

            # Emit bonus_updated for customer-facing app (TapHoa39DatHang)
            customer_code = updated_customer.get("Code") or ""
            if customer_code and socketio:
                total_point = updated_customer.get("TotalPoint", 0) or 0
                raw_gift = total_point * 0.02
                base = round(raw_gift / 100) * 100
                if not isinstance(base, (int, float)) or base != base:
                    base = 0
                reg_bonus = updated_customer.get("RegistrationBonus", 0) or 0
                redeemed = updated_customer.get("RedeemedPoints", 0) or 0
                gift_point = max(0, base + reg_bonus + new_bonus - redeemed)
                bonus_payload = {
                    "code": customer_code,
                    "giftPoint": gift_point,
                    "bonusAdded": amount,
                }
                logger.info("[bonus_updated] Emitting WS: %s", bonus_payload)
                socketio.emit("bonus_updated", bonus_payload, namespace="/api/websocket/customers")

            # Send Zalo notification (best-effort)
            zalo_sent = False
            zalo_user_id = current_customer.get("ZaloUserId") or ""
            if zalo_user_id:
                try:
                    customer_name = current_customer.get("Name") or "Quý khách"
                    msg = (
                        f"🎁 Xin chào {customer_name}!\n\n"
                        f"Bạn vừa nhận được {amount:,} điểm thưởng"
                        f" từ {reason}.\n"
                        f"Tổng điểm thưởng hiện tại: {new_bonus:,} điểm.\n\n"
                        f"Cảm ơn bạn đã ủng hộ Tạp Hóa 39! 🙏"
                    )
                    send_zalo_cs_message(zalo_user_id, msg)
                    zalo_sent = True
                except Exception as exc:
                    logger.error("Zalo CS message failed (non-fatal): %s", exc)

            return jsonify({
                "status": "ok",
                "customer_id": customer_id,
                "BonusPoint": new_bonus,
                "added": amount,
                "customer": updated_customer,
                "zalo_sent": zalo_sent,
            })

        status_code = 404 if result.get("reason") == "not_found" else 400
        return jsonify(result), status_code

    def _read_customer_doc(customer_id: str):
        """Doc truc tiep customers/<Id>, tranh full scan read_all_customers()."""
        doc_id = str(customer_id).strip()
        if not doc_id:
            return None
        snapshot = customer_service.customers_ref.document(doc_id).get()
        if not snapshot.exists:
            return None
        return snapshot.to_dict() or {}

    def _sorted_notes(raw) -> list:
        notes = [n for n in (raw or []) if isinstance(n, dict)]
        notes.sort(key=lambda n: str(n.get("createdAt") or ""), reverse=True)
        return notes

    @bp.route("/customers/<customer_id>/notes", methods=["GET"])
    @handle_api_errors
    def get_customer_notes(customer_id: str):
        data = _read_customer_doc(customer_id)
        if data is None:
            return jsonify({"status": "error", "message": "Customer not found"}), 404
        return jsonify({"status": "ok", "notes": _sorted_notes(data.get("GiftNotes"))})

    @bp.route("/customers/<customer_id>/notes", methods=["POST"])
    @handle_api_errors
    def add_customer_note(customer_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"status": "error", "message": "JSON body is required"}), 400

        text = (payload.get("text") or "").strip()
        if not text:
            return jsonify({"status": "error", "message": "text is required"}), 400
        text = text[:500]

        data = _read_customer_doc(customer_id)
        if data is None:
            return jsonify({"status": "error", "message": "Customer not found"}), 404

        note = {
            "id": uuid.uuid4().hex,
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "createdBy": (payload.get("createdBy") or "").strip(),
        }
        notes = [n for n in (data.get("GiftNotes") or []) if isinstance(n, dict)]
        notes.append(note)

        result = customer_service.update_customer(str(customer_id), {"GiftNotes": notes})
        if not result.get("updated"):
            status_code = 404 if result.get("reason") == "not_found" else 400
            return jsonify(result), status_code

        updated_customer = dict(data)
        updated_customer["GiftNotes"] = notes
        broadcast_customer_updates(socketio, [
            {"applied": True, "customer": updated_customer}
        ])

        return jsonify({"status": "ok", "note": note, "notes": _sorted_notes(notes)})

    @bp.route("/customers/<customer_id>/notes/<note_id>", methods=["DELETE"])
    @handle_api_errors
    def delete_customer_note(customer_id: str, note_id: str):
        data = _read_customer_doc(customer_id)
        if data is None:
            return jsonify({"status": "error", "message": "Customer not found"}), 404

        notes = [n for n in (data.get("GiftNotes") or []) if isinstance(n, dict)]
        remaining = [n for n in notes if str(n.get("id")) != str(note_id)]
        if len(remaining) == len(notes):
            return jsonify({"status": "error", "message": "Note not found"}), 404

        result = customer_service.update_customer(str(customer_id), {"GiftNotes": remaining})
        if not result.get("updated"):
            status_code = 404 if result.get("reason") == "not_found" else 400
            return jsonify(result), status_code

        updated_customer = dict(data)
        updated_customer["GiftNotes"] = remaining
        broadcast_customer_updates(socketio, [
            {"applied": True, "customer": updated_customer}
        ])

        return jsonify({"status": "ok", "notes": _sorted_notes(remaining)})

    @bp.route("/customers/<customer_id>/clear_debt", methods=["POST"])
    @handle_api_errors
    def clear_customer_debt(customer_id: str):
        if not customer_id:
            return jsonify({"status": "error", "message": "Customer ID is required"}), 400

        result = customer_service.clear_customer_debt(customer_id)
        if result.get("updated"):
            broadcast_customer_updates(socketio, [
                {"applied": True, "customer": result.get("customer")}
            ])
            return jsonify({"status": "ok", **result})

        status_code = 404 if result.get("reason") == "not_found" else 400
        return jsonify(result), status_code

    @bp.route("/customers/fetch", methods=["POST"])
    def fetch_customers_changed():
        """
        Accepts JSON: { "id": "123" } or { "ids": ["1","2"] }
        Returns the latest customer document(s) from Firestore.
        """
        return create_fetch_handler(customer_service, "read_all_customers")()

    return bp
