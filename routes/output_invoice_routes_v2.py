"""
OUTPUT INVOICE ROUTES V2 - SCALABLE API
API endpoints cho đồng bộ hóa đơn đầu ra

Endpoints:
- GET  /api/v2/invoices/output              - Query với filter & pagination
- POST /api/v2/invoices/output/import/xml   - Import từ XML (trang thuế - đầu ra)
- POST /api/v2/invoices/output/sync/local   - Sync từ invoices collection

- GET  /api/v2/invoices/output/customers    - Danh sách KH (cho dropdown)
- GET  /api/v2/invoices/output/summary      - Tổng hợp đối chiếu

- POST   /api/v2/invoices/output/reconciliation/run       - Chạy đối chiếu
- GET    /api/v2/invoices/output/reconciliation/results   - Kết quả đối chiếu
- DELETE /api/v2/invoices/output/reconciliation/results/<id> - Xóa kết quả

- DELETE /api/v2/invoices/output/clear         - Xóa theo source
- DELETE /api/v2/invoices/output/clear-all     - Xóa tất cả
"""

import logging
from flask import Blueprint, request, jsonify
from firebase.firebase_invoices.output_invoice_service_v2 import output_invoice_service_v2 as service

logger = logging.getLogger(__name__)


def create_output_invoice_routes_v2():
    """Factory function to create v2 output invoice routes blueprint"""

    bp = Blueprint('output_invoices_v2', __name__, url_prefix='/api/v2/invoices/output')

    # =========================================================================
    # QUERY ENDPOINTS
    # =========================================================================

    @bp.route('', methods=['GET'])
    def get_invoices():
        """
        Query hóa đơn đầu ra với filter và pagination
        """
        try:
            source = request.args.get('source')
            year = request.args.get('year', type=int)
            month_key = request.args.get('month_key')
            from_date = request.args.get('from_date')
            to_date = request.args.get('to_date')
            customer_name = request.args.get('customer_name')
            reconcile_status = request.args.get('reconcile_status')
            page_size = request.args.get('page_size', 25, type=int)
            cursor = request.args.get('after_doc_id') or request.args.get('before_doc_id')
            direction = 'prev' if request.args.get('before_doc_id') else 'next'

            result = service.get_invoices(
                source=source,
                year=year,
                month_key=month_key,
                from_date=from_date,
                to_date=to_date,
                customer_name=customer_name,
                reconcile_status=reconcile_status,
                page_size=page_size,
                cursor_doc_id=cursor,
                direction=direction
            )

            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error in get_output_invoices: {e}")
            return jsonify({
                'invoices': [],
                'pagination': {},
                'error': str(e)
            }), 500

    @bp.route('/customers', methods=['GET'])
    def get_customers():
        """Get list of customers for dropdown"""
        try:
            customers = service.get_customers()
            return jsonify(customers)
        except Exception as e:
            logger.exception(f"Error getting customers: {e}")
            return jsonify([]), 500

    @bp.route('/summary', methods=['GET'])
    def get_summary():
        """Get reconciliation summary"""
        try:
            month_key = request.args.get('month_key')
            year = request.args.get('year', type=int)

            summary = service.get_reconciliation_summary(month_key, year)
            return jsonify(summary)
        except Exception as e:
            logger.exception(f"Error getting summary: {e}")
            return jsonify({
                'taxPortalCount': 0,
                'localCount': 0,
                'matchedCount': 0,
                'unmatchedCount': 0,
                'mismatchCount': 0
            }), 500

    # =========================================================================
    # IMPORT ENDPOINTS
    # =========================================================================

    @bp.route('/import/xml', methods=['POST'])
    def import_xml():
        """Import output invoices from XML files"""
        try:
            from firebase.firebase_invoices.tax_invoice_xml_parser import TaxInvoiceXMLParser

            if 'files' not in request.files:
                return jsonify({
                    'success': False,
                    'message': 'No files provided'
                }), 400

            files = request.files.getlist('files')
            all_invoices = []
            parse_errors = []

            for file in files:
                if not file.filename:
                    continue

                try:
                    content = file.read()
                    invoices, errors = TaxInvoiceXMLParser.parse(content)
                    all_invoices.extend(invoices)
                    parse_errors.extend(errors)
                except Exception as e:
                    parse_errors.append(f"{file.filename}: {str(e)}")

            if not all_invoices:
                return jsonify({
                    'success': False,
                    'message': 'No valid invoices found',
                    'parseErrors': parse_errors
                }), 400

            # Convert to unified format (output invoices)
            unified_invoices = []
            for inv in all_invoices:
                unified_invoices.append({
                    'invoiceNo': inv.get('invoiceNo', ''),
                    'invoiceSymbol': inv.get('invoiceSymbol', ''),
                    'invoiceDate': inv.get('invoiceDate', ''),
                    'buyerName': inv.get('buyerName', ''),
                    'buyerTaxCode': inv.get('buyerTaxCode', ''),
                    'buyerAddress': inv.get('buyerAddress', ''),
                    'sellerName': inv.get('sellerName', ''),
                    'sellerTaxCode': inv.get('sellerTaxCode', ''),
                    'totalBeforeVat': inv.get('totalBeforeVat', 0),
                    'totalAmount': inv.get('totalAmount', 0),
                    'vatAmount': inv.get('vatAmount', 0),
                    'vatRate': inv.get('vatRate', 0),
                    'items': inv.get('items', [])
                })

            logger.info(f"Parsed {len(unified_invoices)} output invoices from XML files")

            result = service.batch_import_invoices(
                unified_invoices,
                service.SOURCE_TAX_PORTAL_OUTPUT
            )
            result['parseErrors'] = parse_errors

            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error importing output XML: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @bp.route('/sync/local', methods=['POST'])
    def sync_local():
        """Sync invoices from local (invoices collection)"""
        try:
            result = service.sync_local_invoices()
            return jsonify(result)
        except Exception as e:
            logger.exception(f"Error syncing local invoices: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # =========================================================================
    # RECONCILIATION ENDPOINTS
    # =========================================================================

    @bp.route('/reconciliation/run', methods=['POST'])
    def run_reconciliation():
        """Run reconciliation between tax and local output invoices"""
        try:
            month_key = request.args.get('month_key')
            result = service.run_reconciliation(month_key)
            return jsonify(result)
        except Exception as e:
            logger.exception(f"Error running output reconciliation: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @bp.route('/reconciliation/results', methods=['GET'])
    def get_reconciliation_results():
        """Get reconciliation results"""
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter

            status = request.args.get('status')
            limit = request.args.get('limit', 50, type=int)

            query = service.db.collection(service.COLLECTION_RECONCILIATION)

            if status:
                query = query.where(filter=FieldFilter('status', '==', status))

            query = query.limit(limit)
            docs = list(query.stream())

            results = []
            for doc in docs:
                data = doc.to_dict()
                if 'checkedAt' in data and hasattr(data['checkedAt'], 'isoformat'):
                    data['checkedAt'] = data['checkedAt'].isoformat()
                data['id'] = doc.id
                results.append(data)

            return jsonify({
                'results': results,
                'count': len(results)
            })

        except Exception as e:
            logger.exception(f"Error getting output reconciliation results: {e}")
            return jsonify({'error': str(e)}), 500

    @bp.route('/reconciliation/results/<result_id>', methods=['DELETE'])
    def delete_reconciliation_result(result_id: str):
        """Delete a reconciliation result"""
        try:
            doc_ref = service.db.collection(service.COLLECTION_RECONCILIATION).document(result_id)
            doc = doc_ref.get()

            if not doc.exists:
                return jsonify({
                    'success': False,
                    'message': 'Không tìm thấy kết quả đối chiếu'
                }), 404

            doc_ref.delete()
            logger.info(f"Deleted output reconciliation result: {result_id}")

            return jsonify({
                'success': True,
                'message': 'Đã xóa kết quả đối chiếu'
            })

        except Exception as e:
            logger.exception(f"Error deleting output reconciliation result: {e}")
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500

    # =========================================================================
    # DELETE ENDPOINTS
    # =========================================================================

    @bp.route('/clear', methods=['DELETE'])
    def clear_invoices():
        """Delete output invoices by source"""
        try:
            source = request.args.get('source')
            if not source:
                return jsonify({
                    'success': False,
                    'message': 'Source is required'
                }), 400

            result = service.clear_by_source(source)
            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error clearing output invoices: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @bp.route('/clear-all', methods=['DELETE'])
    def clear_all():
        """Delete all output invoices"""
        try:
            result = service.clear_all()
            return jsonify(result)
        except Exception as e:
            logger.exception(f"Error clearing all output invoices: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================

    @bp.route('/health', methods=['GET'])
    def health_check():
        """Health check"""
        return jsonify({
            'status': 'healthy',
            'service': 'output_invoices_v2',
            'version': '2.0.0'
        })

    return bp
