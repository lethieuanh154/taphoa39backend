"""REST API routes for chat messages."""
from __future__ import annotations
import time

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

        # Query by Code
        try:
            t1 = time.time()
            print(f"[verify-identity] Querying by Code...")
            for doc in customer_service.customers_ref.where("Code", "==", identity).limit(1).stream():
                c = doc.to_dict() or {}
                name = c.get("Name") or ""
                phone = (c.get("ContactNumber") or "").strip()
                print(f"[verify-identity] Found by Code: name='{name}' in {time.time()-t1:.3f}s total={time.time()-t0:.3f}s")
                return jsonify({"verified": True, "name": name, "identity": identity, "phone": phone, "type": "code"})
            print(f"[verify-identity] Code query done, no match in {time.time()-t1:.3f}s")
        except Exception as e:
            print(f"[verify-identity] Code query ERROR: {type(e).__name__}: {e} in {time.time()-t1:.3f}s")

        # Query by ContactNumber
        try:
            t2 = time.time()
            print(f"[verify-identity] Querying by ContactNumber...")
            for doc in customer_service.customers_ref.where("ContactNumber", "==", identity).limit(1).stream():
                c = doc.to_dict() or {}
                name = c.get("Name") or ""
                print(f"[verify-identity] Found by Phone: name='{name}' in {time.time()-t2:.3f}s total={time.time()-t0:.3f}s")
                return jsonify({"verified": True, "name": name, "identity": identity, "phone": identity, "type": "phone"})
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

    @bp.route("/messages/<conversation_id>", methods=["GET"])
    @handle_api_errors
    def get_messages(conversation_id):
        limit = request.args.get("limit", 100, type=int)
        messages = chat_service.get_messages(conversation_id, limit=limit)
        return jsonify(messages)

    return bp
