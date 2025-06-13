import json
import firebase_admin
from firebase_admin import credentials, firestore
import os

def init_firestore(account, app_name=None):
    service_account_json = os.environ.get(account)
    if not service_account_json:
        raise Exception(f"Missing {account} environment variable.")

    cred_dict = json.loads(service_account_json)
    if not app_name:
        app_name = account  # Dùng tên biến môi trường làm tên app

    # Nếu app đã tồn tại thì lấy app, chưa thì khởi tạo mới
    try:
        app = firebase_admin.get_app(app_name)
    except ValueError:
        cred = credentials.Certificate(cred_dict)
        app = firebase_admin.initialize_app(cred, name=app_name)
    db = firestore.client(app=app)
    return db