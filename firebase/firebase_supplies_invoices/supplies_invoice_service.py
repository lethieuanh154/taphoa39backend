"""
Supplies Invoice Service
Quản lý hóa đơn đầu vào từ cơ quan thuế và folder local
Collections:
- tax_invoices: Hóa đơn từ trang thuế (hoadondientu.gdt.gov.vn)
- internal_invoices: Hóa đơn từ folder local (OCR)
- invoice_reconciliation: Bảng đối chiếu
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from google.cloud.firestore_v1 import FieldFilter

from firebase.init_firebase import init_firestore

logger = logging.getLogger(__name__)

# Environment variable name for service account
FIREBASE_ENV_KEY = "FIREBASE_SERVICE_ACCOUNT_SUPPLIES_INVOICES"


class SuppliesInvoiceService:
    """Service class for managing supplies invoices in Firestore"""

    def __init__(self):
        """Initialize Firestore connection"""
        self._db = None

    @property
    def db(self):
        """Lazy initialization of Firestore client"""
        if self._db is None:
            self._db = init_firestore(FIREBASE_ENV_KEY)
        return self._db

    # =========================================================================
    # TAX INVOICES (từ cơ quan thuế)
    # =========================================================================

    def create_tax_invoice(self, invoice_data: Dict) -> Tuple[bool, str, Optional[str]]:
        """
        Tạo hóa đơn từ cơ quan thuế
        Tránh trùng lặp theo invoiceNo + sellerTaxCode

        Args:
            invoice_data: {
                invoiceNo, invoiceDate, sellerTaxCode, sellerName,
                totalAmount, vatAmount
            }

        Returns:
            (success, message, doc_id)
        """
        try:
            invoice_no = invoice_data.get('invoiceNo', '')
            seller_tax_code = invoice_data.get('sellerTaxCode', '')

            if not invoice_no or not seller_tax_code:
                return False, "Thiếu số hóa đơn hoặc MST nhà cung cấp", None

            # Tạo invoice_key để check trùng
            invoice_key = f"{invoice_no}|{seller_tax_code}"

            # Check trùng
            existing = self.db.collection('tax_invoices').where(
                filter=FieldFilter('invoiceKey', '==', invoice_key)
            ).limit(1).get()

            if len(list(existing)) > 0:
                return False, f"Hóa đơn {invoice_no} từ NCC {seller_tax_code} đã tồn tại", None

            # Chuẩn hóa dữ liệu
            doc_data = {
                'invoiceNo': invoice_no,
                'invoiceDate': invoice_data.get('invoiceDate', ''),
                'sellerTaxCode': seller_tax_code,
                'sellerName': invoice_data.get('sellerName', ''),
                'totalAmount': float(invoice_data.get('totalAmount', 0)),
                'vatAmount': float(invoice_data.get('vatAmount', 0)),
                'source': 'gdt',  # General Department of Taxation
                'invoiceKey': invoice_key,
                'importedAt': datetime.utcnow()
            }

            # Lưu vào Firestore
            doc_ref = self.db.collection('tax_invoices').add(doc_data)
            doc_id = doc_ref[1].id

            logger.info(f"Created tax invoice: {invoice_no} | {seller_tax_code}")
            return True, "Tạo hóa đơn thành công", doc_id

        except Exception as e:
            logger.error(f"Error creating tax invoice: {e}")
            return False, f"Lỗi: {str(e)}", None

    def bulk_create_tax_invoices(self, invoices: List[Dict]) -> Dict:
        """
        Import nhiều hóa đơn từ cơ quan thuế

        Returns:
            {
                success: int,
                failed: int,
                duplicates: int,
                errors: List[str]
            }
        """
        result = {
            'success': 0,
            'failed': 0,
            'duplicates': 0,
            'errors': [],
            'created_ids': []
        }

        for invoice in invoices:
            success, message, doc_id = self.create_tax_invoice(invoice)

            if success:
                result['success'] += 1
                result['created_ids'].append(doc_id)
            elif 'đã tồn tại' in message:
                result['duplicates'] += 1
            else:
                result['failed'] += 1
                result['errors'].append(f"{invoice.get('invoiceNo', 'N/A')}: {message}")

        return result

    def get_tax_invoices(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        month: Optional[int] = None,
        year: Optional[int] = None
    ) -> List[Dict]:
        """
        Lấy danh sách hóa đơn từ cơ quan thuế

        Args:
            from_date: Từ ngày (YYYY-MM-DD)
            to_date: Đến ngày (YYYY-MM-DD)
            month: Tháng (1-12)
            year: Năm
        """
        try:
            query = self.db.collection('tax_invoices')

            # Filter by date range
            if from_date and to_date:
                query = query.where(filter=FieldFilter('invoiceDate', '>=', from_date))
                query = query.where(filter=FieldFilter('invoiceDate', '<=', to_date))
            elif month and year:
                # Tạo date range cho tháng
                start_date = f"{year}-{month:02d}-01"
                if month == 12:
                    end_date = f"{year + 1}-01-01"
                else:
                    end_date = f"{year}-{month + 1:02d}-01"
                query = query.where(filter=FieldFilter('invoiceDate', '>=', start_date))
                query = query.where(filter=FieldFilter('invoiceDate', '<', end_date))
            elif year:
                start_date = f"{year}-01-01"
                end_date = f"{year + 1}-01-01"
                query = query.where(filter=FieldFilter('invoiceDate', '>=', start_date))
                query = query.where(filter=FieldFilter('invoiceDate', '<', end_date))

            # Order by date
            query = query.order_by('invoiceDate')

            docs = query.get()

            invoices = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                invoices.append(data)

            logger.info(f"Retrieved {len(invoices)} tax invoices")
            return invoices

        except Exception as e:
            logger.error(f"Error getting tax invoices: {e}")
            return []

    def delete_tax_invoice(self, doc_id: str) -> bool:
        """Xóa hóa đơn từ cơ quan thuế"""
        try:
            self.db.collection('tax_invoices').document(doc_id).delete()
            logger.info(f"Deleted tax invoice: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting tax invoice: {e}")
            return False

    # =========================================================================
    # INTERNAL INVOICES (từ AI PDF parsing - Gemini)
    # =========================================================================

    def create_ai_invoice(self, invoice_data: Dict) -> Tuple[bool, str, Optional[str]]:
        """
        Lưu hóa đơn từ AI parsing (Gemini 3 Flash)
        Schema mới với đầy đủ thông tin items

        Args:
            invoice_data: {
                invoiceNo: string,
                invoiceSymbol: string,
                invoiceDate: string (YYYY-MM-DD),
                supplier: { name, taxCode, address },
                buyer: { name, taxCode },
                items: [{ name, unit, quantity, unitPrice, amount }],
                totalBeforeVat: number,
                vatRate: number,
                vatAmount: number,
                totalAmount: number,
                confidence: number (0-1)
            }
        """
        try:
            invoice_no = invoice_data.get('invoiceNo', '')
            supplier = invoice_data.get('supplier', {})
            supplier_tax_code = supplier.get('taxCode', '')

            if not invoice_no or not supplier_tax_code:
                return False, "Thiếu số hóa đơn hoặc MST nhà cung cấp", None

            # Tạo invoice_key để check trùng
            invoice_key = f"{invoice_no}|{supplier_tax_code}"

            # Check trùng
            existing = self.db.collection('internal_invoices').where(
                filter=FieldFilter('invoiceKey', '==', invoice_key)
            ).limit(1).get()

            if len(list(existing)) > 0:
                return False, f"Hóa đơn {invoice_no} từ NCC {supplier_tax_code} đã tồn tại", None

            # Chuẩn hóa items
            items = []
            for item in invoice_data.get('items', []):
                items.append({
                    'name': item.get('name', ''),
                    'unit': item.get('unit', ''),
                    'quantity': float(item.get('quantity', 0)),
                    'unitPrice': float(item.get('unitPrice', 0)),
                    'amount': float(item.get('amount', 0))
                })

            # Chuẩn hóa buyer
            buyer = invoice_data.get('buyer', {})

            # Chuẩn hóa dữ liệu theo schema mới
            doc_data = {
                # Thông tin cơ bản
                'invoiceNo': invoice_no,
                'invoiceSymbol': invoice_data.get('invoiceSymbol', ''),
                'invoiceDate': invoice_data.get('invoiceDate', ''),
                'invoiceKey': invoice_key,

                # Nhà cung cấp
                'supplier': {
                    'name': supplier.get('name', ''),
                    'taxCode': supplier_tax_code,
                    'address': supplier.get('address', '')
                },
                'supplierTaxCode': supplier_tax_code,  # Để dễ query
                'supplierName': supplier.get('name', ''),  # Để dễ query

                # Người mua
                'buyer': {
                    'name': buyer.get('name', ''),
                    'taxCode': buyer.get('taxCode', ''),
                    'address': buyer.get('address', '')
                },
                'buyerName': buyer.get('name', ''),  # Để dễ query
                'buyerTaxCode': buyer.get('taxCode', ''),  # Để dễ query

                # Chi tiết hàng hóa
                'items': items,

                # Tổng tiền
                'totalBeforeVat': float(invoice_data.get('totalBeforeVat', 0)),
                'vatRate': float(invoice_data.get('vatRate', 0)),
                'vatAmount': float(invoice_data.get('vatAmount', 0)),
                'totalAmount': float(invoice_data.get('totalAmount', 0)),

                # Metadata
                'source': 'ai_pdf',
                'aiModel': invoice_data.get('aiModel', 'gemini-3-flash'),
                'confidence': float(invoice_data.get('confidence', 0)),
                'createdAt': datetime.utcnow(),

                # Email + Portal metadata
                'sourceTab': invoice_data.get('sourceTab', ''),
                'gmailMessageId': invoice_data.get('gmailMessageId', ''),
                'gmailFrom': invoice_data.get('gmailFrom', ''),
                'gmailDate': invoice_data.get('gmailDate', ''),
                'portalUrl': invoice_data.get('portalUrl', ''),
                'portalPdfUrl': invoice_data.get('portalPdfUrl', ''),
                'invoiceProvider': invoice_data.get('invoiceProvider', ''),
                'portalCredentials': invoice_data.get('portalCredentials', {}),
                'processingMethod': invoice_data.get('processingMethod', ''),
                'attachmentType': invoice_data.get('attachmentType', ''),
            }

            # Lưu vào Firestore
            doc_ref = self.db.collection('internal_invoices').add(doc_data)
            doc_id = doc_ref[1].id

            logger.info(f"Created AI invoice: {invoice_no} | {supplier_tax_code}")
            return True, "Lưu hóa đơn thành công", doc_id

        except Exception as e:
            logger.error(f"Error creating AI invoice: {e}")
            return False, f"Lỗi: {str(e)}", None

    def create_internal_invoice(self, invoice_data: Dict) -> Tuple[bool, str, Optional[str]]:
        """
        Tạo hóa đơn từ folder local (OCR) - Legacy method
        @deprecated Use create_ai_invoice instead

        Args:
            invoice_data: {
                invoiceNo, invoiceDate, supplierTaxCode, supplierName,
                totalAmount, vatAmount, ocrConfidence (optional)
            }
        """
        try:
            invoice_no = invoice_data.get('invoiceNo', '')
            supplier_tax_code = invoice_data.get('supplierTaxCode', '')

            if not invoice_no or not supplier_tax_code:
                return False, "Thiếu số hóa đơn hoặc MST nhà cung cấp", None

            # Tạo invoice_key để check trùng
            invoice_key = f"{invoice_no}|{supplier_tax_code}"

            # Check trùng
            existing = self.db.collection('internal_invoices').where(
                filter=FieldFilter('invoiceKey', '==', invoice_key)
            ).limit(1).get()

            if len(list(existing)) > 0:
                return False, f"Hóa đơn {invoice_no} từ NCC {supplier_tax_code} đã tồn tại", None

            # Chuẩn hóa dữ liệu
            doc_data = {
                'invoiceNo': invoice_no,
                'invoiceDate': invoice_data.get('invoiceDate', ''),
                'supplierTaxCode': supplier_tax_code,
                'supplierName': invoice_data.get('supplierName', ''),
                'totalAmount': float(invoice_data.get('totalAmount', 0)),
                'vatAmount': float(invoice_data.get('vatAmount', 0)),
                'source': 'local',
                'invoiceKey': invoice_key,
                'ocrConfidence': float(invoice_data.get('ocrConfidence', 0)),
                'createdAt': datetime.utcnow()
            }

            # Lưu vào Firestore
            doc_ref = self.db.collection('internal_invoices').add(doc_data)
            doc_id = doc_ref[1].id

            logger.info(f"Created internal invoice: {invoice_no} | {supplier_tax_code}")
            return True, "Tạo hóa đơn thành công", doc_id

        except Exception as e:
            logger.error(f"Error creating internal invoice: {e}")
            return False, f"Lỗi: {str(e)}", None

    def bulk_create_internal_invoices(self, invoices: List[Dict]) -> Dict:
        """
        Import nhiều hóa đơn từ folder local
        """
        result = {
            'success': 0,
            'failed': 0,
            'duplicates': 0,
            'errors': [],
            'created_ids': []
        }

        for invoice in invoices:
            success, message, doc_id = self.create_internal_invoice(invoice)

            if success:
                result['success'] += 1
                result['created_ids'].append(doc_id)
            elif 'đã tồn tại' in message:
                result['duplicates'] += 1
            else:
                result['failed'] += 1
                result['errors'].append(f"{invoice.get('invoiceNo', 'N/A')}: {message}")

        return result

    def get_internal_invoices(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        month: Optional[int] = None,
        year: Optional[int] = None
    ) -> List[Dict]:
        """Lấy danh sách hóa đơn từ folder local"""
        try:
            query = self.db.collection('internal_invoices')

            if from_date and to_date:
                query = query.where(filter=FieldFilter('invoiceDate', '>=', from_date))
                query = query.where(filter=FieldFilter('invoiceDate', '<=', to_date))
            elif month and year:
                start_date = f"{year}-{month:02d}-01"
                if month == 12:
                    end_date = f"{year + 1}-01-01"
                else:
                    end_date = f"{year}-{month + 1:02d}-01"
                query = query.where(filter=FieldFilter('invoiceDate', '>=', start_date))
                query = query.where(filter=FieldFilter('invoiceDate', '<', end_date))
            elif year:
                start_date = f"{year}-01-01"
                end_date = f"{year + 1}-01-01"
                query = query.where(filter=FieldFilter('invoiceDate', '>=', start_date))
                query = query.where(filter=FieldFilter('invoiceDate', '<', end_date))

            query = query.order_by('invoiceDate')

            docs = query.get()

            invoices = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                invoices.append(data)

            logger.info(f"Retrieved {len(invoices)} internal invoices")
            return invoices

        except Exception as e:
            logger.error(f"Error getting internal invoices: {e}")
            return []

    def get_recent_ai_invoices(self, days: int = 1) -> List[Dict]:
        """
        Lấy danh sách hóa đơn AI được tạo trong N ngày gần đây
        Dựa theo createdAt (thời điểm lưu vào Firestore)

        Args:
            days: Số ngày để lọc (mặc định 1 ngày)

        Returns:
            List[Dict]: Danh sách hóa đơn với đầy đủ thông tin items
        """
        try:
            from datetime import timedelta

            # Tính thời điểm bắt đầu (N ngày trước)
            cutoff_time = datetime.utcnow() - timedelta(days=days)

            query = self.db.collection('internal_invoices').where(
                filter=FieldFilter('createdAt', '>=', cutoff_time)
            ).order_by('createdAt', direction='DESCENDING')

            docs = query.get()

            invoices = []
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id

                # Convert datetime to ISO string for JSON serialization
                if 'createdAt' in data and hasattr(data['createdAt'], 'isoformat'):
                    data['createdAt'] = data['createdAt'].isoformat()

                invoices.append(data)

            logger.info(f"Retrieved {len(invoices)} recent AI invoices (last {days} days)")
            return invoices

        except Exception as e:
            logger.error(f"Error getting recent AI invoices: {e}")
            return []

    def get_ai_invoice_by_id(self, doc_id: str) -> Optional[Dict]:
        """
        Lấy chi tiết 1 hóa đơn AI theo ID

        Args:
            doc_id: Document ID trong Firestore

        Returns:
            Dict hoặc None nếu không tìm thấy
        """
        try:
            doc = self.db.collection('internal_invoices').document(doc_id).get()

            if not doc.exists:
                return None

            data = doc.to_dict()
            data['id'] = doc.id

            # Convert datetime to ISO string
            if 'createdAt' in data and hasattr(data['createdAt'], 'isoformat'):
                data['createdAt'] = data['createdAt'].isoformat()

            return data

        except Exception as e:
            logger.error(f"Error getting AI invoice by ID: {e}")
            return None

    def delete_internal_invoice(self, doc_id: str) -> bool:
        """Xóa hóa đơn từ folder local"""
        try:
            self.db.collection('internal_invoices').document(doc_id).delete()
            logger.info(f"Deleted internal invoice: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting internal invoice: {e}")
            return False

    # =========================================================================
    # CLEAR ALL INVOICES
    # =========================================================================

    def clear_all_tax_invoices(self) -> Dict:
        """
        Xóa tất cả hóa đơn từ cơ quan thuế

        Returns:
            {
                'success': True/False,
                'deleted': số lượng đã xóa,
                'error': thông báo lỗi (nếu có)
            }
        """
        try:
            collection_ref = self.db.collection('tax_invoices')
            docs = collection_ref.stream()

            deleted_count = 0
            batch = self.db.batch()
            batch_count = 0

            for doc in docs:
                batch.delete(doc.reference)
                batch_count += 1
                deleted_count += 1

                # Firestore batch limit is 500
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0

            # Commit remaining
            if batch_count > 0:
                batch.commit()

            logger.info(f"Cleared {deleted_count} tax invoices")
            return {
                'success': True,
                'deleted': deleted_count
            }

        except Exception as e:
            logger.error(f"Error clearing tax invoices: {e}")
            return {
                'success': False,
                'deleted': 0,
                'error': str(e)
            }

    def clear_all_internal_invoices(self) -> Dict:
        """
        Xóa tất cả hóa đơn từ AI (internal_invoices)

        Returns:
            {
                'success': True/False,
                'deleted': số lượng đã xóa,
                'error': thông báo lỗi (nếu có)
            }
        """
        try:
            collection_ref = self.db.collection('internal_invoices')
            docs = collection_ref.stream()

            deleted_count = 0
            batch = self.db.batch()
            batch_count = 0

            for doc in docs:
                batch.delete(doc.reference)
                batch_count += 1
                deleted_count += 1

                # Firestore batch limit is 500
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0

            # Commit remaining
            if batch_count > 0:
                batch.commit()

            logger.info(f"Cleared {deleted_count} internal invoices")
            return {
                'success': True,
                'deleted': deleted_count
            }

        except Exception as e:
            logger.error(f"Error clearing internal invoices: {e}")
            return {
                'success': False,
                'deleted': 0,
                'error': str(e)
            }

    def clear_all_invoices(self) -> Dict:
        """
        Xóa tất cả hóa đơn từ cả 2 collection

        Returns:
            {
                'success': True/False,
                'taxDeleted': số hóa đơn thuế đã xóa,
                'internalDeleted': số hóa đơn AI đã xóa,
                'error': thông báo lỗi (nếu có)
            }
        """
        try:
            tax_result = self.clear_all_tax_invoices()
            internal_result = self.clear_all_internal_invoices()

            return {
                'success': tax_result['success'] and internal_result['success'],
                'taxDeleted': tax_result.get('deleted', 0),
                'internalDeleted': internal_result.get('deleted', 0)
            }

        except Exception as e:
            logger.error(f"Error clearing all invoices: {e}")
            return {
                'success': False,
                'taxDeleted': 0,
                'internalDeleted': 0,
                'error': str(e)
            }

    # =========================================================================
    # RECONCILIATION (đối chiếu)
    # =========================================================================

    def reconcile_invoices(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        month: Optional[int] = None,
        year: Optional[int] = None
    ) -> Dict:
        """
        Đối chiếu hóa đơn từ 2 nguồn

        Returns:
            {
                summary: {
                    totalTax, totalInternal, matched, missingInternal,
                    missingTax, mismatch
                },
                reconciliations: List[reconciliation_record]
            }
        """
        try:
            # Lấy dữ liệu từ 2 nguồn
            tax_invoices = self.get_tax_invoices(from_date, to_date, month, year)
            internal_invoices = self.get_internal_invoices(from_date, to_date, month, year)

            # Tạo map để lookup nhanh
            # Key: invoiceNo|taxCode
            tax_map = {}
            for inv in tax_invoices:
                key = f"{inv['invoiceNo']}|{inv['sellerTaxCode']}"
                tax_map[key] = inv

            internal_map = {}
            for inv in internal_invoices:
                key = f"{inv['invoiceNo']}|{inv['supplierTaxCode']}"
                internal_map[key] = inv

            # Tập hợp tất cả keys
            all_keys = set(tax_map.keys()) | set(internal_map.keys())

            # Đối chiếu từng hóa đơn
            reconciliations = []
            summary = {
                'totalTax': len(tax_invoices),
                'totalInternal': len(internal_invoices),
                'matched': 0,
                'missingInternal': 0,
                'missingTax': 0,
                'mismatch': 0
            }

            for key in all_keys:
                tax_inv = tax_map.get(key)
                internal_inv = internal_map.get(key)

                recon_record = {
                    'invoiceKey': key,
                    'taxInvoiceId': tax_inv['id'] if tax_inv else None,
                    'internalInvoiceId': internal_inv['id'] if internal_inv else None,
                    'status': None,
                    'diff': {
                        'totalAmount': 0,
                        'vatAmount': 0
                    },
                    'checkedAt': datetime.utcnow()
                }

                if tax_inv and internal_inv:
                    # Có cả 2 bên - kiểm tra chi tiết
                    total_diff = tax_inv['totalAmount'] - internal_inv['totalAmount']
                    vat_diff = tax_inv['vatAmount'] - internal_inv['vatAmount']

                    if abs(total_diff) < 1 and abs(vat_diff) < 1:
                        recon_record['status'] = 'MATCH'
                        summary['matched'] += 1
                    else:
                        recon_record['status'] = 'MISMATCH'
                        recon_record['diff']['totalAmount'] = total_diff
                        recon_record['diff']['vatAmount'] = vat_diff
                        summary['mismatch'] += 1

                elif tax_inv and not internal_inv:
                    recon_record['status'] = 'MISSING_INTERNAL'
                    summary['missingInternal'] += 1

                elif not tax_inv and internal_inv:
                    recon_record['status'] = 'MISSING_TAX'
                    summary['missingTax'] += 1

                # Thêm thông tin chi tiết để UI hiển thị
                if tax_inv:
                    recon_record['taxData'] = {
                        'invoiceNo': tax_inv['invoiceNo'],
                        'invoiceDate': tax_inv['invoiceDate'],
                        'supplierName': tax_inv['supplierName'],
                        'supplierTaxCode': tax_inv['supplierTaxCode'],
                        'totalAmount': tax_inv['totalAmount'],
                        'vatAmount': tax_inv['vatAmount']
                    }

                if internal_inv:
                    recon_record['internalData'] = {
                        'invoiceNo': internal_inv['invoiceNo'],
                        'invoiceDate': internal_inv['invoiceDate'],
                        'supplierName': internal_inv['supplierName'],
                        'supplierTaxCode': internal_inv['supplierTaxCode'],
                        'totalAmount': internal_inv['totalAmount'],
                        'vatAmount': internal_inv['vatAmount'],
                        'ocrConfidence': internal_inv.get('ocrConfidence', 0)
                    }

                reconciliations.append(recon_record)

            # Lưu kết quả đối chiếu vào Firestore
            self._save_reconciliation_results(reconciliations, month, year)

            logger.info(f"Reconciliation complete: {summary}")

            return {
                'summary': summary,
                'reconciliations': reconciliations
            }

        except Exception as e:
            logger.error(f"Error reconciling invoices: {e}")
            return {
                'summary': {},
                'reconciliations': [],
                'error': str(e)
            }

    def _save_reconciliation_results(
        self,
        reconciliations: List[Dict],
        month: Optional[int] = None,
        year: Optional[int] = None
    ):
        """Lưu kết quả đối chiếu vào Firestore"""
        try:
            # Xóa kết quả cũ của tháng/năm này
            period_key = f"{year or 'all'}-{month or 'all'}"

            old_docs = self.db.collection('invoice_reconciliation').where(
                filter=FieldFilter('periodKey', '==', period_key)
            ).get()

            for doc in old_docs:
                doc.reference.delete()

            # Lưu kết quả mới
            batch = self.db.batch()

            for recon in reconciliations:
                recon['periodKey'] = period_key
                doc_ref = self.db.collection('invoice_reconciliation').document()
                batch.set(doc_ref, recon)

            batch.commit()

            logger.info(f"Saved {len(reconciliations)} reconciliation records")

        except Exception as e:
            logger.error(f"Error saving reconciliation results: {e}")

    def get_sync_summary(
        self,
        month: Optional[int] = None,
        year: Optional[int] = None
    ) -> Dict:
        """
        Lấy tóm tắt đồng bộ cho tháng/năm
        """
        try:
            period_key = f"{year or 'all'}-{month or 'all'}"

            docs = self.db.collection('invoice_reconciliation').where(
                filter=FieldFilter('periodKey', '==', period_key)
            ).get()

            summary = {
                'totalTax': 0,
                'totalInternal': 0,
                'matched': 0,
                'missingInternal': 0,
                'missingTax': 0,
                'mismatch': 0
            }

            for doc in docs:
                data = doc.to_dict()
                status = data.get('status')

                if data.get('taxInvoiceId'):
                    summary['totalTax'] += 1
                if data.get('internalInvoiceId'):
                    summary['totalInternal'] += 1

                if status == 'MATCH':
                    summary['matched'] += 1
                elif status == 'MISSING_INTERNAL':
                    summary['missingInternal'] += 1
                elif status == 'MISSING_TAX':
                    summary['missingTax'] += 1
                elif status == 'MISMATCH':
                    summary['mismatch'] += 1

            return summary

        except Exception as e:
            logger.error(f"Error getting sync summary: {e}")
            return {}


# Singleton instance
supplies_invoice_service = SuppliesInvoiceService()
