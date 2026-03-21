"""REST API routes for chat messages."""
from __future__ import annotations
import time

import bcrypt
from flask import Blueprint, jsonify, request
from routes.shared import handle_api_errors


def create_chat_routes_bp(chat_service, socketio, customer_service=None):
    bp = Blueprint("chat", __name__, url_prefix="/api/chat")

    @bp.route("/verify-identity", methods=["POST"])
    @handle_api_errors
    def verify_identity():
        """Verify customer code or phone number against Firestore customers.
        Dung Firestore query truc tiep thay vi load all customers."""
        t0 = time.time()
        print(f"[verify-identity] START")

        data = request.get_json(silent=True) or {}
        identity = (data.get("identity") or "").strip()
        print(f"[verify-identity] identity='{identity}' parse_json={time.time()-t0:.3f}s")

        if not identity:
            return jsonify({"verified": False, "message": "Vui lòng nhập mã thành viên hoặc số điện thoại"}), 400

        if not customer_service:
            print(f"[verify-identity] No customer_service, allow by default")
            return jsonify({"verified": True, "name": identity, "identity": identity})

        print(f"[verify-identity] customer_service exists, customers_ref={customer_service.customers_ref is not None}")

        password = (data.get("password") or "").strip()

        def _calc_gift_point(c):
            """Calculate gift point matching frontend calculateGiftValue(), minus redeemed."""
            total_point = c.get("TotalPoint", 0) or 0
            raw_gift = total_point * 0.02
            base = round(raw_gift / 100) * 100
            if not isinstance(base, (int, float)) or base != base:  # NaN check
                base = 0
            registration_bonus = c.get("RegistrationBonus", 0) or 0
            bonus_point = c.get("BonusPoint", 0) or 0
            redeemed = c.get("RedeemedPoints", 0) or 0
            return max(0, base + registration_bonus + bonus_point - redeemed)

        def _check_password(c, password):
            """Check password. Returns (ok, hasPassword).
            - No Password field (old customer): ok=True, hasPassword=False
            - Has Password + no password sent: ok=False, requirePassword=True
            - Has Password + password sent: check bcrypt match
            """
            stored_hash = c.get("Password", "")
            if not stored_hash:
                return True, False
            if not password:
                return False, True  # requirePassword
            try:
                if bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
                    return True, True
            except Exception:
                pass
            return False, True

        def _build_response(c, identity_val, phone_val, type_val):
            name = c.get("Name") or ""
            code = c.get("Code") or ""
            gift_point = _calc_gift_point(c)
            ok, has_pw = _check_password(c, password)
            if not ok and not password:
                # Client didn't send password but customer has one → ask for it
                return jsonify({"verified": False, "requirePassword": True, "name": name, "identity": identity_val, "phone": phone_val, "code": code}), 200
            if not ok:
                return jsonify({"verified": False, "message": "Sai mật khẩu"}), 401
            return jsonify({"verified": True, "name": name, "identity": identity_val, "phone": phone_val, "code": code, "type": type_val, "giftPoint": gift_point, "hasPassword": has_pw})

        # Query by Code
        try:
            t1 = time.time()
            print(f"[verify-identity] Querying by Code...")
            for doc in customer_service.customers_ref.where("Code", "==", identity).limit(1).stream():
                c = doc.to_dict() or {}
                phone_val = (c.get("ContactNumber") or "").strip()
                print(f"[verify-identity] Found by Code in {time.time()-t1:.3f}s total={time.time()-t0:.3f}s")
                return _build_response(c, identity, phone_val, "code")
            print(f"[verify-identity] Code query done, no match in {time.time()-t1:.3f}s")
        except Exception as e:
            print(f"[verify-identity] Code query ERROR: {type(e).__name__}: {e} in {time.time()-t1:.3f}s")

        # Query by ContactNumber
        try:
            t2 = time.time()
            print(f"[verify-identity] Querying by ContactNumber...")
            for doc in customer_service.customers_ref.where("ContactNumber", "==", identity).limit(1).stream():
                c = doc.to_dict() or {}
                print(f"[verify-identity] Found by Phone in {time.time()-t2:.3f}s total={time.time()-t0:.3f}s")
                return _build_response(c, identity, identity, "phone")
            print(f"[verify-identity] Phone query done, no match in {time.time()-t2:.3f}s")
        except Exception as e:
            print(f"[verify-identity] Phone query ERROR: {type(e).__name__}: {e} in {time.time()-t2:.3f}s")

        print(f"[verify-identity] NOT FOUND total={time.time()-t0:.3f}s")
        return jsonify({"verified": False, "message": "Không tìm thấy khách hàng với mã/SĐT này"}), 404

    @bp.route("/send", methods=["POST"])
    @handle_api_errors
    def send_message():
        data = request.get_json(silent=True) or {}
        message_text = (data.get("message") or "").strip()
        sender_id = (data.get("senderId") or "").strip()
        if not message_text or not sender_id:
            return jsonify({"status": "error", "message": "senderId and message required"}), 400

        saved = chat_service.send_message(data)

        # Broadcast via WebSocket
        if socketio:
            socketio.emit("message_created", saved, namespace="/api/websocket/messages")

        return jsonify({"status": "ok", "message": saved})

    @bp.route("/conversations", methods=["GET"])
    @handle_api_errors
    def get_conversations():
        conversations = chat_service.get_conversations()

        # Enrich conversations with customer data from Firestore
        if customer_service:
            customers = customer_service.read_all_customers()
            # Build lookup maps: by Code and by ContactNumber
            code_map = {}
            phone_map = {}
            for c in customers:
                if not isinstance(c, dict):
                    continue
                code = (c.get("Code") or "").strip()
                phone = (c.get("ContactNumber") or "").strip()
                if code:
                    code_map[code] = c
                if phone:
                    phone_map[phone] = c

            for conv in conversations:
                conv_id = conv.get("conversationId", "")
                matched = code_map.get(conv_id) or phone_map.get(conv_id)
                if matched:
                    conv["senderName"] = matched.get("Name") or conv.get("senderName", "")
                    conv["conversationCode"] = matched.get("Code") or ""
                    conv["contactNumber"] = matched.get("ContactNumber") or ""

        return jsonify(conversations)

    @bp.route("/change-password", methods=["POST"])
    @handle_api_errors
    def change_password():
        """Change customer password. Old customers (no Password) don't need currentPassword."""
        data = request.get_json(silent=True) or {}
        identity = (data.get("identity") or "").strip()
        new_password = (data.get("newPassword") or "").strip()
        current_password = (data.get("currentPassword") or "").strip()

        if not identity or not new_password:
            return jsonify({"success": False, "message": "Thiếu thông tin"}), 400

        if len(new_password) < 4:
            return jsonify({"success": False, "message": "Mật khẩu phải có ít nhất 4 ký tự"}), 400

        if not customer_service:
            return jsonify({"success": False, "message": "Service unavailable"}), 503

        # Find customer by Code or ContactNumber
        doc_ref = None
        customer_data = None
        for field in ("Code", "ContactNumber"):
            try:
                for doc in customer_service.customers_ref.where(field, "==", identity).limit(1).stream():
                    doc_ref = doc.reference
                    customer_data = doc.to_dict() or {}
                    break
            except Exception:
                pass
            if doc_ref:
                break

        if not doc_ref:
            return jsonify({"success": False, "message": "Không tìm thấy khách hàng"}), 404

        # If customer already has a password, verify current password
        stored_hash = customer_data.get("Password", "")
        if stored_hash and current_password:
            try:
                if not bcrypt.checkpw(current_password.encode("utf-8"), stored_hash.encode("utf-8")):
                    return jsonify({"success": False, "message": "Mật khẩu hiện tại không đúng"}), 401
            except Exception:
                return jsonify({"success": False, "message": "Lỗi xác minh mật khẩu"}), 500

        # Hash and save new password
        hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        doc_ref.update({"Password": hashed})

        return jsonify({"success": True, "message": "Đổi mật khẩu thành công"})

    @bp.route("/messages/<conversation_id>", methods=["GET"])
    @handle_api_errors
    def get_messages(conversation_id):
        limit = request.args.get("limit", 100, type=int)
        messages = chat_service.get_messages(conversation_id, limit=limit)
        return jsonify(messages)

    return bp
