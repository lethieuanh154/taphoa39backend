"""
Supplies Invoice API Routes
API endpoints cho đồng bộ hóa đơn đầu vào

Endpoints:
- POST /api/invoices/import-tax       - Import hóa đơn từ cơ quan thuế (XML/Excel)
- POST /api/invoices/import-local     - Import hóa đơn từ folder local (JSON)
- POST /api/invoices/reconcile        - Đối chiếu hóa đơn
- GET  /api/invoices/sync-summary     - Lấy tóm tắt đồng bộ
- GET  /api/invoices/tax              - Lấy danh sách hóa đơn từ cơ quan thuế
- GET  /api/invoices/internal         - Lấy danh sách hóa đơn từ folder local
- DELETE /api/invoices/tax/<id>       - Xóa hóa đơn từ cơ quan thuế
- DELETE /api/invoices/internal/<id>  - Xóa hóa đơn từ folder local
"""

import logging
from flask import Blueprint, request, jsonify

from firebase.firebase_supplies_invoices import SuppliesInvoiceService
from services.invoice_parsers import (
    TaxInvoiceXMLParser,
    TaxInvoiceExcelParser,
    LocalInvoiceJSONParser,
    detect_and_parse
)

logger = logging.getLogger(__name__)


def create_supplies_invoice_routes() -> Blueprint:
    """Create and configure the supplies invoice routes blueprint"""

    bp = Blueprint('supplies_invoices', __name__, url_prefix='/api/invoices')

    # Initialize service
    service = SuppliesInvoiceService()

    # =========================================================================
    # IMPORT ENDPOINTS
    # =========================================================================

    @bp.route('/import-tax', methods=['POST'])
    def import_tax_invoices():
        """
        Import hóa đơn từ cơ quan thuế
        Accepts: XML, Excel files

        Request:
            - files: List of files (multipart/form-data)

        Response:
            {
                "success": true,
                "summary": {
                    "totalFiles": 2,
                    "totalInvoices": 15,
                    "imported": 12,
                    "duplicates": 3,
                    "failed": 0
                },
                "errors": []
            }
        """
        try:
            if 'files' not in request.files and 'file' not in request.files:
                return jsonify({
                    'success': False,
                    'error': 'Không có file trong request'
                }), 400

            # Get files - support both 'files' and 'file' field names
            files = request.files.getlist('files') or request.files.getlist('file')

            if not files or (len(files) == 1 and files[0].filename == ''):
                return jsonify({
                    'success': False,
                    'error': 'Không có file được chọn'
                }), 400

            summary = {
                'totalFiles': len(files),
                'totalInvoices': 0,
                'imported': 0,
                'duplicates': 0,
                'failed': 0
            }
            all_errors = []

            for file in files:
                filename = file.filename
                content = file.read()

                logger.info(f"Processing tax invoice file: {filename}")

                # Detect file type and parse
                invoices, errors, file_type = detect_and_parse(content, filename)

                if errors:
                    all_errors.extend([f"{filename}: {e}" for e in errors])

                if file_type not in ['xml', 'excel']:
                    all_errors.append(f"{filename}: Chỉ hỗ trợ file XML hoặc Excel")
                    continue

                summary['totalInvoices'] += len(invoices)

                # Import to Firestore
                if invoices:
                    result = service.bulk_create_tax_invoices(invoices)
                    summary['imported'] += result['success']
                    summary['duplicates'] += result['duplicates']
                    summary['failed'] += result['failed']

                    if result['errors']:
                        all_errors.extend([f"{filename}: {e}" for e in result['errors']])

            logger.info(f"Import tax invoices complete: {summary}")

            return jsonify({
                'success': True,
                'summary': summary,
                'errors': all_errors
            })

        except Exception as e:
            logger.exception(f"Error importing tax invoices: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    @bp.route('/save-ai-invoice', methods=['POST'])
    def save_ai_invoice():
        """
        Lưu hóa đơn từ AI parsing (Gemini 3 Flash)
        Thay thế import-local cho flow mới

        Request JSON:
            {
                "invoiceNo": "1631",
                "invoiceSymbol": "1C25THP",
                "invoiceDate": "2025-11-17",
                "supplier": {
                    "name": "CÔNG TY TNHH...",
                    "taxCode": "0102345678",
                    "address": "123 Đường ABC..."
                },
                "buyer": {
                    "name": "TẠP HÓA 39",
                    "taxCode": "0123456789"
                },
                "items": [
                    {
                        "name": "Sản phẩm A",
                        "unit": "Cái",
                        "quantity": 10,
                        "unitPrice": 100000,
                        "amount": 1000000
                    }
                ],
                "totalBeforeVat": 1000000,
                "vatRate": 10,
                "vatAmount": 100000,
                "totalAmount": 1100000,
                "confidence": 0.95
            }

        Response:
            {
                "success": true,
                "message": "Lưu hóa đơn thành công",
                "docId": "abc123..."
            }
        """
        try:
            data = request.get_json()

            if not data:
                return jsonify({
                    'success': False,
                    'error': 'Không có dữ liệu hóa đơn'
                }), 400

            logger.info(f"Saving AI invoice: {data.get('invoiceNo')}")

            success, message, doc_id = service.create_ai_invoice(data)

            if success:
                return jsonify({
                    'success': True,
                    'message': message,
                    'docId': doc_id
                })
            else:
                return jsonify({
                    'success': False,
                    'error': message
                }), 400

        except Exception as e:
            logger.exception(f"Error saving AI invoice: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    @bp.route('/import-local', methods=['POST'])
    def import_local_invoices():
        """
        Import hóa đơn từ folder local (OCR JSON)
        @deprecated Use save-ai-invoice instead
        Accepts: JSON files

        Request:
            - files: List of files (multipart/form-data)

        Response:
            {
                "success": true,
                "summary": {
                    "totalFiles": 5,
                    "totalInvoices": 5,
                    "imported": 4,
                    "duplicates": 1,
                    "failed": 0
                },
                "errors": []
            }
        """
        try:
            if 'files' not in request.files and 'file' not in request.files:
                return jsonify({
                    'success': False,
                    'error': 'Không có file trong request'
                }), 400

            files = request.files.getlist('files') or request.files.getlist('file')

            if not files or (len(files) == 1 and files[0].filename == ''):
                return jsonify({
                    'success': False,
                    'error': 'Không có file được chọn'
                }), 400

            summary = {
                'totalFiles': len(files),
                'totalInvoices': 0,
                'imported': 0,
                'duplicates': 0,
                'failed': 0
            }
            all_errors = []

            for file in files:
                filename = file.filename
                content = file.read()

                logger.info(f"Processing local invoice file: {filename}")

                # Parse JSON
                invoices, errors = LocalInvoiceJSONParser.parse(content)

                if errors:
                    all_errors.extend([f"{filename}: {e}" for e in errors])

                summary['totalInvoices'] += len(invoices)

                # Import to Firestore
                if invoices:
                    result = service.bulk_create_internal_invoices(invoices)
                    summary['imported'] += result['success']
                    summary['duplicates'] += result['duplicates']
                    summary['failed'] += result['failed']

                    if result['errors']:
                        all_errors.extend([f"{filename}: {e}" for e in result['errors']])

            logger.info(f"Import local invoices complete: {summary}")

            return jsonify({
                'success': True,
                'summary': summary,
                'errors': all_errors
            })

        except Exception as e:
            logger.exception(f"Error importing local invoices: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    # =========================================================================
    # RECONCILIATION ENDPOINTS
    # =========================================================================

    @bp.route('/reconcile', methods=['POST'])
    def reconcile_invoices():
        """
        Đối chiếu hóa đơn từ 2 nguồn

        Request JSON:
            {
                "fromDate": "2024-01-01",  // optional
                "toDate": "2024-01-31",    // optional
                "month": 1,                // optional
                "year": 2024               // optional
            }

        Response:
            {
                "success": true,
                "summary": {
                    "totalTax": 100,
                    "totalInternal": 95,
                    "matched": 90,
                    "missingInternal": 5,
                    "missingTax": 3,
                    "mismatch": 2
                },
                "reconciliations": [...]
            }
        """
        try:
            data = request.get_json() or {}

            from_date = data.get('fromDate')
            to_date = data.get('toDate')
            month = data.get('month')
            year = data.get('year')

            logger.info(f"Reconciling invoices: {data}")

            result = service.reconcile_invoices(
                from_date=from_date,
                to_date=to_date,
                month=month,
                year=year
            )

            if 'error' in result:
                return jsonify({
                    'success': False,
                    'error': result['error']
                }), 500

            return jsonify({
                'success': True,
                'summary': result['summary'],
                'reconciliations': result['reconciliations']
            })

        except Exception as e:
            logger.exception(f"Error reconciling invoices: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    @bp.route('/sync-summary', methods=['GET'])
    def get_sync_summary():
        """
        Lấy tóm tắt đồng bộ

        Query params:
            - month: YYYY-MM format (e.g., "2024-01")
            - year: YYYY format (e.g., "2024")

        Response:
            {
                "success": true,
                "summary": {
                    "totalTax": 100,
                    "totalInternal": 95,
                    "matched": 90,
                    "missingInternal": 5,
                    "missingTax": 3,
                    "mismatch": 2
                }
            }
        """
        try:
            month_param = request.args.get('month')  # YYYY-MM format
            year_param = request.args.get('year')

            month = None
            year = None

            if month_param:
                parts = month_param.split('-')
                if len(parts) == 2:
                    year = int(parts[0])
                    month = int(parts[1])

            if year_param and not year:
                year = int(year_param)

            summary = service.get_sync_summary(month=month, year=year)

            return jsonify({
                'success': True,
                'summary': summary
            })

        except Exception as e:
            logger.exception(f"Error getting sync summary: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    # =========================================================================
    # LIST ENDPOINTS
    # =========================================================================

    @bp.route('/tax', methods=['GET'])
    def get_tax_invoices():
        """
        Lấy danh sách hóa đơn từ cơ quan thuế

        Query params:
            - fromDate: YYYY-MM-DD
            - toDate: YYYY-MM-DD
            - month: 1-12
            - year: YYYY
        """
        try:
            from_date = request.args.get('fromDate')
            to_date = request.args.get('toDate')
            month = request.args.get('month', type=int)
            year = request.args.get('year', type=int)

            invoices = service.get_tax_invoices(
                from_date=from_date,
                to_date=to_date,
                month=month,
                year=year
            )

            # Convert datetime objects to strings for JSON serialization
            for inv in invoices:
                if 'importedAt' in inv and hasattr(inv['importedAt'], 'isoformat'):
                    inv['importedAt'] = inv['importedAt'].isoformat()

            return jsonify({
                'success': True,
                'invoices': invoices,
                'total': len(invoices)
            })

        except Exception as e:
            logger.exception(f"Error getting tax invoices: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    @bp.route('/internal', methods=['GET'])
    def get_internal_invoices():
        """
        Lấy danh sách hóa đơn từ folder local

        Query params:
            - fromDate: YYYY-MM-DD
            - toDate: YYYY-MM-DD
            - month: 1-12
            - year: YYYY
        """
        try:
            from_date = request.args.get('fromDate')
            to_date = request.args.get('toDate')
            month = request.args.get('month', type=int)
            year = request.args.get('year', type=int)

            invoices = service.get_internal_invoices(
                from_date=from_date,
                to_date=to_date,
                month=month,
                year=year
            )

            # Convert datetime objects to strings
            for inv in invoices:
                if 'createdAt' in inv and hasattr(inv['createdAt'], 'isoformat'):
                    inv['createdAt'] = inv['createdAt'].isoformat()

            return jsonify({
                'success': True,
                'invoices': invoices,
                'total': len(invoices)
            })

        except Exception as e:
            logger.exception(f"Error getting internal invoices: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    # =========================================================================
    # DELETE ENDPOINTS
    # =========================================================================

    @bp.route('/tax/<doc_id>', methods=['DELETE'])
    def delete_tax_invoice(doc_id):
        """Xóa hóa đơn từ cơ quan thuế"""
        try:
            success = service.delete_tax_invoice(doc_id)

            if success:
                return jsonify({
                    'success': True,
                    'message': 'Đã xóa hóa đơn'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Không thể xóa hóa đơn'
                }), 400

        except Exception as e:
            logger.exception(f"Error deleting tax invoice: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    @bp.route('/internal/<doc_id>', methods=['DELETE'])
    def delete_internal_invoice(doc_id):
        """Xóa hóa đơn từ folder local"""
        try:
            success = service.delete_internal_invoice(doc_id)

            if success:
                return jsonify({
                    'success': True,
                    'message': 'Đã xóa hóa đơn'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Không thể xóa hóa đơn'
                }), 400

        except Exception as e:
            logger.exception(f"Error deleting internal invoice: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    # =========================================================================
    # CLEAR ALL ENDPOINTS
    # =========================================================================

    @bp.route('/clear-tax', methods=['DELETE'])
    def clear_tax_invoices():
        """
        Xóa tất cả hóa đơn từ cơ quan thuế (tax_invoices collection)

        Response:
            {
                "success": true,
                "message": "Đã xóa X hóa đơn",
                "deleted": X
            }
        """
        try:
            logger.warning("CLEARING ALL TAX INVOICES - User requested deletion")

            result = service.clear_all_tax_invoices()

            if result['success']:
                return jsonify({
                    'success': True,
                    'message': f"Đã xóa {result['deleted']} hóa đơn từ trang thuế",
                    'deleted': result['deleted']
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('error', 'Không thể xóa hóa đơn')
                }), 500

        except Exception as e:
            logger.exception(f"Error clearing tax invoices: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    @bp.route('/clear-internal', methods=['DELETE'])
    def clear_internal_invoices():
        """
        Xóa tất cả hóa đơn từ AI (internal_invoices collection)

        Response:
            {
                "success": true,
                "message": "Đã xóa X hóa đơn",
                "deleted": X
            }
        """
        try:
            logger.warning("CLEARING ALL INTERNAL INVOICES - User requested deletion")

            result = service.clear_all_internal_invoices()

            if result['success']:
                return jsonify({
                    'success': True,
                    'message': f"Đã xóa {result['deleted']} hóa đơn từ AI",
                    'deleted': result['deleted']
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('error', 'Không thể xóa hóa đơn')
                }), 500

        except Exception as e:
            logger.exception(f"Error clearing internal invoices: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    @bp.route('/clear-all', methods=['DELETE'])
    def clear_all_invoices():
        """
        Xóa tất cả hóa đơn từ cả 2 collection (tax_invoices + internal_invoices)

        Response:
            {
                "success": true,
                "message": "Đã xóa X hóa đơn thuế và Y hóa đơn AI",
                "taxDeleted": X,
                "internalDeleted": Y
            }
        """
        try:
            logger.warning("CLEARING ALL INVOICES (BOTH COLLECTIONS) - User requested deletion")

            result = service.clear_all_invoices()

            if result['success']:
                return jsonify({
                    'success': True,
                    'message': f"Đã xóa {result['taxDeleted']} hóa đơn thuế và {result['internalDeleted']} hóa đơn AI",
                    'taxDeleted': result['taxDeleted'],
                    'internalDeleted': result['internalDeleted']
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('error', 'Không thể xóa hóa đơn')
                }), 500

        except Exception as e:
            logger.exception(f"Error clearing all invoices: {e}")
            return jsonify({
                'success': False,
                'error': f'Lỗi server: {str(e)}'
            }), 500

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================

    @bp.route('/health', methods=['GET'])
    def health_check():
        """Health check for supplies invoice API"""
        return jsonify({
            'status': 'healthy',
            'service': 'supplies_invoices',
            'version': '1.0.0'
        })

    return bp
