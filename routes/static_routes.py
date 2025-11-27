from __future__ import annotations

import os
from flask import Blueprint, abort, current_app, send_from_directory


def create_static_routes_bp() -> Blueprint:
    bp = Blueprint("static_routes", __name__)

    @bp.route("/")
    def serve_index():
        return send_from_directory(current_app.static_folder, "index.html")

    @bp.route("/<path:path>")
    def serve_static_files(path: str):
        # Allow socket.io traffic to be handled by the SocketIO server.
        # Only serve static files for other paths; if path exists serve it,
        # otherwise fall back to index.html for SPA routing.
        full_path = os.path.join(current_app.static_folder, path)
        if os.path.exists(full_path):
            return send_from_directory(current_app.static_folder, path)

        return send_from_directory(current_app.static_folder, "index.html")

    return bp
