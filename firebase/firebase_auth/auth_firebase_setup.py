"""
Firebase Admin SDK setup for Authentication. 
Uses separate Firebase project (FIREBASE_SERVICE_ACCOUNT_AUTH) to avoid conflicts
with other Firebase projects (HANGHOA, HOADON, CUSTOMER).
"""

import os
import json
import firebase_admin
from firebase_admin import credentials, auth
from dotenv import load_dotenv

# Load . env from firebase folder
load_dotenv(os.path.join(os.path. dirname(__file__), '..', '. env'))

# App name to avoid conflicts with other Firebase apps
AUTH_APP_NAME = "auth_app"

_auth_app = None


def _get_auth_app():
    """Get or initialize the Firebase Auth app."""
    global _auth_app
    
    if _auth_app is not None:
        return _auth_app
    
    # Check if app already exists
    try:
        _auth_app = firebase_admin.get_app(AUTH_APP_NAME)
        return _auth_app
    except ValueError:
        pass  # App doesn't exist, create it
    
    # Get service account from environment
    service_account_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_AUTH')
    
    if not service_account_json:
        raise ValueError(
            "FIREBASE_SERVICE_ACCOUNT_AUTH environment variable is not set.  "
            "Please add it to firebase/. env file."
        )
    
    try:
        cred_dict = json.loads(service_account_json)
        cred = credentials.Certificate(cred_dict)
        _auth_app = firebase_admin.initialize_app(cred, name=AUTH_APP_NAME)
        print(f"[AUTH] Initialized Firebase Auth app with project: {cred_dict.get('project_id')}")
        return _auth_app
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in FIREBASE_SERVICE_ACCOUNT_AUTH: {e}")


def verify_firebase_token(id_token: str) -> dict:
    """
    Verify Firebase ID token and return decoded token data.
    
    Args:
        id_token: Firebase ID token from client (Google Sign-In)
        
    Returns:
        Decoded token data containing user info (uid, email, name, picture, etc.)
        
    Raises:
        ValueError: If token is invalid, expired, or revoked
    """
    app = _get_auth_app()
    
    try:
        # Verify token with the specific auth app
        decoded_token = auth.verify_id_token(id_token, app=app, check_revoked=True)
        return decoded_token
    except auth.RevokedIdTokenError:
        raise ValueError("Token has been revoked")
    except auth.ExpiredIdTokenError:
        raise ValueError("Token has expired")
    except auth.InvalidIdTokenError as e:
        raise ValueError(f"Invalid token: {str(e)}")
    except Exception as e:
        raise ValueError(f"Token verification failed: {str(e)}")


def get_user_by_email(email: str):
    """
    Get Firebase user by email. 
    
    Args:
        email: User's email address
        
    Returns:
        Firebase UserRecord or None if not found
    """
    app = _get_auth_app()
    
    try:
        user = auth.get_user_by_email(email, app=app)
        return user
    except auth.UserNotFoundError:
        return None


def create_custom_token(uid: str, additional_claims: dict = None) -> str:
    """
    Create a custom token for a user. 
    
    Args:
        uid: User's Firebase UID
        additional_claims: Optional additional claims to include in token
        
    Returns:
        Custom token string
    """
    app = _get_auth_app()
    return auth.create_custom_token(uid, additional_claims, app=app)