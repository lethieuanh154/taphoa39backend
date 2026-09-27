"""Socket.IO namespace registration.

This module provides lightweight Namespace implementations so clients can
connect to the server and receive emitted events. The namespaces intentionally
do not implement application logic — events are emitted from the REST
endpoints (see `routes/shared.py`) using the `socketio.emit` API. These
Namespace classes exist to accept connections and optionally allow clients to
subscribe to rooms in the future.
"""

from __future__ import annotations

import os

from flask_socketio import Namespace, join_room, leave_room, rooms
from flask import request
from typing import Any
from flask_socketio import SocketIO

# Simple in-memory pending notifications store.
# Key: namespace string (e.g. '/api/websocket/invoices'), value: list of payloads
_PENDING_NOTIFICATIONS: dict[str, list[Any]] = {}


def add_pending_notification(namespace: str, payload: Any) -> None:
    """Add a pending notification for the given namespace.

    REST routes can call this when they want to notify clients but also
    support the case where no clients are currently connected. Use
    `emit_or_queue` if you have a `socketio` instance available and want
    to emit immediately when possible.
    """
    lst = _PENDING_NOTIFICATIONS.setdefault(namespace, [])
    lst.append(payload)


def clear_pending_notifications(namespace: str) -> None:
    _PENDING_NOTIFICATIONS.pop(namespace, None)


def emit_or_queue(socketio: SocketIO, namespace: str, event: str = 'notify', payload: Any = None) -> None:
    """Emit to connected clients in `namespace` if any; otherwise queue the payload.

    This helper is safe to call from REST routes that have access to the
    `socketio` instance (for example via `current_app.socketio`). It will
    attempt to emit to the namespace; if no clients are connected, the
    payload is stored in the pending list so future connects receive it.
    """
    try:
        # Attempt to emit to namespace. If no clients are connected, this is a no-op on the server,
        # but we cannot definitively know from here; to be conservative, if emitting doesn't
        # raise, also add to pending so clients that connect later will receive it.
        socketio.emit(event, payload, namespace=namespace)
    except Exception:
        # If emit fails, just queue
        add_pending_notification(namespace, payload)
        return
    # Also queue the payload so newly connected clients will see it on connect.
    add_pending_notification(namespace, payload)



class BaseNamespace(Namespace):
    def __init__(self, namespace: str):
        super().__init__(namespace)
        self._namespace = namespace

    def on_connect(self):  # pragma: no cover - thin wrapper
        print(f"Client connected to namespace {self._namespace}")
        # When a client connects, emit any pending notifications that were queued
        pending = _PENDING_NOTIFICATIONS.get(self._namespace)
        if pending:
            try:
                # Emit each pending payload using the 'notify' event name.
                for payload in list(pending):
                    try:
                        # emit only to this client/namespace
                        self.emit('notify', payload)
                    except Exception:
                        # swallow per-item errors
                        pass
                # Once emitted to the connecting client, clear pending notifications for this namespace.
                _PENDING_NOTIFICATIONS.pop(self._namespace, None)
            except Exception:
                pass
        # If there's a pending last-notify for this namespace, send it to the
        # newly connected client so they immediately know the latest change.
        try:
            last = LAST_NOTIFIES.get(self._namespace)
            if last:
                # emit only to this connected socket
                self.emit(last.get("event"), last.get("data"), room=request.sid)
        except Exception:
            pass

    def on_disconnect(self):  # pragma: no cover - thin wrapper
        print(f"Client disconnected from namespace {self._namespace}")

    # Optional: allow clients to subscribe to rooms in a namespace
    def on_subscribe(self, data: Any):  # pragma: no cover - convenience event
        # data expected: {"rooms": ["room1", ...]}
        rooms = data.get("rooms") if isinstance(data, dict) else None
        if not rooms:
            return
        for r in rooms:
            try:
                join_room(r, sid=request.sid, namespace=self._namespace)
            except Exception:
                pass


PRODUCTS_NS = '/api/websocket/products'
# Namespace products dung chung cho DatHang (khach, khong login) va BanHang/Management (nhan vien).
# Payload noi bo (Cost, OnHandNV, Description, hang gop...) CHI gui vao STAFF_ROOM;
# PUBLIC_ROOM nhan ban da loc (xem routes/shared.py `_public_ws_product`).
STAFF_ROOM = 'staff'
PUBLIC_ROOM = 'public'


def _ws_auth_enforced() -> bool:
    """Cung co voi admin-auth REST: tat (BE local tai quay) -> moi client la staff nhu truoc."""
    return os.getenv("ENFORCE_ADMIN_AUTH", "false").lower() in ("1", "true", "yes")


def _verify_staff_token(token: Any) -> bool:
    if not token or not isinstance(token, str):
        return False
    try:
        from firebase.firebase_auth.auth_firebase_setup import verify_firebase_token
        return bool(verify_firebase_token(token.strip()))
    except Exception:
        return False


class ProductsRoomNamespace(BaseNamespace):
    """Client moi vao PUBLIC_ROOM; gui event `authenticate` {idToken} hop le -> chuyen sang STAFF_ROOM."""

    def on_connect(self, auth: Any = None):  # pragma: no cover - thin wrapper
        token = auth.get('idToken') if isinstance(auth, dict) else None
        self._enter_room(not _ws_auth_enforced() or _verify_staff_token(token))

    def on_authenticate(self, data: Any):  # pragma: no cover - thin wrapper
        token = data.get('idToken') if isinstance(data, dict) else None
        if not _verify_staff_token(token):
            return {'ok': False}
        if STAFF_ROOM not in rooms(sid=request.sid, namespace=self._namespace):
            self._enter_room(True)
        return {'ok': True}

    def _enter_room(self, staff: bool) -> None:
        sid = request.sid
        if staff:
            leave_room(PUBLIC_ROOM, sid=sid, namespace=self._namespace)
            join_room(STAFF_ROOM, sid=sid, namespace=self._namespace)
        else:
            join_room(PUBLIC_ROOM, sid=sid, namespace=self._namespace)
        try:
            last = LAST_NOTIFIES.get(self._namespace)
            if last:
                data = last.get("data") if staff else last.get("public_data")
                if data is not None:
                    self.emit(last.get("event"), data, room=sid)
        except Exception:
            pass

    def on_subscribe(self, data: Any):  # pragma: no cover - khong cho tu join STAFF_ROOM
        return None


def register_namespaces(socketio) -> None:
    """Register the Socket.IO namespaces with the provided `socketio` server.

    This function should be called after `SocketIO(app)` is created.
    """
    if not socketio:
        return

    socketio.on_namespace(ProductsRoomNamespace(PRODUCTS_NS))
    socketio.on_namespace(BaseNamespace('/api/websocket/customers'))
    socketio.on_namespace(BaseNamespace('/api/websocket/invoices'))
    socketio.on_namespace(BaseNamespace('/api/websocket/orders'))
    socketio.on_namespace(BaseNamespace('/api/websocket/messages'))


# In-memory store for last notifications per namespace. Structure:
# { namespace_path: { 'event': <event_name>, 'data': <payload> } }
# This is process-local and intended for single-process dev use.
LAST_NOTIFIES = {}


def set_last_notify(namespace: str, event: str, data: object, public_data: object = None) -> None:
    """`public_data` chi dung cho PRODUCTS_NS: ban da loc replay cho PUBLIC_ROOM (None = khong replay)."""
    try:
        if not namespace:
            return
        LAST_NOTIFIES[namespace] = {"event": event, "data": data, "public_data": public_data}
    except Exception:
        pass

