from flask import Blueprint, request, jsonify
from functools import wraps

# Import từ firebase_auth module (project riêng cho authentication)
from firebase.firebase_auth.auth_firebase_setup import verify_firebase_token
from firebase.firebase_auth.user_management import UserManager

from Utility.get_env import UserName, Password, LatestBranchId, retailer
from FromKiotViet.get_authorization import get_authen_with_credentials

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')
user_manager = UserManager()


def require_auth(f):
    """Decorator to require Firebase authentication for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid authorization header"}), 401
        
        token = auth_header.split('Bearer ')[1]
        
        try:
            decoded_token = verify_firebase_token(token)
            request.user = decoded_token
            return f(*args, **kwargs)
        except ValueError as e:
            return jsonify({"error": str(e)}), 401
    
    return decorated_function


@auth_bp.route('/verify-email', methods=['POST'])
def verify_email():
    """Check if email is allowed before completing login."""
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    
    if not email:
        return jsonify({"error": "Email is required"}), 400
    
    if not user_manager.is_email_allowed(email):
        return jsonify({
            "error": "Email không được phép đăng nhập",
            "allowed": False
        }), 403
    
    return jsonify({
        "message": "Email is allowed",
        "allowed": True
    }), 200


@auth_bp.route('/login', methods=['POST'])
def login():
    """Complete login after Google Sign-In."""
    data = request.get_json()
    firebase_id_token = data.get('id_token')
    
    if not firebase_id_token:
        return jsonify({"error": "Firebase ID token is required"}), 400
    
    try:
        # Verify Firebase token using AUTH project
        decoded_token = verify_firebase_token(firebase_id_token)
        
        firebase_uid = decoded_token['uid']
        email = decoded_token.get('email', '')
        display_name = decoded_token.get('name', '')
        photo_url = decoded_token.get('picture', '')
        
        # Check if email is allowed
        if not user_manager.is_email_allowed(email):
            return jsonify({"error": "Email không được phép đăng nhập"}), 403
        
        # Get or create user in Firestore
        user = user_manager.get_or_create_user(email, firebase_uid, display_name, photo_url)
        
        # Generate refresh token
        refresh_token = user_manager.generate_refresh_token(firebase_uid)
        
        # Get KiotViet token
        kiotviet_token = get_authen_with_credentials(UserName, Password, LatestBranchId, retailer)
        
        return jsonify({
            "success": True,
            "user": {
                "uid": firebase_uid,
                "email": email,
                "display_name": display_name,
                "photo_url": photo_url
            },
            "refresh_token": refresh_token,
            "kiotviet": {
                "access_token": kiotviet_token,
                "retailer": retailer,
                "branch_id": LatestBranchId
            }
        }), 200
        
    except ValueError as e:
        print(f"[AUTH ERROR] {str(e)}")
        return jsonify({"error": str(e)}), 401


@auth_bp.route('/refresh', methods=['POST'])
def refresh_token():
    """Refresh authentication using refresh token."""
    data = request.get_json()
    refresh_token_value = data.get('refresh_token')
    
    if not refresh_token_value:
        return jsonify({"error": "Refresh token is required"}), 400
    
    firebase_uid = user_manager.validate_refresh_token(refresh_token_value)
    
    if not firebase_uid:
        return jsonify({"error": "Invalid or expired refresh token"}), 401
    
    kiotviet_token = get_authen_with_credentials(UserName, Password, LatestBranchId, retailer)
    
    return jsonify({
        "success": True,
        "kiotviet": {
            "access_token": kiotviet_token,
            "retailer": retailer,
            "branch_id": LatestBranchId
        }
    }), 200


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logout and revoke refresh token."""
    data = request.get_json()
    refresh_token_value = data.get('refresh_token')
    
    if refresh_token_value:
        user_manager.revoke_refresh_token(refresh_token_value)
    
    return jsonify({"success": True, "message": "Logged out successfully"}), 200


@auth_bp.route('/me', methods=['GET'])
@require_auth
def get_current_user():
    """Get current authenticated user info."""
    return jsonify({
        "uid": request.user['uid'],
        "email": request.user.get('email', ''),
        "display_name": request.user.get('name', '')
    }), 200