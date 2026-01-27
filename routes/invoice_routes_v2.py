"""
INVOICE ROUTES V2 - SCALABLE API
API endpoints với pagination và optimized queries cho 100.000+ hóa đơn

Endpoints:
- GET  /api/v2/invoices              - Query với filter & pagination
- GET  /api/v2/invoices/default      - Load mặc định (30 ngày, 50 records)
- POST /api/v2/invoices              - Tạo 1 hóa đơn
- POST /api/v2/invoices/batch        - Import nhiều hóa đơn
- POST /api/v2/invoices/import-xml   - Import từ XML (trang thuế)

- GET  /api/v2/suppliers             - Danh sách NCC (cho dropdown)

- GET  /api/v2/reconciliation/summary   - Tổng hợp đối chiếu
- POST /api/v2/reconciliation/run       - Chạy đối chiếu

- DELETE /api/v2/invoices/clear         - Xóa theo source
- DELETE /api/v2/invoices/clear-all     - Xóa tất cả
"""

import logging
from flask import Blueprint, request, jsonify
from firebase.firebase_invoices.invoice_service_v2 import invoice_service_v2 as service

logger = logging.getLogger(__name__)


def create_invoice_routes_v2():
    """Factory function to create v2 invoice routes blueprint"""

    bp = Blueprint('invoices_v2', __name__, url_prefix='/api/v2/invoices')

    # =========================================================================
    # QUERY ENDPOINTS
    # =========================================================================

    @bp.route('', methods=['GET'])
    def get_invoices():
        """
        Query hóa đơn với filter và pagination

        Query params:
            - source: TAX_PORTAL | AI_PDF
            - year: 2024
            - monthKey: 2024-12
            - fromDate: 2024-01-01
            - toDate: 2024-12-31
            - supplierTaxCode: MST nhà cung cấp
            - reconcileStatus: PENDING | MATCHED | UNMATCHED | MISMATCH
            - pageSize: 50 (max 100)
            - cursor: document ID for pagination
            - direction: next | prev

        Response:
            {
                "invoices": [...],
                "pagination": {
                    "hasNext": true,
                    "hasPrev": false,
                    "firstDocId": "...",
                    "lastDocId": "...",
                    "pageSize": 50,
                    "count": 50
                }
            }
        """
        try:
            # Parse query params
            source = request.args.get('source')
            year = request.args.get('year', type=int)
            month_key = request.args.get('monthKey')
            from_date = request.args.get('fromDate')
            to_date = request.args.get('toDate')
            supplier_tax_code = request.args.get('supplierTaxCode')
            reconcile_status = request.args.get('reconcileStatus')
            page_size = request.args.get('pageSize', 50, type=int)
            cursor = request.args.get('cursor')
            direction = request.args.get('direction', 'next')

            result = service.get_invoices(
                source=source,
                year=year,
                month_key=month_key,
                from_date=from_date,
                to_date=to_date,
                supplier_tax_code=supplier_tax_code,
                reconcile_status=reconcile_status,
                page_size=page_size,
                cursor_doc_id=cursor,
                direction=direction
            )

            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error in get_invoices: {e}")
            return jsonify({
                'invoices': [],
                'pagination': {},
                'error': str(e)
            }), 500

    @bp.route('/default', methods=['GET'])
    def get_invoices_default():
        """
        Load mặc định: 30 ngày gần nhất, 50 records

        Query params:
            - source: TAX_PORTAL | AI_PDF (optional)
        """
        try:
            source = request.args.get('source')
            result = service.get_invoices_default(source=source)
            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error in get_invoices_default: {e}")
            return jsonify({'error': str(e)}), 500

    # =========================================================================
    # CREATE ENDPOINTS
    # =========================================================================

    @bp.route('', methods=['POST'])
    def create_invoice():
        """
        Tạo 1 hóa đơn

        Body:
            {
                "source": "TAX_PORTAL" | "AI_PDF",
                "invoiceNo": "00000123",
                "invoiceSymbol": "1C24TAA",
                "invoiceDate": "2024-12-01",
                "supplierName": "...",
                "supplierTaxCode": "...",
                ...
            }
        """
        try:
            data = request.get_json()
            source = data.get('source', 'AI_PDF')

            success, message, doc_id = service.create_invoice(data, source)

            return jsonify({
                'success': success,
                'message': message,
                'docId': doc_id
            }), 200 if success else 400

        except Exception as e:
            logger.exception(f"Error creating invoice: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @bp.route('/batch', methods=['POST'])
    def batch_import():
        """
        Import nhiều hóa đơn (JSON)

        Body:
            {
                "source": "TAX_PORTAL" | "AI_PDF",
                "invoices": [...]
            }
        """
        try:
            data = request.get_json()
            source = data.get('source', 'AI_PDF')
            invoices = data.get('invoices', [])

            if not invoices:
                return jsonify({
                    'success': False,
                    'error': 'Không có hóa đơn để import'
                }), 400

            result = service.batch_import_invoices(invoices, source)
            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error in batch import: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @bp.route('/import-xml', methods=['POST'])
    def import_xml():
        """
        Import hóa đơn từ XML files (trang thuế)

        Multipart form:
            - files: XML files
        """
        try:
            from services.invoice_parsers import TaxInvoiceXMLParser

            if 'files' not in request.files:
                return jsonify({
                    'success': False,
                    'error': 'Không có file được upload'
                }), 400

            files = request.files.getlist('files')
            all_invoices = []
            parse_errors = []

            for file in files:
                if not file.filename:
                    continue

                try:
                    content = file.read()  # Keep as bytes for parser
                    invoices, errors = TaxInvoiceXMLParser.parse(content)
                    all_invoices.extend(invoices)
                    parse_errors.extend(errors)
                except Exception as e:
                    parse_errors.append(f"{file.filename}: {str(e)}")

            if not all_invoices:
                return jsonify({
                    'success': False,
                    'error': 'Không parse được hóa đơn nào',
                    'parseErrors': parse_errors
                }), 400

            # Convert to unified format
            unified_invoices = []
            for inv in all_invoices:
                unified_invoices.append({
                    'invoiceNo': inv.get('invoiceNo', ''),
                    'invoiceSymbol': inv.get('invoiceSymbol', ''),
                    'invoiceDate': inv.get('invoiceDate', ''),
                    'sellerName': inv.get('sellerName', ''),
                    'supplierTaxCode': inv.get('sellerTaxCode', ''),
                    'sellerTaxCode': inv.get('sellerTaxCode', ''),
                    'sellerAddress': inv.get('sellerAddress', ''),
                    'sellerPhone': inv.get('sellerPhone', ''),
                    'sellerEmail': inv.get('sellerEmail', ''),
                    'buyerName': inv.get('buyerName', ''),
                    'buyerTaxCode': inv.get('buyerTaxCode', ''),
                    'buyerAddress': inv.get('buyerAddress', ''),
                    'buyerCode': inv.get('buyerCode', ''),
                    'totalBeforeVat': inv.get('totalBeforeVat', 0),
                    'totalAmount': inv.get('totalAmount', 0),
                    'vatAmount': inv.get('vatAmount', 0),
                    'vatRate': inv.get('vatRate', 0),
                    'totalAmountInWords': inv.get('totalAmountInWords', ''),
                    'items': inv.get('items', [])
                })

            logger.info(f"Parsed {len(unified_invoices)} invoices from XML files")

            result = service.batch_import_invoices(
                unified_invoices,
                service.SOURCE_TAX_PORTAL
            )
            result['parseErrors'] = parse_errors

            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error importing XML: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # =========================================================================
    # SUPPLIER ENDPOINTS
    # =========================================================================

    @bp.route('/suppliers', methods=['GET'])
    def get_suppliers():
        """
        Lấy danh sách nhà cung cấp (cho dropdown/autocomplete)

        Query params:
            - search: Tìm theo tên hoặc MST
            - limit: Số lượng (default 50)
        """
        try:
            search = request.args.get('search')
            limit = request.args.get('limit', 50, type=int)

            suppliers = service.get_suppliers(search=search, limit=limit)
            return jsonify({
                'suppliers': suppliers,
                'count': len(suppliers)
            })

        except Exception as e:
            logger.exception(f"Error getting suppliers: {e}")
            return jsonify({'error': str(e)}), 500

    # =========================================================================
    # RECONCILIATION ENDPOINTS
    # =========================================================================

    @bp.route('/reconciliation/summary', methods=['GET'])
    def get_reconciliation_summary():
        """
        Lấy tổng hợp đối chiếu

        Query params:
            - monthKey: 2024-12
            - year: 2024
        """
        try:
            month_key = request.args.get('monthKey')
            year = request.args.get('year', type=int)

            result = service.get_reconciliation_summary(
                month_key=month_key,
                year=year
            )
            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error getting reconciliation summary: {e}")
            return jsonify({'error': str(e)}), 500

    @bp.route('/reconciliation/run', methods=['POST'])
    def run_reconciliation():
        """
        Chạy đối chiếu tự động

        Body:
            {
                "monthKey": "2024-12"  (optional)
            }
        """
        try:
            data = request.get_json() or {}
            month_key = data.get('monthKey')

            logger.info(f"Running reconciliation for monthKey={month_key}")
            result = service.run_reconciliation(month_key=month_key)
            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error running reconciliation: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @bp.route('/reconciliation/results', methods=['GET'])
    def get_reconciliation_results():
        """
        Lấy danh sách kết quả đối chiếu với chi tiết sai lệch

        Query params:
            - status: MATCH | MISMATCH | MISSING_INTERNAL | MISSING_TAX (optional)
            - limit: số records (default 50)

        Response:
            {
                "results": [
                    {
                        "invoiceKey": "00000001|0101234567",
                        "status": "MISMATCH",
                        "taxData": {...},
                        "internalData": {...},
                        "fieldDiffs": [
                            {
                                "field": "totalAmount",
                                "fieldLabel": "Tổng tiền thanh toán",
                                "taxValue": 22000000,
                                "internalValue": 11000000,
                                "diff": 11000000,
                                "diffType": "number"
                            }
                        ]
                    }
                ],
                "count": 1
            }
        """
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
                # Convert datetime to string for JSON
                if 'checkedAt' in data and hasattr(data['checkedAt'], 'isoformat'):
                    data['checkedAt'] = data['checkedAt'].isoformat()
                data['id'] = doc.id
                results.append(data)

            return jsonify({
                'results': results,
                'count': len(results)
            })

        except Exception as e:
            logger.exception(f"Error getting reconciliation results: {e}")
            return jsonify({'error': str(e)}), 500

    @bp.route('/reconciliation/results/<result_id>', methods=['DELETE'])
    def delete_reconciliation_result(result_id: str):
        """
        Xóa một kết quả đối chiếu

        Path params:
            - result_id: ID của document trong invoice_reconciliation

        Response:
            {
                "success": true,
                "message": "Đã xóa kết quả đối chiếu"
            }
        """
        try:
            doc_ref = service.db.collection(service.COLLECTION_RECONCILIATION).document(result_id)
            doc = doc_ref.get()

            if not doc.exists:
                return jsonify({
                    'success': False,
                    'message': 'Không tìm thấy kết quả đối chiếu'
                }), 404

            # Xóa document
            doc_ref.delete()
            logger.info(f"Deleted reconciliation result: {result_id}")

            return jsonify({
                'success': True,
                'message': 'Đã xóa kết quả đối chiếu'
            })

        except Exception as e:
            logger.exception(f"Error deleting reconciliation result: {e}")
            return jsonify({
                'success': False,
                'message': str(e)
            }), 500

    # =========================================================================
    # DELETE ENDPOINTS
    # =========================================================================

    @bp.route('/clear', methods=['DELETE'])
    def clear_invoices():
        """
        Xóa hóa đơn theo nguồn

        Query params:
            - source: TAX_PORTAL | AI_PDF
        """
        try:
            source = request.args.get('source')
            if not source:
                return jsonify({
                    'success': False,
                    'error': 'Thiếu tham số source'
                }), 400

            logger.warning(f"CLEARING invoices for source={source}")
            result = service.clear_invoices_by_source(source)
            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error clearing invoices: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @bp.route('/clear-all', methods=['DELETE'])
    def clear_all_invoices():
        """Xóa tất cả hóa đơn"""
        try:
            logger.warning("CLEARING ALL INVOICES")
            result = service.clear_all_invoices()
            return jsonify(result)

        except Exception as e:
            logger.exception(f"Error clearing all invoices: {e}")
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
        # Lấy project ID từ Firestore client
        try:
            project_id = service.db.project
        except:
            project_id = 'unknown'

        return jsonify({
            'status': 'healthy',
            'service': 'invoices_v2',
            'version': '2.0.0',
            'firebaseProject': project_id
        })

    @bp.route('/debug', methods=['GET'])
    def debug_data():
        """
        Debug endpoint - xem cấu trúc data thực tế trong Firestore
        Giúp xác định vấn đề format date hoặc field names

        Query params:
            - collection: tax_invoices | internal_invoices
            - limit: số document muốn xem (default 3)
        """
        try:
            collection_name = request.args.get('collection', 'tax_invoices')
            limit = request.args.get('limit', 3, type=int)

            # Lấy vài document mẫu
            docs = list(service.db.collection(collection_name).limit(limit).stream())

            sample_docs = []
            for doc in docs:
                data = doc.to_dict()
                # Convert Timestamp to string for JSON serialization
                sample = {'_id': doc.id}
                for key, value in data.items():
                    if hasattr(value, 'isoformat'):
                        sample[key] = f"[Timestamp] {value.isoformat()}"
                    elif hasattr(value, '__class__'):
                        sample[key] = f"[{value.__class__.__name__}] {str(value)}"
                    else:
                        sample[key] = value
                sample_docs.append(sample)

            # Đếm tổng số document
            total_count = len(list(service.db.collection(collection_name).stream()))

            return jsonify({
                'collection': collection_name,
                'totalCount': total_count,
                'sampleCount': len(sample_docs),
                'samples': sample_docs,
                'note': 'Kiểm tra format của invoiceDate để debug query'
            })

        except Exception as e:
            logger.exception(f"Error in debug: {e}")
            return jsonify({'error': str(e)}), 500

    @bp.route('/all', methods=['GET'])
    def get_all_invoices():
        """
        Get all invoices WITHOUT date filter (for debugging)
        Chỉ dùng để debug - kiểm tra xem có lấy được data không

        Query params:
            - source: TAX_PORTAL | AI_PDF
            - limit: số document (default 50)
        """
        try:
            source = request.args.get('source', 'TAX_PORTAL')
            limit = request.args.get('limit', 50, type=int)

            # Query trực tiếp không filter
            result = service.get_invoices(
                source=source,
                page_size=limit
                # Không có from_date, to_date, year, month_key
            )

            return jsonify({
                'debug': True,
                'message': 'Query without date filter',
                'source': source,
                **result
            })

        except Exception as e:
            logger.exception(f"Error in get_all_invoices: {e}")
            return jsonify({'error': str(e)}), 500

    return bp
