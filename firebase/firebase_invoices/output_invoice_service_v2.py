"""
OUTPUT INVOICE SERVICE V2
Service cho đồng bộ hóa đơn đầu ra
- Trang thuế (TAX_PORTAL_OUTPUT) vs Local invoices (từ invoices collection)

Collections:
- output_tax_invoices: Hóa đơn đầu ra từ trang thuế (import XML)
- output_local_invoices: Hóa đơn đầu ra từ local (sync từ invoices collection)
- output_invoice_reconciliation: Kết quả đối chiếu

Features:
- Import XML từ trang thuế (hóa đơn đầu ra)
- Sync từ invoices collection (local)
- Đối chiếu TAX_PORTAL_OUTPUT vs LOCAL
- Pagination với cursor-based navigation
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from google.cloud import firestore

from firebase.init_firebase import init_firestore

logger = logging.getLogger(__name__)


class OutputInvoiceServiceV2:
    """
    Service cho hóa đơn đầu ra
    """

    # Collection names
    COLLECTION_TAX_INVOICES = 'output_tax_invoices'
    COLLECTION_LOCAL_INVOICES = 'output_local_invoices'
    COLLECTION_RECONCILIATION = 'output_invoice_reconciliation'
    COLLECTION_INVOICES = 'invoices'  # Source collection for local invoices

    # Source types
    SOURCE_TAX_PORTAL_OUTPUT = 'TAX_PORTAL_OUTPUT'
    SOURCE_LOCAL = 'LOCAL'

    # Status
    STATUS_PENDING = 'PENDING'
    STATUS_MATCHED = 'MATCHED'
    STATUS_UNMATCHED = 'UNMATCHED'
    STATUS_MISMATCH = 'MISMATCH'

    def __init__(self):
        self._db = None
        logger.info("OutputInvoiceServiceV2 initialized (lazy)")

    @property
    def db(self):
        """Lazy initialization của Firestore client"""
        if self._db is None:
            # Sử dụng cùng Firebase project với invoice_service_v2
            self._db = init_firestore("FIREBASE_SERVICE_ACCOUNT_SUPPLIES_INVOICES")
            logger.info("OutputInvoiceServiceV2 Firestore client initialized")
        return self._db

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def get_invoices(
        self,
        source: Optional[str] = None,
        year: Optional[int] = None,
        month_key: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        customer_name: Optional[str] = None,
        reconcile_status: Optional[str] = None,
        page_size: int = 25,
        cursor_doc_id: Optional[str] = None,
        direction: str = 'next'
    ) -> Dict:
        """
        Query hóa đơn đầu ra với filter và pagination
        """
        try:
            # Determine collection
            collection_name = (
                self.COLLECTION_TAX_INVOICES
                if source == self.SOURCE_TAX_PORTAL_OUTPUT
                else self.COLLECTION_LOCAL_INVOICES
            )

            query = self.db.collection(collection_name)

            # Client-side filters
            use_client_side_customer_filter = bool(customer_name)
            use_client_side_status_filter = bool(reconcile_status)

            # Date range filtering
            if month_key:
                parts = month_key.split('-')
                if len(parts) == 2:
                    y, m = int(parts[0]), int(parts[1])
                    start_date = f"{y}-{m:02d}-01"
                    if m == 12:
                        end_date = f"{y + 1}-01-01"
                    else:
                        end_date = f"{y}-{m + 1:02d}-01"
                    query = query.where('invoiceDate', '>=', start_date)
                    query = query.where('invoiceDate', '<', end_date)
            elif year:
                query = query.where('invoiceDate', '>=', f'{year}-01-01')
                query = query.where('invoiceDate', '<', f'{year + 1}-01-01')
            elif from_date or to_date:
                if from_date:
                    query = query.where('invoiceDate', '>=', from_date)
                if to_date:
                    query = query.where('invoiceDate', '<=', to_date)

            # Order and limit
            query = query.order_by('invoiceDate', direction=firestore.Query.DESCENDING)
            query = query.limit(page_size + 1)

            # Cursor pagination
            if cursor_doc_id:
                cursor_doc = self.db.collection(collection_name).document(cursor_doc_id).get()
                if cursor_doc.exists:
                    if direction == 'next':
                        query = query.start_after(cursor_doc)
                    else:
                        query = query.end_before(cursor_doc)

            # Execute query
            docs = list(query.stream())

            # Process results
            invoices = []
            first_doc_id = None
            last_doc_id = None

            for doc in docs[:page_size]:
                data = doc.to_dict()

                # Client-side customer filtering
                if use_client_side_customer_filter:
                    doc_customer = data.get('customerName', '') or data.get('buyerName', '')
                    if customer_name.lower() not in doc_customer.lower():
                        continue

                # Client-side status filtering
                if use_client_side_status_filter:
                    doc_status = data.get('reconcileStatus', self.STATUS_PENDING)
                    if doc_status != reconcile_status:
                        continue

                normalized = self._normalize_invoice_data(data, source or self.SOURCE_TAX_PORTAL_OUTPUT)
                normalized['id'] = doc.id

                invoices.append(normalized)

                if first_doc_id is None:
                    first_doc_id = doc.id
                last_doc_id = doc.id

            has_next = len(docs) > page_size

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
            logger.exception(f"Error getting output invoices: {e}")
            return {
                'invoices': [],
                'pagination': {
                    'hasNext': False,
                    'hasPrev': False,
                    'firstDocId': None,
                    'lastDocId': None,
                    'pageSize': page_size,
                    'count': 0
                }
            }

    def _normalize_invoice_data(self, data: Dict, source: str) -> Dict:
        """Normalize invoice data to unified format"""
        customer_info = data.get('customer', {})

        return {
            'invoiceNo': data.get('invoiceNo', ''),
            'invoiceSymbol': data.get('invoiceSymbol', ''),
            'invoiceDate': data.get('invoiceDate', ''),
            'issueDate': data.get('invoiceDate', ''),
            'customerName': (
                customer_info.get('name', '') or
                data.get('buyerName', '') or
                data.get('customerName', '')
            ),
            'customerTaxCode': (
                customer_info.get('taxCode', '') or
                data.get('buyerTaxCode', '') or
                data.get('customerTaxCode', '')
            ),
            'customerAddress': (
                customer_info.get('address', '') or
                data.get('buyerAddress', '') or
                data.get('customerAddress', '')
            ),
            'totalBeforeVat': data.get('totalBeforeVat', 0),
            'vatRate': data.get('vatRate', 0),
            'vatAmount': data.get('vatAmount', 0),
            'totalAmount': data.get('totalAmount', 0),
            'source': source,
            'reconcileStatus': data.get('reconcileStatus', self.STATUS_PENDING)
        }

    # =========================================================================
    # GET CUSTOMERS
    # =========================================================================

    def get_customers(self) -> List[str]:
        """Get list of unique customer names for dropdown"""
        try:
            customers = set()

            # From tax invoices
            for doc in self.db.collection(self.COLLECTION_TAX_INVOICES).stream():
                data = doc.to_dict()
                customer_name = data.get('buyerName', '') or data.get('customerName', '')
                if customer_name:
                    customers.add(customer_name)

            # From local invoices
            for doc in self.db.collection(self.COLLECTION_LOCAL_INVOICES).stream():
                data = doc.to_dict()
                customer_name = data.get('customerName', '') or data.get('buyerName', '')
                if customer_name:
                    customers.add(customer_name)

            return sorted(list(customers))

        except Exception as e:
            logger.exception(f"Error getting customers: {e}")
            return []

    # =========================================================================
    # IMPORT METHODS
    # =========================================================================

    def batch_import_invoices(self, invoices: List[Dict], source: str) -> Dict:
        """
        Import nhiều hóa đơn (từ XML hoặc local)
        """
        try:
            collection = (
                self.COLLECTION_TAX_INVOICES
                if source == self.SOURCE_TAX_PORTAL_OUTPUT
                else self.COLLECTION_LOCAL_INVOICES
            )

            imported = 0
            duplicates = 0
            failed = 0

            batch = self.db.batch()
            batch_count = 0

            for inv in invoices:
                try:
                    # Create unique key
                    invoice_key = self._create_invoice_key(inv)
                    if not invoice_key:
                        failed += 1
                        continue

                    # Check for duplicate
                    existing = list(
                        self.db.collection(collection)
                        .where('invoiceKey', '==', invoice_key)
                        .limit(1)
                        .stream()
                    )

                    if existing:
                        duplicates += 1
                        continue

                    # Prepare invoice data
                    inv_data = {
                        **inv,
                        'invoiceKey': invoice_key,
                        'source': source,
                        'reconcileStatus': self.STATUS_PENDING,
                        'createdAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow()
                    }

                    doc_ref = self.db.collection(collection).document()
                    batch.set(doc_ref, inv_data)
                    batch_count += 1
                    imported += 1

                    # Commit batch every 500
                    if batch_count >= 500:
                        batch.commit()
                        batch = self.db.batch()
                        batch_count = 0

                except Exception as e:
                    logger.error(f"Error importing invoice: {e}")
                    failed += 1

            # Commit remaining
            if batch_count > 0:
                batch.commit()

            logger.info(f"Output invoice import: {imported} imported, {duplicates} duplicates, {failed} failed")

            return {
                'success': True,
                'imported': imported,
                'duplicates': duplicates,
                'failed': failed
            }

        except Exception as e:
            logger.exception(f"Error in batch import: {e}")
            return {
                'success': False,
                'imported': 0,
                'duplicates': 0,
                'failed': len(invoices),
                'error': str(e)
            }

    def _create_invoice_key(self, inv: Dict) -> str:
        """Create unique key for invoice"""
        invoice_no = inv.get('invoiceNo', '')
        customer_tax_code = inv.get('buyerTaxCode', '') or inv.get('customerTaxCode', '')

        if not invoice_no:
            return ''

        return f"{invoice_no}|{customer_tax_code}"

    # =========================================================================
    # SYNC LOCAL INVOICES
    # =========================================================================

    def sync_local_invoices(self) -> Dict:
        """
        Sync invoices from 'invoices' collection to output_local_invoices
        """
        try:
            synced = 0
            updated = 0
            skipped = 0

            batch = self.db.batch()
            batch_count = 0

            # Get all invoices from main collection
            for doc in self.db.collection(self.COLLECTION_INVOICES).stream():
                try:
                    data = doc.to_dict()

                    # Create invoice key
                    invoice_id = data.get('id', doc.id)

                    # Check if already exists
                    existing = list(
                        self.db.collection(self.COLLECTION_LOCAL_INVOICES)
                        .where('originalInvoiceId', '==', invoice_id)
                        .limit(1)
                        .stream()
                    )

                    # Prepare data
                    inv_data = {
                        'invoiceNo': str(invoice_id),
                        'invoiceDate': self._format_date(data.get('createdDate')),
                        'customerName': data.get('customer', 'Khách lẻ'),
                        'customerTaxCode': '',
                        'totalBeforeVat': self._calculate_before_vat(data.get('totalPrice', 0)),
                        'vatRate': 0,
                        'vatAmount': 0,
                        'totalAmount': data.get('totalPrice', 0),
                        'source': self.SOURCE_LOCAL,
                        'originalInvoiceId': invoice_id,
                        'reconcileStatus': self.STATUS_PENDING,
                        'updatedAt': datetime.utcnow()
                    }

                    if existing:
                        # Update
                        doc_ref = self.db.collection(self.COLLECTION_LOCAL_INVOICES).document(existing[0].id)
                        batch.update(doc_ref, inv_data)
                        updated += 1
                    else:
                        # Create new
                        inv_data['invoiceKey'] = f"{invoice_id}|"
                        inv_data['createdAt'] = datetime.utcnow()
                        doc_ref = self.db.collection(self.COLLECTION_LOCAL_INVOICES).document()
                        batch.set(doc_ref, inv_data)
                        synced += 1

                    batch_count += 1

                    if batch_count >= 500:
                        batch.commit()
                        batch = self.db.batch()
                        batch_count = 0

                except Exception as e:
                    logger.error(f"Error syncing invoice: {e}")
                    skipped += 1

            # Commit remaining
            if batch_count > 0:
                batch.commit()

            logger.info(f"Local sync: {synced} synced, {updated} updated, {skipped} skipped")

            return {
                'success': True,
                'synced': synced,
                'updated': updated,
                'skipped': skipped
            }

        except Exception as e:
            logger.exception(f"Error syncing local invoices: {e}")
            return {
                'success': False,
                'synced': 0,
                'updated': 0,
                'skipped': 0,
                'error': str(e)
            }

    def _format_date(self, date_value) -> str:
        """Format date to yyyy-mm-dd"""
        if not date_value:
            return ''

        if hasattr(date_value, 'strftime'):
            return date_value.strftime('%Y-%m-%d')

        if isinstance(date_value, str):
            # Try to parse dd/mm/yyyy
            if '/' in date_value:
                parts = date_value.split('/')
                if len(parts) == 3:
                    return f"{parts[2]}-{parts[1]}-{parts[0]}"
            return date_value

        return ''

    def _calculate_before_vat(self, total: float, vat_rate: float = 0) -> float:
        """Calculate amount before VAT"""
        if vat_rate > 0:
            return total / (1 + vat_rate / 100)
        return total

    # =========================================================================
    # RECONCILIATION
    # =========================================================================

    def get_reconciliation_summary(
        self,
        month_key: Optional[str] = None,
        year: Optional[int] = None
    ) -> Dict:
        """Get reconciliation summary"""
        try:
            # Count tax invoices
            tax_query = self.db.collection(self.COLLECTION_TAX_INVOICES)
            local_query = self.db.collection(self.COLLECTION_LOCAL_INVOICES)

            if month_key:
                parts = month_key.split('-')
                if len(parts) == 2:
                    y, m = int(parts[0]), int(parts[1])
                    start = f"{y}-{m:02d}-01"
                    end = f"{y}-{m+1:02d}-01" if m < 12 else f"{y+1}-01-01"
                    tax_query = tax_query.where('invoiceDate', '>=', start).where('invoiceDate', '<', end)
                    local_query = local_query.where('invoiceDate', '>=', start).where('invoiceDate', '<', end)
            elif year:
                start = f"{year}-01-01"
                end = f"{year+1}-01-01"
                tax_query = tax_query.where('invoiceDate', '>=', start).where('invoiceDate', '<', end)
                local_query = local_query.where('invoiceDate', '>=', start).where('invoiceDate', '<', end)

            tax_count = len(list(tax_query.stream()))
            local_count = len(list(local_query.stream()))

            # Count by status
            matched = 0
            unmatched = 0
            mismatch = 0

            for doc in self.db.collection(self.COLLECTION_RECONCILIATION).stream():
                status = doc.to_dict().get('status', '')
                if status == 'MATCH':
                    matched += 1
                elif status in ['MISSING_LOCAL', 'MISSING_TAX']:
                    unmatched += 1
                elif status == 'MISMATCH':
                    mismatch += 1

            return {
                'taxPortalCount': tax_count,
                'localCount': local_count,
                'matchedCount': matched,
                'unmatchedCount': unmatched,
                'mismatchCount': mismatch
            }

        except Exception as e:
            logger.exception(f"Error getting reconciliation summary: {e}")
            return {
                'taxPortalCount': 0,
                'localCount': 0,
                'matchedCount': 0,
                'unmatchedCount': 0,
                'mismatchCount': 0
            }

    def run_reconciliation(self, month_key: Optional[str] = None) -> Dict:
        """Run reconciliation between tax and local invoices"""
        try:
            # Load all tax invoices
            tax_query = self.db.collection(self.COLLECTION_TAX_INVOICES)
            local_query = self.db.collection(self.COLLECTION_LOCAL_INVOICES)

            if month_key:
                parts = month_key.split('-')
                if len(parts) == 2:
                    y, m = int(parts[0]), int(parts[1])
                    start = f"{y}-{m:02d}-01"
                    end = f"{y}-{m+1:02d}-01" if m < 12 else f"{y+1}-01-01"
                    tax_query = tax_query.where('invoiceDate', '>=', start).where('invoiceDate', '<', end)
                    local_query = local_query.where('invoiceDate', '>=', start).where('invoiceDate', '<', end)

            tax_invoices = {self._normalize_invoice_no(doc.to_dict().get('invoiceNo', '')): (doc.id, doc.to_dict()) for doc in tax_query.stream()}
            local_invoices = {self._normalize_invoice_no(doc.to_dict().get('invoiceNo', '')): (doc.id, doc.to_dict()) for doc in local_query.stream()}

            all_keys = set(tax_invoices.keys()) | set(local_invoices.keys())

            summary = {
                'matched': 0,
                'mismatch': 0,
                'missingLocal': 0,
                'missingTax': 0
            }

            reconciliations = []

            for key in all_keys:
                tax_data = tax_invoices.get(key)
                local_data = local_invoices.get(key)

                tax_id, tax_inv = tax_data if tax_data else (None, None)
                local_id, local_inv = local_data if local_data else (None, None)

                recon_record = {
                    'invoiceKey': key,
                    'taxInvoiceId': tax_id,
                    'localInvoiceId': local_id,
                    'checkedAt': datetime.utcnow(),
                    'monthKey': month_key
                }

                if tax_inv and local_inv:
                    # Compare
                    field_diffs = self._compare_invoice_fields(tax_inv, local_inv)

                    if not field_diffs:
                        recon_record['status'] = 'MATCH'
                        summary['matched'] += 1
                    else:
                        recon_record['status'] = 'MISMATCH'
                        recon_record['fieldDiffs'] = field_diffs
                        summary['mismatch'] += 1

                elif tax_inv and not local_inv:
                    recon_record['status'] = 'MISSING_LOCAL'
                    summary['missingLocal'] += 1

                elif not tax_inv and local_inv:
                    recon_record['status'] = 'MISSING_TAX'
                    summary['missingTax'] += 1

                # Add invoice data for UI
                if tax_inv:
                    recon_record['taxData'] = {
                        'invoiceNo': tax_inv.get('invoiceNo', ''),
                        'invoiceDate': tax_inv.get('invoiceDate', ''),
                        'customerName': tax_inv.get('buyerName', '') or tax_inv.get('customerName', ''),
                        'customerTaxCode': tax_inv.get('buyerTaxCode', '') or tax_inv.get('customerTaxCode', ''),
                        'totalBeforeVat': tax_inv.get('totalBeforeVat', 0),
                        'vatRate': tax_inv.get('vatRate', 0),
                        'vatAmount': tax_inv.get('vatAmount', 0),
                        'totalAmount': tax_inv.get('totalAmount', 0)
                    }

                if local_inv:
                    recon_record['localData'] = {
                        'invoiceNo': local_inv.get('invoiceNo', ''),
                        'invoiceDate': local_inv.get('invoiceDate', ''),
                        'customerName': local_inv.get('customerName', ''),
                        'customerTaxCode': local_inv.get('customerTaxCode', ''),
                        'totalBeforeVat': local_inv.get('totalBeforeVat', 0),
                        'vatRate': local_inv.get('vatRate', 0),
                        'vatAmount': local_inv.get('vatAmount', 0),
                        'totalAmount': local_inv.get('totalAmount', 0)
                    }

                reconciliations.append(recon_record)

            # Save results
            self._save_reconciliation_results(reconciliations, month_key)

            # Update invoice statuses
            self._update_invoice_reconcile_status(reconciliations)

            logger.info(f"Output reconciliation complete: {summary}")

            return {
                'success': True,
                'processed': len(all_keys),
                'matched': summary['matched'],
                'unmatched': summary['missingLocal'] + summary['missingTax'],
                'mismatch': summary['mismatch']
            }

        except Exception as e:
            logger.exception(f"Error running output reconciliation: {e}")
            return {
                'success': False,
                'processed': 0,
                'matched': 0,
                'unmatched': 0,
                'mismatch': 0,
                'error': str(e)
            }

    def _compare_invoice_fields(self, tax_inv: Dict, local_inv: Dict) -> List[Dict]:
        """Compare fields between tax and local invoices"""
        diffs = []

        field_mappings = [
            ('totalAmount', 'Tổng tiền', 'number'),
            ('totalBeforeVat', 'Tiền trước VAT', 'number'),
            ('vatAmount', 'Tiền thuế', 'number'),
            ('vatRate', 'Thuế suất', 'number'),
        ]

        for field, label, diff_type in field_mappings:
            tax_val = tax_inv.get(field, 0) or 0
            local_val = local_inv.get(field, 0) or 0

            if diff_type == 'number':
                tax_val = float(tax_val) if tax_val else 0
                local_val = float(local_val) if local_val else 0

                if abs(tax_val - local_val) > 0.01:
                    diffs.append({
                        'field': field,
                        'fieldLabel': label,
                        'taxValue': tax_val,
                        'localValue': local_val,
                        'diff': tax_val - local_val,
                        'diffType': diff_type
                    })

        return diffs

    def _save_reconciliation_results(self, reconciliations: List[Dict], month_key: Optional[str]):
        """Save reconciliation results to Firestore"""
        try:
            # Delete old results for this month
            if month_key:
                old_docs = list(
                    self.db.collection(self.COLLECTION_RECONCILIATION)
                    .where('monthKey', '==', month_key)
                    .stream()
                )
            else:
                old_docs = list(self.db.collection(self.COLLECTION_RECONCILIATION).stream())

            # Delete in batches
            batch = self.db.batch()
            for i, doc in enumerate(old_docs):
                batch.delete(doc.reference)
                if (i + 1) % 500 == 0:
                    batch.commit()
                    batch = self.db.batch()
            if old_docs:
                batch.commit()

            # Save new results
            batch = self.db.batch()
            batch_count = 0

            for recon in reconciliations:
                doc_ref = self.db.collection(self.COLLECTION_RECONCILIATION).document()
                batch.set(doc_ref, recon)
                batch_count += 1

                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0

            if batch_count > 0:
                batch.commit()

            logger.info(f"Saved {len(reconciliations)} output reconciliation records")

        except Exception as e:
            logger.error(f"Error saving output reconciliation results: {e}")

    def _update_invoice_reconcile_status(self, reconciliations: List[Dict]):
        """Update reconcileStatus in invoice documents"""
        try:
            status_map = {
                'MATCH': 'MATCHED',
                'MISMATCH': 'MISMATCH',
                'MISSING_LOCAL': 'UNMATCHED',
                'MISSING_TAX': 'UNMATCHED'
            }

            batch = self.db.batch()
            batch_count = 0

            for recon in reconciliations:
                status = recon.get('status')
                invoice_status = status_map.get(status, 'PENDING')

                if recon.get('taxInvoiceId'):
                    doc_ref = self.db.collection(self.COLLECTION_TAX_INVOICES).document(recon['taxInvoiceId'])
                    batch.update(doc_ref, {
                        'reconcileStatus': invoice_status,
                        'reconciledAt': datetime.utcnow()
                    })
                    batch_count += 1

                if recon.get('localInvoiceId'):
                    doc_ref = self.db.collection(self.COLLECTION_LOCAL_INVOICES).document(recon['localInvoiceId'])
                    batch.update(doc_ref, {
                        'reconcileStatus': invoice_status,
                        'reconciledAt': datetime.utcnow()
                    })
                    batch_count += 1

                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0

            if batch_count > 0:
                batch.commit()

            logger.info(f"Updated reconcileStatus for output invoices")

        except Exception as e:
            logger.error(f"Error updating output invoice reconcile status: {e}")

    def _normalize_invoice_no(self, invoice_no: str) -> str:
        """Normalize invoice number for comparison"""
        if not invoice_no:
            return ''
        return str(invoice_no).lstrip('0') or '0'

    # =========================================================================
    # DELETE METHODS
    # =========================================================================

    def clear_by_source(self, source: str) -> Dict:
        """Delete all invoices from a source"""
        try:
            collection = (
                self.COLLECTION_TAX_INVOICES
                if source == self.SOURCE_TAX_PORTAL_OUTPUT
                else self.COLLECTION_LOCAL_INVOICES
            )

            docs = list(self.db.collection(collection).stream())
            deleted = 0

            batch = self.db.batch()
            for i, doc in enumerate(docs):
                batch.delete(doc.reference)
                deleted += 1
                if (i + 1) % 500 == 0:
                    batch.commit()
                    batch = self.db.batch()

            if docs:
                batch.commit()

            logger.info(f"Deleted {deleted} output invoices from {source}")

            return {
                'success': True,
                'deleted': deleted
            }

        except Exception as e:
            logger.exception(f"Error clearing output by source: {e}")
            return {
                'success': False,
                'deleted': 0,
                'error': str(e)
            }

    def clear_all(self) -> Dict:
        """Delete all output invoices"""
        try:
            tax_result = self.clear_by_source(self.SOURCE_TAX_PORTAL_OUTPUT)
            local_result = self.clear_by_source(self.SOURCE_LOCAL)

            # Also clear reconciliation results
            recon_docs = list(self.db.collection(self.COLLECTION_RECONCILIATION).stream())
            batch = self.db.batch()
            for i, doc in enumerate(recon_docs):
                batch.delete(doc.reference)
                if (i + 1) % 500 == 0:
                    batch.commit()
                    batch = self.db.batch()
            if recon_docs:
                batch.commit()

            return {
                'success': True,
                'taxDeleted': tax_result.get('deleted', 0),
                'localDeleted': local_result.get('deleted', 0)
            }

        except Exception as e:
            logger.exception(f"Error clearing all output: {e}")
            return {
                'success': False,
                'taxDeleted': 0,
                'localDeleted': 0,
                'error': str(e)
            }


# Singleton instance
output_invoice_service_v2 = OutputInvoiceServiceV2()
