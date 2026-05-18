import requests
from flask import Blueprint, request, jsonify

bp = Blueprint('osrm_proxy', __name__)


@bp.route('/api/osrm/route')
def osrm_route():
    coords = request.args.get('coords', '')
    if not coords:
        return jsonify({'error': 'coords required'}), 400
    try:
        resp = requests.get(
            f'https://router.project-osrm.org/route/v1/driving/{coords}',
            params={'overview': 'full', 'geometries': 'geojson'},
            timeout=10
        )
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@bp.route('/api/osrm/table')
def osrm_table():
    coords = request.args.get('coords', '')
    if not coords:
        return jsonify({'error': 'coords required'}), 400
    try:
        resp = requests.get(
            f'https://router.project-osrm.org/table/v1/driving/{coords}',
            params={'annotations': 'distance'},
            timeout=10
        )
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 502
