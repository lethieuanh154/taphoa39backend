"""
HDDT PROXY ROUTES
Proxy để gọi API từ hoadondientu.gdt.gov.vn
Tránh vấn đề CORS khi gọi từ frontend
"""

import logging
import re
import requests
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint('hddt_proxy', __name__, url_prefix='/api/hddt')

HDDT_API_BASE = 'https://hoadondientu.gdt.gov.vn:30000'


# ==================== SVG CAPTCHA SOLVER ====================

# Fingerprint patterns cho mỗi ký tự (A-Z, 0-9)
# Mỗi pattern là chuỗi các SVG path commands (M, Q, Z) đặc trưng cho ký tự đó
CAPTCHA_PATTERNS = {
    'MQQQQQZMQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQZMQQZ': 'A',
    'MQQQQQQQQQZMQQQQQQZMQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQZMQQQQQQQQZMQQQQQQQQZ': 'B',
    'MQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQZ': 'C',
    'MQQQQQQQQZMQQQQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQZ': 'D',
    'MQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': 'E',
    'MQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQZ': 'F',
    'MQQQQQQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': 'G',
    'MQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQZ': 'H',
    'MQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQZ': 'J',
    'MQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQZ': 'K',
    'MQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQZ': 'M',
    'MQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQZ': 'N',
    'MQQQQQQZMQQQQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQQZ': 'P',
    'MQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQZ': 'Q',
    'MQQQQQQZMQQQQQQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQQZ': 'R',
    'MQQQQQQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': 'S',
    'MQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQZ': 'T',
    'MQQQQQQQQQQZMQQQQQQQQQQQQQQQQZ': 'V',
    'MQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': 'W',
    'MQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQZ': 'X',
    'MQQQQQQQQQZMQQQQQQQQQQQQQZ': 'Y',
    'MQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQZ': 'Z',
    'MQQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': '2',
    'MQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': '3',
    'MQQQQZMQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQZMQQQQQZ': '4',
    'MQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': '5',
    'MQQQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQZ': '6',
    'MQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQZ': '7',
    'MQQQQQQQQZMQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQZMQQQQQQQZ': '8',
    'MQQQQQQQQZMQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQZ': '9',
}


def solve_svg_captcha(svg_content):
    """
    Giải captcha SVG bằng cách phân tích SVG path patterns.
    Port từ VBA code detectSVGCaptcha.
    """
    try:
        # Tách các path elements từ SVG
        parts = svg_content.split(' d="')

        # Regex để tách commands M, Q, Z và lấy tọa độ
        pattern = re.compile(r'([MQZ])([^MQZ]*)')

        chars = []

        for i in range(1, len(parts)):
            # Lấy path data (trước dấu ")
            path_data = parts[i].split('"')[0]

            # Tìm tất cả commands
            matches = list(pattern.finditer(path_data))
            if not matches:
                continue

            # Tạo fingerprint: chỉ lấy command letters
            fingerprint = pattern.sub(r'\1', path_data)

            # Lấy tọa độ X từ command đầu tiên (để sắp xếp vị trí)
            first_match = matches[0]
            sub = first_match.group(2).strip()
            x_pos = 0
            if sub:
                # Lấy số đầu tiên trong submatch
                num_match = re.match(r'([\d.]+)', sub)
                if num_match:
                    x_pos = float(num_match.group(1))

            # Tìm ký tự tương ứng
            if fingerprint in CAPTCHA_PATTERNS:
                chars.append((x_pos, CAPTCHA_PATTERNS[fingerprint]))

        if not chars:
            return ''

        # Sắp xếp theo vị trí X (trái sang phải)
        chars.sort(key=lambda c: c[0])

        return ''.join(c[1] for c in chars)

    except Exception as e:
        logger.error(f"[Captcha Solver] Error: {e}")
        return ''


# ==================== LOGIN ENDPOINTS ====================

@bp.route('/captcha', methods=['GET'])
def get_captcha():
    """
    Lấy captcha từ GDT API và tự động giải.
    Response: { key, content (SVG), solved (text đã giải) }
    """
    try:
        url = f"{HDDT_API_BASE}/captcha"
        response = requests.get(url, timeout=15, verify=True)

        if response.status_code == 200:
            data = response.json()
            captcha_key = data.get('key', '')
            captcha_svg = data.get('content', '')

            # Tự động giải captcha
            solved = solve_svg_captcha(captcha_svg)
            logger.info(f"[Captcha] key={captcha_key}, solved={solved}")

            return jsonify({
                'key': captcha_key,
                'content': captcha_svg,
                'solved': solved
            })
        else:
            return jsonify({'error': f'GDT API Error: {response.status_code}'}), response.status_code

    except Exception as e:
        logger.exception(f"[Captcha] Error: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/login', methods=['POST'])
def login():
    """
    Đăng nhập vào GDT và lấy token.
    Request body: { username, password, ckey, cvalue }
    Response: { token, profile }
    """
    try:
        body = request.get_json()
        if not body:
            return jsonify({'error': 'Missing request body'}), 400

        username = body.get('username', '')
        password = body.get('password', '')
        ckey = body.get('ckey', '')
        cvalue = body.get('cvalue', '')

        if not all([username, password, ckey, cvalue]):
            return jsonify({'error': 'Missing required fields: username, password, ckey, cvalue'}), 400

        # Step 1: Authenticate
        auth_url = f"{HDDT_API_BASE}/security-taxpayer/authenticate"
        auth_payload = {
            'username': username,
            'password': password,
            'cvalue': cvalue,
            'ckey': ckey
        }

        auth_response = requests.post(
            auth_url,
            json=auth_payload,
            timeout=15,
            verify=True
        )

        if auth_response.status_code != 200:
            error_detail = auth_response.text
            logger.error(f"[Login] Auth failed: {auth_response.status_code} - {error_detail}")
            return jsonify({
                'error': 'Đăng nhập thất bại',
                'detail': error_detail,
                'status_code': auth_response.status_code
            }), auth_response.status_code

        auth_data = auth_response.json()
        token = auth_data.get('token', '')

        if not token:
            return jsonify({'error': 'Không nhận được token từ GDT'}), 500

        # Step 2: Lấy profile
        profile = None
        try:
            profile_url = f"{HDDT_API_BASE}/security-taxpayer/profile"
            profile_response = requests.get(
                profile_url,
                headers={'Authorization': f'Bearer {token}'},
                timeout=15,
                verify=True
            )
            if profile_response.status_code == 200:
                profile = profile_response.json()
        except Exception as e:
            logger.warning(f"[Login] Failed to get profile: {e}")

        return jsonify({
            'token': token,
            'profile': profile
        })

    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request timeout'}), 504
    except Exception as e:
        logger.exception(f"[Login] Error: {e}")
        return jsonify({'error': str(e)}), 500


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
