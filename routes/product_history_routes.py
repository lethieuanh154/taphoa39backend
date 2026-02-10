"""
Product History Routes
API lịch sử thay đổi sản phẩm - lưu trên Firestore để đồng bộ giữa các máy
Collection: product_history/{productId}
"""

from flask import Blueprint, jsonify, request
from firebase.init_firebase import init_firestore
from datetime import datetime

bp = Blueprint('product_history', __name__, url_prefix='/api/product-history')

# Dùng chung Firestore project với products
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_PRODUCT", app_name="product_app")
COLLECTION = 'product_history'
MAX_RECORDS = 100


@bp.route('/<product_id>', methods=['GET'])
def get_history(product_id):
    """Lấy lịch sử thay đổi của 1 sản phẩm"""
    try:
        doc = db.collection(COLLECTION).document(product_id).get()
        if doc.exists:
            return jsonify(doc.to_dict())
        return jsonify({'productId': product_id, 'records': []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<product_id>', methods=['POST'])
def add_records(product_id):
    """
    Thêm records vào lịch sử.
    Body: { productCode, productName, records: [{ field, fieldLabel, oldValue, newValue, changedBy? }] }
    """
    try:
        body = request.get_json()
        if not body or not body.get('records'):
            return jsonify({'error': 'Missing records'}), 400

        doc_ref = db.collection(COLLECTION).document(product_id)
        doc = doc_ref.get()

        if doc.exists:
            data = doc.to_dict()
            existing_records = data.get('records', [])
        else:
            existing_records = []

        # Thêm timestamp cho mỗi record mới
        now = datetime.now().isoformat()
        new_records = []
        for r in body['records']:
            new_records.append({
                'timestamp': r.get('timestamp', now),
                'field': r['field'],
                'fieldLabel': r['fieldLabel'],
                'oldValue': r['oldValue'],
                'newValue': r['newValue'],
                'changedBy': r.get('changedBy', '')
            })

        all_records = existing_records + new_records

        # Giữ tối đa MAX_RECORDS, ưu tiên mới nhất
        if len(all_records) > MAX_RECORDS:
            all_records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            all_records = all_records[:MAX_RECORDS]

        doc_data = {
            'productId': product_id,
            'productCode': body.get('productCode', ''),
            'productName': body.get('productName', ''),
            'records': all_records,
            'updatedAt': now
        }

        doc_ref.set(doc_data)
        return jsonify(doc_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<product_id>', methods=['DELETE'])
def clear_history(product_id):
    """Xóa lịch sử của 1 sản phẩm"""
    try:
        db.collection(COLLECTION).document(product_id).delete()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
