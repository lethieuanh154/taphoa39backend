"""Firestore service for chat messages.

Uses FIREBASE_SERVICE_ACCOUNT_CUSTOMER for storage.
Collection: chatMessages
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from firebase.init_firebase import init_firestore

COLLECTION_NAME = "chatMessages"

db = init_firestore("FIREBASE_SERVICE_ACCOUNT_CUSTOMER")
messages_ref = db.collection(COLLECTION_NAME)


class FirestoreChatService:
    def __init__(self):
        self.messages_ref = messages_ref

    def send_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Save a chat message to Firestore. Returns the saved message with id."""
        doc = {
            "senderId": data.get("senderId", ""),
            "senderName": data.get("senderName", ""),
            "senderType": data.get("senderType", "customer"),
            "message": data.get("message", ""),
            "conversationId": data.get("conversationId", data.get("senderId", "")),
            "timestamp": datetime.now().isoformat(),
        }
        _, doc_ref = self.messages_ref.add(doc)
        doc["id"] = doc_ref.id
        return doc

    def get_messages(self, conversation_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get messages for a conversation, ordered by timestamp."""
        # Filter only — no order_by to avoid needing a composite index
        query = self.messages_ref.where("conversationId", "==", conversation_id)
        results = []
        for doc in query.stream():
            item = doc.to_dict()
            item["id"] = doc.id
            results.append(item)
        # Sort in Python and apply limit
        results.sort(key=lambda m: m.get("timestamp", ""))
        return results[:limit]

    def get_conversations(self) -> List[Dict[str, Any]]:
        """Get unique conversations with last message info for staff view."""
        # Fetch recent messages ordered by timestamp desc
        query = self.messages_ref.order_by("timestamp", direction="DESCENDING").limit(500)

        conversations: Dict[str, Dict[str, Any]] = {}
        for doc in query.stream():
            item = doc.to_dict()
            conv_id = item.get("conversationId", "")
            if not conv_id:
                continue
            if conv_id not in conversations:
                conversations[conv_id] = {
                    "conversationId": conv_id,
                    "senderName": item.get("senderName", conv_id),
                    "lastMessage": item.get("message", ""),
                    "lastTimestamp": item.get("timestamp", ""),
                    "senderType": item.get("senderType", "customer"),
                }

        return sorted(
            conversations.values(),
            key=lambda c: c.get("lastTimestamp", ""),
            reverse=True,
        )
