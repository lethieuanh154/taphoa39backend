"""
User management for authentication. 
Stores user sessions in Firestore (using AUTH project).
"""

from datetime import datetime, timedelta
from typing import Optional
import secrets
import hashlib
import os
import json
from dotenv import load_dotenv
from google.cloud import firestore

# Load .env from firebase folder
load_dotenv(os. path.join(os.path.dirname(__file__), '.. ', '.env'))


# Allowed emails (whitelist)
ALLOWED_EMAILS = [
    "lethieuanh89@gmail.com",
    "minhanh.hoavang@gmail.com"
    # Thêm email được phép vào đây
]


def _get_auth_firestore():
    """Get Firestore client for auth project."""
    from firebase. init_firebase import init_firestore
    return init_firestore("FIREBASE_SERVICE_ACCOUNT_AUTH", app_name="auth_firestore_app")


class UserManager:
    """Manage user sessions and tokens in Firestore."""
    
    COLLECTION_NAME = "users"
    SESSIONS_COLLECTION = "sessions"
    REFRESH_TOKEN_EXPIRY_DAYS = 30
    
    def __init__(self):
        self.db = _get_auth_firestore()
    
    def is_email_allowed(self, email: str) -> bool:
        """Check if email is in the allowed list."""
        if not email:
            return False
        normalized = email.lower(). strip()
        return normalized in [e.lower() for e in ALLOWED_EMAILS]
    
    def get_or_create_user(self, email: str, firebase_uid: str, display_name: str = None, photo_url: str = None) -> dict:
        """
        Get existing user or create new user document in Firestore. 
        
        Args:
            email: User's email
            firebase_uid: Firebase Authentication UID
            display_name: User's display name from Google
            photo_url: User's photo URL from Google
            
        Returns:
            User document data
        """
        user_ref = self.db. collection(self. COLLECTION_NAME). document(firebase_uid)
        user_doc = user_ref. get()
        
        if user_doc.exists:
            # Update last login
            user_ref.update({
                "last_login": datetime.utcnow(),
                "updated_at": datetime. utcnow(),
                "display_name": display_name,
                "photo_url": photo_url
            })
            return user_doc. to_dict()
        else:
            # Create new user
            user_data = {
                "email": email,
                "firebase_uid": firebase_uid,
                "display_name": display_name,
                "photo_url": photo_url,
                "created_at": datetime.utcnow(),
                "updated_at": datetime. utcnow(),
                "last_login": datetime.utcnow(),
                "is_active": True
            }
            user_ref.set(user_data)
            return user_data
    
    def generate_refresh_token(self, firebase_uid: str) -> str:
        """Generate and store a secure refresh token."""
        refresh_token = secrets. token_urlsafe(64)
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        
        session_ref = self.db. collection(self. SESSIONS_COLLECTION). document()
        session_data = {
            "user_id": firebase_uid,
            "token_hash": token_hash,
            "created_at": datetime. utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=self.REFRESH_TOKEN_EXPIRY_DAYS),
            "is_valid": True
        }
        session_ref.set(session_data)
        
        return refresh_token
    
    def validate_refresh_token(self, refresh_token: str) -> Optional[str]:
        """Validate refresh token and return user ID if valid."""
        token_hash = hashlib.sha256(refresh_token.encode()). hexdigest()
        
        sessions_ref = self. db.collection(self.SESSIONS_COLLECTION)
        query = sessions_ref. where("token_hash", "==", token_hash). where("is_valid", "==", True). limit(1)
        
        docs = query.stream()
        for doc in docs:
            session = doc.to_dict()
            if session. get("expires_at") and session["expires_at"]. replace(tzinfo=None) > datetime.utcnow():
                return session. get("user_id")
            else:
                doc.reference.update({"is_valid": False})
        
        return None
    
    def revoke_refresh_token(self, refresh_token: str) -> bool:
        """Revoke a refresh token."""
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        
        sessions_ref = self. db.collection(self.SESSIONS_COLLECTION)
        query = sessions_ref. where("token_hash", "==", token_hash). limit(1)
        
        docs = query.stream()
        for doc in docs:
            doc.reference.update({"is_valid": False})
            return True
        
        return False