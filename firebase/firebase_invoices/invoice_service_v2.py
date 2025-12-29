"""
INVOICE SERVICE V2 - SCALABLE VERSION
Thiết kế cho 100.000+ hóa đơn với pagination và optimized queries

Collection: invoices (unified - thay thế tax_invoices + internal_invoices)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from google.cloud.firestore_v1.base_query import FieldFilter
from firebase_admin import firestore

logger = logging.getLogger(__name__)


class InvoiceServiceV2:
    """
    Scalable Invoice Service với:
    - Unified collection (invoices)
    - Pagination support
    - Optimized queries với composite indexes
    - Supplier caching
    """

    # Constants
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 100
    COLLECTION_INVOICES = 'invoices'
    COLLECTION_SUPPLIERS = 'suppliers'
    COLLECTION_SYNC_LOGS = 'sync_logs'

    # Source types
    SOURCE_TAX_PORTAL = 'TAX_PORTAL'
    SOURCE_AI_PDF = 'AI_PDF'

    # Reconcile status
    STATUS_PENDING = 'PENDING'
    STATUS_MATCHED = 'MATCHED'
    STATUS_UNMATCHED = 'UNMATCHED'
    STATUS_MISMATCH = 'MISMATCH'

    def __init__(self):
        self.db = firestore.client()
        logger.info("InvoiceServiceV2 initialized")

    # =========================================================================
    # QUERY METHODS (với pagination)
    # =========================================================================

    def get_invoices(
        self,
        source: Optional[str] = None,
        year: Optional[int] = None,
        month_key: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        supplier_tax_code: Optional[str] = None,
        reconcile_status: Optional[str] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        cursor_doc_id: Optional[str] = None,
        direction: str = 'next'
    ) -> Dict:
        """
        Query hóa đơn với filter và pagination

        Args:
            source: 'TAX_PORTAL' | 'AI_PDF' | None (all)
            year: Năm (e.g., 2024)
            month_key: Tháng (e.g., '2024-12')
            from_date: Từ ngày (YYYY-MM-DD)
            to_date: Đến ngày (YYYY-MM-DD)
            supplier_tax_code: MST nhà cung cấp
            reconcile_status: Trạng thái đối chiếu
            page_size: Số records/trang (max 100)
            cursor_doc_id: Document ID cursor cho pagination
            direction: 'next' | 'prev'

        Returns:
            {
                'invoices': [...],
                'pagination': {
                    'hasNext': bool,
                    'hasPrev': bool,
                    'firstDocId': str,
                    'lastDocId': str,
                    'pageSize': int,
                    'totalEstimate': int  # Ước tính (không chính xác 100%)
                }
            }
        """
        try:
            # Validate page_size
            page_size = min(page_size, self.MAX_PAGE_SIZE)

            # Build query
            query = self.db.collection(self.COLLECTION_INVOICES)

            # Apply filters
            if source:
                query = query.where(filter=FieldFilter('source', '==', source))

            if supplier_tax_code:
                query = query.where(filter=FieldFilter('supplierTaxCode', '==', supplier_tax_code))

            if reconcile_status:
                query = query.where(filter=FieldFilter('reconcileStatus', '==', reconcile_status))

            # Date filters (mutually exclusive priority)
            if month_key:
                query = query.where(filter=FieldFilter('monthKey', '==', month_key))
            elif year:
                query = query.where(filter=FieldFilter('year', '==', year))
            elif from_date or to_date:
                if from_date:
                    from_dt = datetime.strptime(from_date, '%Y-%m-%d')
                    query = query.where(filter=FieldFilter('issueDate', '>=', from_dt))
                if to_date:
                    to_dt = datetime.strptime(to_date, '%Y-%m-%d')
                    # Add 1 day to include the end date
                    to_dt = to_dt + timedelta(days=1)
                    query = query.where(filter=FieldFilter('issueDate', '<', to_dt))

            # Order by issueDate descending
            query = query.order_by('issueDate', direction=firestore.Query.DESCENDING)

            # Apply cursor for pagination
            if cursor_doc_id:
                cursor_doc = self.db.collection(self.COLLECTION_INVOICES).document(cursor_doc_id).get()
                if cursor_doc.exists:
                    if direction == 'next':
                        query = query.start_after(cursor_doc)
                    else:
                        query = query.end_before(cursor_doc)

            # Fetch one extra to check hasNext
            query = query.limit(page_size + 1)

            # Execute query
            docs = list(query.stream())

            # Check pagination
            has_next = len(docs) > page_size
            if has_next:
                docs = docs[:page_size]

            # Convert to dict
            invoices = []
            first_doc_id = None
            last_doc_id = None

            for i, doc in enumerate(docs):
                data = doc.to_dict()
                data['id'] = doc.id

                # Convert Timestamp to ISO string
                if 'issueDate' in data and data['issueDate']:
                    data['issueDate'] = data['issueDate'].isoformat()
                if 'createdAt' in data and data['createdAt']:
                    data['createdAt'] = data['createdAt'].isoformat()
                if 'updatedAt' in data and data['updatedAt']:
                    data['updatedAt'] = data['updatedAt'].isoformat()

                invoices.append(data)

                if i == 0:
                    first_doc_id = doc.id
                last_doc_id = doc.id

            return {
                'invoices': invoices,
                'pagination': {
                    'hasNext': has_next,
                    'hasPrev': cursor_doc_id is not None,
                    'firstDocId': first_doc_id,
                    'lastDocId': last_doc_id,
                    'pageSize': page_size,
                    'count': len(invoices)
                }
            }

        except Exception as e:
            logger.error(f"Error querying invoices: {e}")
            return {
                'invoices': [],
                'pagination': {
                    'hasNext': False,
                    'hasPrev': False,
                    'firstDocId': None,
                    'lastDocId': None,
                    'pageSize': page_size,
                    'count': 0
                },
                'error': str(e)
            }

    def get_invoices_default(self, source: Optional[str] = None) -> Dict:
        """
        Load mặc định: 30 ngày gần nhất, 50 records
        """
        from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        return self.get_invoices(
            source=source,
            from_date=from_date,
            page_size=self.DEFAULT_PAGE_SIZE
        )

    # =========================================================================
    # CREATE METHODS
    # =========================================================================

    def create_invoice(self, invoice_data: Dict, source: str) -> Tuple[bool, str, Optional[str]]:
        """
        Tạo hóa đơn mới (unified method cho cả TAX_PORTAL và AI_PDF)

        Args:
            invoice_data: Dữ liệu hóa đơn
            source: 'TAX_PORTAL' | 'AI_PDF'

        Returns:
            (success, message, doc_id)
        """
        try:
            # Đảm bảo invoiceNo luôn là string để giữ nguyên số 0 đầu (VD: '00000001')
            invoice_no = str(invoice_data.get('invoiceNo', '')).strip()
            supplier_tax_code = str(invoice_data.get('supplierTaxCode', '') or \
                               invoice_data.get('supplier', {}).get('taxCode', '')).strip()

            if not invoice_no or not supplier_tax_code:
                return False, "Thiếu số hóa đơn hoặc MST nhà cung cấp", None

            # Chuẩn hóa số hóa đơn để compare (loại bỏ số 0 đầu)
            normalized_invoice_no = self._normalize_invoice_no(invoice_no)

            # Create invoice key for duplicate check (dùng số đã chuẩn hóa)
            invoice_key = f"{normalized_invoice_no}|{supplier_tax_code}"

            # Check duplicate
            existing = self.db.collection(self.COLLECTION_INVOICES).where(
                filter=FieldFilter('invoiceKey', '==', invoice_key)
            ).where(
                filter=FieldFilter('source', '==', source)
            ).limit(1).get()

            if len(list(existing)) > 0:
                return False, f"Hóa đơn {invoice_no} từ nguồn {source} đã tồn tại", None

            # Parse date
            issue_date_str = invoice_data.get('invoiceDate', '') or invoice_data.get('issueDate', '')
            issue_date = self._parse_date(issue_date_str)

            # Extract supplier info
            supplier = invoice_data.get('supplier', {})
            supplier_name = supplier.get('name', '') or invoice_data.get('supplierName', '')
            supplier_address = supplier.get('address', '') or invoice_data.get('supplierAddress', '')

            # Extract buyer info
            buyer = invoice_data.get('buyer', {})
            buyer_name = buyer.get('name', '') or invoice_data.get('buyerName', '')
            buyer_tax_code = buyer.get('taxCode', '') or invoice_data.get('buyerTaxCode', '')

            # Build document
            doc_data = {
                # Keys
                'invoiceKey': invoice_key,
                'invoiceNo': invoice_no,  # Giữ nguyên số hóa đơn gốc (VD: '00084538')
                'normalizedInvoiceNo': normalized_invoice_no,  # Số đã chuẩn hóa để compare (VD: '84538')
                'invoiceSymbol': invoice_data.get('invoiceSymbol', ''),

                # Supplier
                'supplierName': supplier_name,
                'supplierTaxCode': supplier_tax_code,
                'supplierAddress': supplier_address,

                # Buyer
                'buyerName': buyer_name,
                'buyerTaxCode': buyer_tax_code,

                # Dates (indexed fields)
                'issueDate': issue_date,
                'issueDateKey': issue_date.strftime('%Y-%m-%d') if issue_date else '',
                'monthKey': issue_date.strftime('%Y-%m') if issue_date else '',
                'year': issue_date.year if issue_date else 0,

                # Amounts
                'totalBeforeVat': float(invoice_data.get('totalBeforeVat', 0)),
                'vatRate': float(invoice_data.get('vatRate', 0)),
                'vatAmount': float(invoice_data.get('vatAmount', 0)),
                'totalAmount': float(invoice_data.get('totalAmount', 0)),

                # Source & Status
                'source': source,
                'reconcileStatus': self.STATUS_PENDING,
                'matchedInvoiceId': None,

                # Metadata
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow()
            }

            # Add items for AI_PDF source
            if source == self.SOURCE_AI_PDF:
                items = []
                for item in invoice_data.get('items', []):
                    items.append({
                        'name': item.get('name', ''),
                        'unit': item.get('unit', ''),
                        'quantity': float(item.get('quantity', 0)),
                        'unitPrice': float(item.get('unitPrice', 0)),
                        'amount': float(item.get('amount', 0))
                    })
                doc_data['items'] = items

            # Save to Firestore
            doc_ref = self.db.collection(self.COLLECTION_INVOICES).add(doc_data)
            doc_id = doc_ref[1].id

            # Update supplier stats (async in production)
            self._update_supplier_stats(supplier_tax_code, supplier_name, supplier_address)

            logger.info(f"Created invoice: {invoice_no} | source={source}")
            return True, "Tạo hóa đơn thành công", doc_id

        except Exception as e:
            logger.error(f"Error creating invoice: {e}")
            return False, f"Lỗi: {str(e)}", None

    def create_invoice_from_tax_portal(self, invoice_data: Dict) -> Tuple[bool, str, Optional[str]]:
        """Wrapper cho hóa đơn từ trang thuế"""
        return self.create_invoice(invoice_data, self.SOURCE_TAX_PORTAL)

    def create_invoice_from_ai(self, invoice_data: Dict) -> Tuple[bool, str, Optional[str]]:
        """Wrapper cho hóa đơn từ AI PDF"""
        return self.create_invoice(invoice_data, self.SOURCE_AI_PDF)

    # =========================================================================
    # BATCH IMPORT
    # =========================================================================

    def batch_import_invoices(self, invoices: List[Dict], source: str) -> Dict:
        """
        Import nhiều hóa đơn (batch)

        Returns:
            {
                'success': bool,
                'imported': int,
                'duplicates': int,
                'failed': int,
                'errors': [...]
            }
        """
        imported = 0
        duplicates = 0
        failed = 0
        errors = []

        for inv in invoices:
            success, msg, doc_id = self.create_invoice(inv, source)
            if success:
                imported += 1
            elif 'đã tồn tại' in msg:
                duplicates += 1
            else:
                failed += 1
                errors.append(f"{inv.get('invoiceNo', 'N/A')}: {msg}")

        # Log sync action
        self._log_sync_action('IMPORT', source, len(invoices), imported, failed, duplicates)

        return {
            'success': failed == 0,
            'imported': imported,
            'duplicates': duplicates,
            'failed': failed,
            'errors': errors[:10]  # Limit errors to 10
        }

    # =========================================================================
    # SUPPLIER METHODS
    # =========================================================================

    def get_suppliers(self, search: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """
        Lấy danh sách nhà cung cấp (cho dropdown/autocomplete)

        Args:
            search: Tìm theo tên hoặc MST
            limit: Số lượng tối đa

        Returns:
            List of suppliers
        """
        try:
            query = self.db.collection(self.COLLECTION_SUPPLIERS)

            # Note: Firestore không hỗ trợ LIKE query
            # Nếu cần search, phải dùng Algolia hoặc client-side filter

            query = query.order_by('invoiceCount', direction=firestore.Query.DESCENDING)
            query = query.limit(limit)

            docs = query.stream()
            suppliers = []

            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id

                # Client-side filter (không optimal nhưng OK cho supplier list nhỏ)
                if search:
                    search_lower = search.lower()
                    name_match = search_lower in data.get('name', '').lower()
                    code_match = search_lower in data.get('taxCode', '').lower()
                    if not (name_match or code_match):
                        continue

                suppliers.append(data)

            return suppliers

        except Exception as e:
            logger.error(f"Error getting suppliers: {e}")
            return []

    def _update_supplier_stats(self, tax_code: str, name: str, address: str = ''):
        """Update supplier stats (internal)"""
        try:
            doc_ref = self.db.collection(self.COLLECTION_SUPPLIERS).document(tax_code)
            doc = doc_ref.get()

            if doc.exists:
                doc_ref.update({
                    'invoiceCount': firestore.Increment(1),
                    'lastInvoiceDate': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                })
            else:
                doc_ref.set({
                    'taxCode': tax_code,
                    'name': name,
                    'address': address,
                    'invoiceCount': 1,
                    'totalAmount': 0,
                    'lastInvoiceDate': datetime.utcnow(),
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                })
        except Exception as e:
            logger.error(f"Error updating supplier stats: {e}")

    # =========================================================================
    # DELETE METHODS
    # =========================================================================

    def delete_invoice(self, doc_id: str) -> bool:
        """Xóa 1 hóa đơn"""
        try:
            self.db.collection(self.COLLECTION_INVOICES).document(doc_id).delete()
            logger.info(f"Deleted invoice: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting invoice: {e}")
            return False

    def clear_invoices_by_source(self, source: str) -> Dict:
        """Xóa tất cả hóa đơn theo nguồn"""
        try:
            query = self.db.collection(self.COLLECTION_INVOICES).where(
                filter=FieldFilter('source', '==', source)
            )

            docs = query.stream()
            deleted_count = 0
            batch = self.db.batch()
            batch_count = 0

            for doc in docs:
                batch.delete(doc.reference)
                batch_count += 1
                deleted_count += 1

                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0

            if batch_count > 0:
                batch.commit()

            self._log_sync_action('DELETE', source, deleted_count, deleted_count, 0, 0)

            return {'success': True, 'deleted': deleted_count}

        except Exception as e:
            logger.error(f"Error clearing invoices by source: {e}")
            return {'success': False, 'deleted': 0, 'error': str(e)}

    def clear_all_invoices(self) -> Dict:
        """Xóa tất cả hóa đơn"""
        tax_result = self.clear_invoices_by_source(self.SOURCE_TAX_PORTAL)
        ai_result = self.clear_invoices_by_source(self.SOURCE_AI_PDF)

        return {
            'success': tax_result['success'] and ai_result['success'],
            'taxDeleted': tax_result.get('deleted', 0),
            'aiDeleted': ai_result.get('deleted', 0)
        }

    # =========================================================================
    # RECONCILIATION
    # =========================================================================

    def get_reconciliation_summary(
        self,
        month_key: Optional[str] = None,
        year: Optional[int] = None
    ) -> Dict:
        """
        Lấy tổng hợp đối chiếu

        Returns:
            {
                'taxPortalCount': int,
                'aiPdfCount': int,
                'matchedCount': int,
                'unmatchedCount': int,
                'mismatchCount': int
            }
        """
        try:
            base_query = self.db.collection(self.COLLECTION_INVOICES)

            if month_key:
                base_query = base_query.where(filter=FieldFilter('monthKey', '==', month_key))
            elif year:
                base_query = base_query.where(filter=FieldFilter('year', '==', year))

            # Count by source
            tax_docs = base_query.where(
                filter=FieldFilter('source', '==', self.SOURCE_TAX_PORTAL)
            ).count().get()

            ai_docs = base_query.where(
                filter=FieldFilter('source', '==', self.SOURCE_AI_PDF)
            ).count().get()

            # Count by status
            matched_docs = base_query.where(
                filter=FieldFilter('reconcileStatus', '==', self.STATUS_MATCHED)
            ).count().get()

            unmatched_docs = base_query.where(
                filter=FieldFilter('reconcileStatus', '==', self.STATUS_UNMATCHED)
            ).count().get()

            mismatch_docs = base_query.where(
                filter=FieldFilter('reconcileStatus', '==', self.STATUS_MISMATCH)
            ).count().get()

            return {
                'taxPortalCount': tax_docs[0][0].value if tax_docs else 0,
                'aiPdfCount': ai_docs[0][0].value if ai_docs else 0,
                'matchedCount': matched_docs[0][0].value if matched_docs else 0,
                'unmatchedCount': unmatched_docs[0][0].value if unmatched_docs else 0,
                'mismatchCount': mismatch_docs[0][0].value if mismatch_docs else 0
            }

        except Exception as e:
            logger.error(f"Error getting reconciliation summary: {e}")
            return {
                'taxPortalCount': 0,
                'aiPdfCount': 0,
                'matchedCount': 0,
                'unmatchedCount': 0,
                'mismatchCount': 0,
                'error': str(e)
            }

    def run_reconciliation(self, month_key: Optional[str] = None) -> Dict:
        """
        Chạy đối chiếu tự động

        Algorithm:
        1. Lấy tất cả hóa đơn TAX_PORTAL theo month_key
        2. Với mỗi hóa đơn, tìm match trong AI_PDF bằng invoiceKey
        3. So sánh totalAmount và vatAmount
        4. Update reconcileStatus
        """
        try:
            # Get TAX_PORTAL invoices
            tax_query = self.db.collection(self.COLLECTION_INVOICES).where(
                filter=FieldFilter('source', '==', self.SOURCE_TAX_PORTAL)
            )
            if month_key:
                tax_query = tax_query.where(filter=FieldFilter('monthKey', '==', month_key))

            tax_docs = list(tax_query.stream())
            logger.info(f"Found {len(tax_docs)} TAX_PORTAL invoices for reconciliation")

            matched = 0
            unmatched = 0
            mismatch = 0
            batch = self.db.batch()
            batch_count = 0

            for tax_doc in tax_docs:
                tax_data = tax_doc.to_dict()
                invoice_key = tax_data.get('invoiceKey', '')

                # Find matching AI_PDF invoice
                ai_query = self.db.collection(self.COLLECTION_INVOICES).where(
                    filter=FieldFilter('source', '==', self.SOURCE_AI_PDF)
                ).where(
                    filter=FieldFilter('invoiceKey', '==', invoice_key)
                ).limit(1)

                ai_docs = list(ai_query.stream())

                if not ai_docs:
                    # No match found
                    batch.update(tax_doc.reference, {
                        'reconcileStatus': self.STATUS_UNMATCHED,
                        'updatedAt': datetime.utcnow()
                    })
                    unmatched += 1
                else:
                    ai_doc = ai_docs[0]
                    ai_data = ai_doc.to_dict()

                    # Compare amounts
                    tax_total = tax_data.get('totalAmount', 0)
                    ai_total = ai_data.get('totalAmount', 0)
                    tax_vat = tax_data.get('vatAmount', 0)
                    ai_vat = ai_data.get('vatAmount', 0)

                    # Allow 1 VND tolerance
                    if abs(tax_total - ai_total) <= 1 and abs(tax_vat - ai_vat) <= 1:
                        status = self.STATUS_MATCHED
                        matched += 1
                    else:
                        status = self.STATUS_MISMATCH
                        mismatch += 1

                    # Update both documents
                    batch.update(tax_doc.reference, {
                        'reconcileStatus': status,
                        'matchedInvoiceId': ai_doc.id,
                        'updatedAt': datetime.utcnow()
                    })
                    batch.update(ai_doc.reference, {
                        'reconcileStatus': status,
                        'matchedInvoiceId': tax_doc.id,
                        'updatedAt': datetime.utcnow()
                    })
                    batch_count += 1

                batch_count += 1
                if batch_count >= 250:  # Half of 500 because we update 2 docs
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0

            if batch_count > 0:
                batch.commit()

            # Find AI invoices without TAX match
            ai_unmatched_query = self.db.collection(self.COLLECTION_INVOICES).where(
                filter=FieldFilter('source', '==', self.SOURCE_AI_PDF)
            ).where(
                filter=FieldFilter('reconcileStatus', '==', self.STATUS_PENDING)
            )
            if month_key:
                ai_unmatched_query = ai_unmatched_query.where(
                    filter=FieldFilter('monthKey', '==', month_key)
                )

            ai_unmatched_docs = list(ai_unmatched_query.stream())
            batch = self.db.batch()
            batch_count = 0

            for doc in ai_unmatched_docs:
                batch.update(doc.reference, {
                    'reconcileStatus': self.STATUS_UNMATCHED,
                    'updatedAt': datetime.utcnow()
                })
                unmatched += 1
                batch_count += 1

                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0

            if batch_count > 0:
                batch.commit()

            self._log_sync_action('RECONCILE', 'ALL', len(tax_docs), matched, mismatch, unmatched)

            return {
                'success': True,
                'processed': len(tax_docs),
                'matched': matched,
                'unmatched': unmatched,
                'mismatch': mismatch
            }

        except Exception as e:
            logger.error(f"Error running reconciliation: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string to datetime"""
        if not date_str:
            return None

        # Try common formats
        formats = [
            '%Y-%m-%d',           # ISO
            '%d/%m/%Y',           # Vietnamese
            '%d-%m-%Y',
            '%Y/%m/%d',
            '%d.%m.%Y',
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        logger.warning(f"Could not parse date: {date_str}")
        return None

    def _normalize_invoice_no(self, invoice_no: str) -> str:
        """
        Chuẩn hóa số hóa đơn để so khớp
        Loại bỏ số 0 đầu để compare: '00084538' -> '84538'
        Nhưng vẫn giữ nguyên số hóa đơn gốc khi lưu
        """
        if not invoice_no:
            return ''
        # Loại bỏ số 0 đầu để compare
        return invoice_no.lstrip('0') or '0'

    def _log_sync_action(
        self,
        action: str,
        source: str,
        total: int,
        success: int,
        fail: int,
        duplicate: int
    ):
        """Log sync action for audit trail"""
        try:
            self.db.collection(self.COLLECTION_SYNC_LOGS).add({
                'action': action,
                'source': source,
                'totalProcessed': total,
                'successCount': success,
                'failCount': fail,
                'duplicateCount': duplicate,
                'createdAt': datetime.utcnow()
            })
        except Exception as e:
            logger.error(f"Error logging sync action: {e}")


# Singleton instance
invoice_service_v2 = InvoiceServiceV2()
