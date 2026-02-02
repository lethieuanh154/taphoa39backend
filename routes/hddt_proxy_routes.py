"""
HDDT PROXY ROUTES
Proxy để gọi API từ hoadondientu.gdt.gov.vn
Tránh vấn đề CORS khi gọi từ frontend
"""

import logging
import requests
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint('hddt_proxy', __name__, url_prefix='/api/hddt')

HDDT_API_BASE = 'https://hoadondientu.gdt.gov.vn:30000'


def get_auth_header():
    """Lấy Authorization header từ request"""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None
    return auth_header


@bp.route('/purchase', methods=['GET'])
def get_purchase_invoices():
    """
    Proxy cho API lấy hóa đơn mua vào
    GET /query/invoices/purchase

    Query params:
        - sort: Sắp xếp (default: tdlap:desc)
        - size: Số lượng (default: 50)
        - search: Search query
    """
    try:
        auth_header = get_auth_header()
        if not auth_header:
            return jsonify({'error': 'Missing Authorization header'}), 401

        # Forward query params
        sort = request.args.get('sort', 'tdlap:desc')
        size = request.args.get('size', '50')
        search = request.args.get('search', '')

        url = f"{HDDT_API_BASE}/query/invoices/purchase"
        params = {
            'sort': sort,
            'size': size,
            'search': search
        }

        headers = {
            'Authorization': auth_header,
            'Content-Type': 'application/json'
        }

        logger.info(f"[HDDT Proxy] GET {url} with params: {params}")

        response = requests.get(url, params=params, headers=headers, timeout=30, verify=True)

        if response.status_code == 200:
            return jsonify(response.json())
        else:
            logger.error(f"[HDDT Proxy] Error: {response.status_code} - {response.text}")
            return jsonify({
                'error': f'HDDT API Error: {response.status_code}',
                'detail': response.text
            }), response.status_code

    except requests.exceptions.Timeout:
        logger.error("[HDDT Proxy] Request timeout")
        return jsonify({'error': 'Request timeout'}), 504
    except requests.exceptions.RequestException as e:
        logger.error(f"[HDDT Proxy] Request error: {e}")
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Unexpected error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-sco', methods=['GET'])
def get_purchase_invoices_sco():
    """
    Proxy cho API lấy hóa đơn mua vào từ máy tính tiền (SCO)
    GET /sco-query/invoices/purchase
    ttxly==8: Hóa đơn khởi tạo từ máy tính tiền
    """
    try:
        auth_header = get_auth_header()
        if not auth_header:
            return jsonify({'error': 'Missing Authorization header'}), 401

        # Forward query params
        sort = request.args.get('sort', 'tdlap:desc')
        size = request.args.get('size', '50')
        search = request.args.get('search', '')

        url = f"{HDDT_API_BASE}/sco-query/invoices/purchase"
        params = {
            'sort': sort,
            'size': size,
            'search': search
        }

        headers = {
            'Authorization': auth_header,
            'Content-Type': 'application/json'
        }

        logger.info(f"[HDDT Proxy] GET {url} with params: {params}")

        response = requests.get(url, params=params, headers=headers, timeout=30, verify=True)

        if response.status_code == 200:
            return jsonify(response.json())
        else:
            logger.error(f"[HDDT Proxy] Error: {response.status_code} - {response.text}")
            return jsonify({
                'error': f'HDDT API Error: {response.status_code}',
                'detail': response.text
            }), response.status_code

    except requests.exceptions.Timeout:
        logger.error("[HDDT Proxy] Request timeout")
        return jsonify({'error': 'Request timeout'}), 504
    except requests.exceptions.RequestException as e:
        logger.error(f"[HDDT Proxy] Request error: {e}")
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Unexpected error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/sold', methods=['GET'])
def get_sold_invoices():
    """
    Proxy cho API lấy hóa đơn bán ra (sold invoices)
    GET /sco-query/invoices/sold

    Query params:
        - sort: Sắp xếp (default: tdlap:desc)
        - size: Số lượng (default: 50)
        - search: Search query
    """
    try:
        auth_header = get_auth_header()
        if not auth_header:
            return jsonify({'error': 'Missing Authorization header'}), 401

        # Forward query params
        sort = request.args.get('sort', 'tdlap:desc')
        size = request.args.get('size', '50')
        search = request.args.get('search', '')

        url = f"{HDDT_API_BASE}/sco-query/invoices/sold"
        params = {
            'sort': sort,
            'size': size,
            'search': search
        }

        headers = {
            'Authorization': auth_header,
            'Content-Type': 'application/json'
        }

        logger.info(f"[HDDT Proxy] GET {url} with params: {params}")

        response = requests.get(url, params=params, headers=headers, timeout=30, verify=True)

        if response.status_code == 200:
            return jsonify(response.json())
        else:
            logger.error(f"[HDDT Proxy] Error: {response.status_code} - {response.text}")
            return jsonify({
                'error': f'HDDT API Error: {response.status_code}',
                'detail': response.text
            }), response.status_code

    except requests.exceptions.Timeout:
        logger.error("[HDDT Proxy] Request timeout")
        return jsonify({'error': 'Request timeout'}), 504
    except requests.exceptions.RequestException as e:
        logger.error(f"[HDDT Proxy] Request error: {e}")
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Unexpected error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/sold-detail', methods=['GET'])
def get_sold_invoice_detail():
    """
    Proxy cho API lấy chi tiết hóa đơn bán ra theo params
    GET /sco-query/invoices/detail?nbmst=xxx&khhdon=xxx&shdon=xxx&khmshdon=xxx

    Query params:
        - nbmst: Mã số thuế người bán
        - khhdon: Ký hiệu hóa đơn
        - shdon: Số hóa đơn
        - khmshdon: Ký hiệu mẫu số hóa đơn
    """
    try:
        auth_header = get_auth_header()
        if not auth_header:
            return jsonify({'error': 'Missing Authorization header'}), 401

        # Lấy query params
        nbmst = request.args.get('nbmst')
        khhdon = request.args.get('khhdon')
        shdon = request.args.get('shdon')
        khmshdon = request.args.get('khmshdon')

        if not all([nbmst, khhdon, shdon, khmshdon]):
            return jsonify({'error': 'Missing required params: nbmst, khhdon, shdon, khmshdon'}), 400

        # API chi tiết hóa đơn bán ra dùng /sco-query/invoices/detail
        url = f"{HDDT_API_BASE}/sco-query/invoices/detail"
        params = {
            'nbmst': nbmst,
            'khhdon': khhdon,
            'shdon': shdon,
            'khmshdon': khmshdon
        }

        headers = {
            'Authorization': auth_header,
            'Content-Type': 'application/json'
        }

        logger.info(f"[HDDT Proxy] GET {url} with params: {params}")

        response = requests.get(url, params=params, headers=headers, timeout=30, verify=True)

        if response.status_code == 200:
            return jsonify(response.json())
        else:
            logger.error(f"[HDDT Proxy] Error: {response.status_code} - {response.text}")
            return jsonify({
                'error': f'HDDT API Error: {response.status_code}',
                'detail': response.text
            }), response.status_code

    except requests.exceptions.Timeout:
        logger.error("[HDDT Proxy] Request timeout")
        return jsonify({'error': 'Request timeout'}), 504
    except requests.exceptions.RequestException as e:
        logger.error(f"[HDDT Proxy] Request error: {e}")
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Unexpected error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/invoice/<invoice_id>', methods=['GET'])
def get_invoice_detail_by_id(invoice_id):
    """
    Proxy cho API lấy chi tiết hóa đơn theo ID
    GET /query/invoices/{invoice_id}
    """
    try:
        auth_header = get_auth_header()
        if not auth_header:
            return jsonify({'error': 'Missing Authorization header'}), 401

        url = f"{HDDT_API_BASE}/query/invoices/{invoice_id}"

        headers = {
            'Authorization': auth_header,
            'Content-Type': 'application/json'
        }

        logger.info(f"[HDDT Proxy] GET {url}")

        response = requests.get(url, headers=headers, timeout=30, verify=True)

        if response.status_code == 200:
            return jsonify(response.json())
        else:
            logger.error(f"[HDDT Proxy] Error: {response.status_code} - {response.text}")
            return jsonify({
                'error': f'HDDT API Error: {response.status_code}',
                'detail': response.text
            }), response.status_code

    except Exception as e:
        logger.exception(f"[HDDT Proxy] Error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/detail', methods=['GET'])
def get_invoice_detail():
    """
    Proxy cho API lấy chi tiết hóa đơn theo params
    GET /query/invoices/detail?nbmst=xxx&khhdon=xxx&shdon=xxx&khmshdon=xxx

    Query params:
        - nbmst: Mã số thuế người bán
        - khhdon: Ký hiệu hóa đơn
        - shdon: Số hóa đơn
        - khmshdon: Ký hiệu mẫu số hóa đơn
    """
    try:
        auth_header = get_auth_header()
        if not auth_header:
            return jsonify({'error': 'Missing Authorization header'}), 401

        # Lấy query params
        nbmst = request.args.get('nbmst')
        khhdon = request.args.get('khhdon')
        shdon = request.args.get('shdon')
        khmshdon = request.args.get('khmshdon')

        if not all([nbmst, khhdon, shdon, khmshdon]):
            return jsonify({'error': 'Missing required params: nbmst, khhdon, shdon, khmshdon'}), 400

        url = f"{HDDT_API_BASE}/query/invoices/detail"
        params = {
            'nbmst': nbmst,
            'khhdon': khhdon,
            'shdon': shdon,
            'khmshdon': khmshdon
        }

        headers = {
            'Authorization': auth_header,
            'Content-Type': 'application/json'
        }

        logger.info(f"[HDDT Proxy] GET {url} with params: {params}")

        response = requests.get(url, params=params, headers=headers, timeout=30, verify=True)

        if response.status_code == 200:
            return jsonify(response.json())
        else:
            logger.error(f"[HDDT Proxy] Error: {response.status_code} - {response.text}")
            return jsonify({
                'error': f'HDDT API Error: {response.status_code}',
                'detail': response.text
            }), response.status_code

    except requests.exceptions.Timeout:
        logger.error("[HDDT Proxy] Request timeout")
        return jsonify({'error': 'Request timeout'}), 504
    except requests.exceptions.RequestException as e:
        logger.error(f"[HDDT Proxy] Request error: {e}")
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Unexpected error: {e}")
        return jsonify({'error': str(e)}), 500
