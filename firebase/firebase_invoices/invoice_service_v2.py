"""
INVOICE SERVICE V2 - SCALABLE VERSION
Thiết kế cho 100.000+ hóa đơn với pagination và optimized queries

Collections:
- tax_invoices: Hóa đơn từ trang thuế (hoadondientu.gdt.gov.vn)
- internal_invoices: Hóa đơn từ AI/PDF parsing
- invoice_reconciliation: Kết quả đối chiếu
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from google.cloud.firestore_v1.base_query import FieldFilter
from firebase_admin import firestore

from firebase.init_firebase import init_firestore

logger = logging.getLogger(__name__)


class InvoiceServiceV2:
    """
    Scalable Invoice Service với:
    - 2 collection riêng biệt: tax_invoices, internal_invoices
    - Pagination support
    - Optimized queries với composite indexes
    - Supplier caching
    """

    # Constants
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 100
    # Sử dụng các collection hiện có
    COLLECTION_TAX_INVOICES = 'tax_invoices'
    COLLECTION_INTERNAL_INVOICES = 'internal_invoices'
    COLLECTION_RECONCILIATION = 'invoice_reconciliation'
    COLLECTION_SUPPLIERS = 'suppliers'

    # Source types
    SOURCE_TAX_PORTAL = 'TAX_PORTAL'
    SOURCE_AI_PDF = 'AI_PDF'

    # Reconcile status
    STATUS_PENDING = 'PENDING'
    STATUS_MATCHED = 'MATCHED'
    STATUS_UNMATCHED = 'UNMATCHED'
    STATUS_MISMATCH = 'MISMATCH'

    def __init__(self):
        self._db = None
        logger.info("InvoiceServiceV2 initialized (lazy)")

    @property
    def db(self):
        """Lazy initialization của Firestore client - sử dụng named app"""
        if self._db is None:
            # Sử dụng FIREBASE_SERVICE_ACCOUNT_SUPPLIES_INVOICES (project: taphoa39-supplies-invoices)
            self._db = init_firestore("FIREBASE_SERVICE_ACCOUNT_SUPPLIES_INVOICES")
            logger.info("InvoiceServiceV2 Firestore client initialized")
        return self._db

    # =========================================================================
    # QUERY METHODS (với pagination)
    # =========================================================================

    def _get_collection_name(self, source: Optional[str]) -> str:
        """Lấy tên collection dựa trên source"""
        if source == self.SOURCE_TAX_PORTAL:
            return self.COLLECTION_TAX_INVOICES
        elif source == self.SOURCE_AI_PDF:
            return self.COLLECTION_INTERNAL_INVOICES
        else:
            # Default to tax_invoices nếu không chỉ định
            return self.COLLECTION_TAX_INVOICES

    def _normalize_invoice_data(self, data: Dict, source: str) -> Dict:
        """
        Chuẩn hóa data từ các collection khác nhau thành format thống nhất

        Cả 2 collection đều sử dụng supplier object: supplier.name, supplier.taxCode, supplier.address
        """
        normalized = {
            'invoiceNo': data.get('invoiceNo', ''),
            'totalAmount': float(data.get('totalAmount', 0)),
            'vatAmount': float(data.get('vatAmount', 0)),
            'source': source,
        }

        # Map invoiceDate -> issueDate (có thể là string hoặc Timestamp)
        invoice_date = data.get('invoiceDate', '')
        if invoice_date:
            if hasattr(invoice_date, 'isoformat'):
                # Đây là Timestamp/datetime
                normalized['issueDate'] = invoice_date.isoformat()
            else:
                # Đây là string
                normalized['issueDate'] = invoice_date
        else:
            normalized['issueDate'] = ''

        # Lấy supplier info từ nested object (chuẩn mới)
        # Fallback đến flat fields để backward compatible với data cũ
        supplier = data.get('supplier', {})
        normalized['supplierTaxCode'] = supplier.get('taxCode', '') or data.get('supplierTaxCode', '') or data.get('sellerTaxCode', '')
        normalized['supplierName'] = supplier.get('name', '') or data.get('supplierName', '') or data.get('sellerName', '')
        normalized['supplierAddress'] = supplier.get('address', '') or data.get('supplierAddress', '') or data.get('sellerAddress', '')

        # Thêm các field khác nếu có
        normalized['invoiceKey'] = data.get('invoiceKey', '')
        normalized['reconcileStatus'] = data.get('reconcileStatus', self.STATUS_PENDING)

        # Các field bổ sung
        normalized['confidence'] = data.get('confidence', data.get('ocrConfidence', 0))
        normalized['items'] = data.get('items', [])
        normalized['buyer'] = data.get('buyer', {})
        normalized['invoiceSymbol'] = data.get('invoiceSymbol', '')
        normalized['totalBeforeVat'] = float(data.get('totalBeforeVat', 0))
        normalized['vatRate'] = float(data.get('vatRate', 0))

        return normalized

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
            source: 'TAX_PORTAL' | 'AI_PDF' (REQUIRED - phải chỉ định source)
            year: Năm (e.g., 2024)
            month_key: Tháng (e.g., '2024-12')
            from_date: Từ ngày (YYYY-MM-DD hoặc dd/mm/yyyy)
            to_date: Đến ngày (YYYY-MM-DD hoặc dd/mm/yyyy)
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
                    'count': int
                }
            }
        """
        try:
            # Validate page_size
            page_size = min(page_size, self.MAX_PAGE_SIZE)

            # Xác định collection dựa trên source
            collection_name = self._get_collection_name(source)
            logger.info(f"Querying collection: {collection_name} with source: {source}")
            logger.info(f"Filters: year={year}, month_key={month_key}, from_date={from_date}, to_date={to_date}, supplier={supplier_tax_code}")

            # Convert year/month_key to from_date/to_date nếu chưa có
            if not from_date and not to_date:
                if month_key:
                    # month_key format: "2024-12"
                    try:
                        year_part, month_part = month_key.split('-')
                        year_int = int(year_part)
                        month_int = int(month_part)
                        # Ngày đầu tháng
                        from_date = f"{year_int}-{month_int:02d}-01"
                        # Ngày cuối tháng
                        if month_int == 12:
                            to_date = f"{year_int}-12-31"
                        else:
                            next_month = datetime(year_int, month_int + 1, 1)
                            last_day = next_month - timedelta(days=1)
                            to_date = last_day.strftime('%Y-%m-%d')
                        logger.info(f"Converted month_key={month_key} to from_date={from_date}, to_date={to_date}")
                    except Exception as e:
                        logger.error(f"Error parsing month_key: {e}")
                elif year:
                    # Filter theo năm
                    from_date = f"{year}-01-01"
                    to_date = f"{year}-12-31"
                    logger.info(f"Converted year={year} to from_date={from_date}, to_date={to_date}")

            # Build query - KHÔNG có filter trước, chỉ limit
            query = self.db.collection(collection_name)

            # Supplier filter - sẽ áp dụng client-side để backward compatible với data cũ
            # Vì data cũ có thể dùng flat fields (supplierTaxCode, sellerTaxCode)
            # và data mới dùng nested field (supplier.taxCode)
            use_client_side_supplier_filter = bool(supplier_tax_code)

            # Reconcile status filter - client-side vì field này có thể không tồn tại trong tất cả documents
            use_client_side_status_filter = bool(reconcile_status)

            # Date filters - QUAN TRỌNG: Cần detect format date trong Firestore
            # Firestore có thể lưu dạng: "2024-12-29", "29/12/2024", hoặc Timestamp
            # LƯU Ý: Nếu format là DD/MM/YYYY, string comparison KHÔNG CHÍNH XÁC
            # => Sử dụng client-side filtering cho format DD/MM/YYYY
            use_client_side_date_filter = False
            parsed_from_date = None
            parsed_to_date = None

            if from_date or to_date:
                # Detect format của invoiceDate trong collection
                date_format = self._detect_date_format_in_collection(collection_name)
                logger.info(f"Detected date format in {collection_name}: {date_format}")

                if date_format == 'TIMESTAMP':
                    # Query với Timestamp - convert string to datetime
                    if from_date:
                        parsed_from = self._parse_date(from_date)
                        if parsed_from:
                            query = query.where(filter=FieldFilter('invoiceDate', '>=', parsed_from))
                            logger.info(f"Applied from_date filter (Timestamp): invoiceDate >= {parsed_from}")
                    if to_date:
                        parsed_to = self._parse_date(to_date)
                        if parsed_to:
                            # Add 1 day để include cả ngày to_date
                            parsed_to = parsed_to.replace(hour=23, minute=59, second=59)
                            query = query.where(filter=FieldFilter('invoiceDate', '<=', parsed_to))
                            logger.info(f"Applied to_date filter (Timestamp): invoiceDate <= {parsed_to}")
                elif date_format == 'YYYY-MM-DD':
                    # Query với string YYYY-MM-DD - string comparison works correctly
                    if from_date:
                        normalized_from = self._normalize_date_for_query(from_date, 'YYYY-MM-DD')
                        if normalized_from:
                            query = query.where(filter=FieldFilter('invoiceDate', '>=', normalized_from))
                            logger.info(f"Applied from_date filter (YYYY-MM-DD): invoiceDate >= {normalized_from}")
                    if to_date:
                        normalized_to = self._normalize_date_for_query(to_date, 'YYYY-MM-DD')
                        if normalized_to:
                            query = query.where(filter=FieldFilter('invoiceDate', '<=', normalized_to))
                            logger.info(f"Applied to_date filter (YYYY-MM-DD): invoiceDate <= {normalized_to}")
                else:
                    # Format DD/MM/YYYY - string comparison KHÔNG CHÍNH XÁC
                    # => Không apply filter ở Firestore, sẽ filter ở client-side
                    logger.warning(f"Date format DD/MM/YYYY detected - using client-side filtering")
                    use_client_side_date_filter = True
                    parsed_from_date = self._parse_date(from_date) if from_date else None
                    parsed_to_date = self._parse_date(to_date) if to_date else None
                    if parsed_to_date:
                        parsed_to_date = parsed_to_date.replace(hour=23, minute=59, second=59)

            # Order by invoiceDate descending
            query = query.order_by('invoiceDate', direction=firestore.Query.DESCENDING)

            # Apply cursor for pagination
            if cursor_doc_id:
                cursor_doc = self.db.collection(collection_name).document(cursor_doc_id).get()
                if cursor_doc.exists:
                    if direction == 'next':
                        query = query.start_after(cursor_doc)
                    else:
                        query = query.end_before(cursor_doc)

            # Fetch one extra to check hasNext
            query = query.limit(page_size + 1)

            # Execute query
            docs = list(query.stream())
            logger.info(f"Found {len(docs)} documents in {collection_name}")

            # Check pagination
            has_next = len(docs) > page_size
            if has_next:
                docs = docs[:page_size]

            # Convert to dict với normalized format
            invoices = []
            first_doc_id = None
            last_doc_id = None

            for i, doc in enumerate(docs):
                data = doc.to_dict()

                # Client-side date filtering (cho DD/MM/YYYY format)
                if use_client_side_date_filter:
                    invoice_date_str = data.get('invoiceDate', '')
                    invoice_date = self._parse_date(invoice_date_str) if invoice_date_str else None
                    if invoice_date:
                        if parsed_from_date and invoice_date < parsed_from_date:
                            continue
                        if parsed_to_date and invoice_date > parsed_to_date:
                            continue

                # Client-side supplier filtering (backward compatible với cả data cũ và mới)
                if use_client_side_supplier_filter:
                    # Lấy taxCode từ nested object hoặc flat fields
                    supplier_obj = data.get('supplier', {})
                    doc_tax_code = (
                        supplier_obj.get('taxCode', '') or
                        data.get('supplierTaxCode', '') or
                        data.get('sellerTaxCode', '')
                    )
                    if doc_tax_code != supplier_tax_code:
                        continue

                # Client-side reconcileStatus filtering
                if use_client_side_status_filter:
                    doc_status = data.get('reconcileStatus', self.STATUS_PENDING)
                    if doc_status != reconcile_status:
                        continue

                # Normalize data to unified format
                normalized = self._normalize_invoice_data(data, source or self.SOURCE_TAX_PORTAL)
                normalized['id'] = doc.id

                invoices.append(normalized)

                if first_doc_id is None:
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
            import traceback
            logger.error(traceback.format_exc())
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

    def _detect_date_format_in_collection(self, collection_name: str) -> str:
        """
        Detect format của invoiceDate trong collection
        Returns: 'YYYY-MM-DD', 'DD/MM/YYYY', hoặc 'TIMESTAMP'
        """
        try:
            # Lấy 1 document mẫu
            docs = list(self.db.collection(collection_name).limit(1).stream())
            if not docs:
                return 'YYYY-MM-DD'  # Default

            data = docs[0].to_dict()
            invoice_date = data.get('invoiceDate')

            if invoice_date is None:
                return 'YYYY-MM-DD'

            # Check if Timestamp
            if hasattr(invoice_date, 'isoformat'):
                return 'TIMESTAMP'

            # Check string format
            if isinstance(invoice_date, str):
                if '/' in invoice_date:
                    return 'DD/MM/YYYY'
                elif '-' in invoice_date and len(invoice_date) == 10:
                    return 'YYYY-MM-DD'

            return 'YYYY-MM-DD'

        except Exception as e:
            logger.error(f"Error detecting date format: {e}")
            return 'YYYY-MM-DD'

    def _normalize_date_for_query(self, date_str: str, target_format: str = 'YYYY-MM-DD') -> Optional[str]:
        """
        Normalize date string to format used in Firestore
        Input có thể là: YYYY-MM-DD hoặc dd/mm/yyyy
        Output: format phù hợp với Firestore data

        Args:
            date_str: Input date string
            target_format: 'YYYY-MM-DD' hoặc 'DD/MM/YYYY'
        """
        if not date_str:
            return None

        # Parse input date
        parsed_date = None

        # Try YYYY-MM-DD format
        if len(date_str) == 10 and date_str[4] == '-':
            try:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
            except:
                pass

        # Try dd/mm/yyyy format
        if not parsed_date and '/' in date_str:
            parts = date_str.split('/')
            if len(parts) == 3:
                try:
                    parsed_date = datetime.strptime(date_str, '%d/%m/%Y')
                except:
                    pass

        if not parsed_date:
            return date_str

        # Output to target format
        if target_format == 'DD/MM/YYYY':
            return parsed_date.strftime('%d/%m/%Y')
        else:
            return parsed_date.strftime('%Y-%m-%d')

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
            # Xác định collection dựa trên source
            collection_name = self._get_collection_name(source)

            # Đảm bảo invoiceNo luôn là string
            invoice_no = str(invoice_data.get('invoiceNo', '')).strip()

            # Lấy supplier tax code - khác nhau giữa 2 loại
            if source == self.SOURCE_TAX_PORTAL:
                supplier_tax_code = str(invoice_data.get('sellerTaxCode', '') or
                                       invoice_data.get('supplierTaxCode', '')).strip()
            else:
                supplier_tax_code = str(invoice_data.get('supplierTaxCode', '') or
                                       invoice_data.get('supplier', {}).get('taxCode', '')).strip()

            if not invoice_no or not supplier_tax_code:
                return False, "Thiếu số hóa đơn hoặc MST nhà cung cấp", None

            # Create invoice key for duplicate check
            invoice_key = f"{invoice_no}|{supplier_tax_code}"

            # Check duplicate trong collection tương ứng
            existing = self.db.collection(collection_name).where(
                filter=FieldFilter('invoiceKey', '==', invoice_key)
            ).limit(1).get()

            if len(list(existing)) > 0:
                return False, f"Hóa đơn {invoice_no} từ nguồn {source} đã tồn tại", None

            # Parse date
            issue_date_str = invoice_data.get('invoiceDate', '') or invoice_data.get('issueDate', '')

            # Build document data dựa trên collection
            if source == self.SOURCE_TAX_PORTAL:
                # Schema for tax_invoices, aligned with internal_invoices as per user request
                supplier_name = invoice_data.get('sellerName', '') or invoice_data.get('supplierName', '')
                supplier_address = invoice_data.get('sellerAddress', '') or invoice_data.get('supplierAddress', '')

                buyer_data = {
                    'name': invoice_data.get('buyerName', ''),
                    'taxCode': invoice_data.get('buyerTaxCode', ''),
                }

                items = []
                vat_rates_in_items = []
                for item_data in invoice_data.get('items', []):
                    items.append({
                        'name': item_data.get('itemName', ''),
                        'unit': item_data.get('unitName', ''),
                        'quantity': float(item_data.get('quantity', 0)),
                        'unitPrice': float(item_data.get('unitPrice', 0)),
                        'amount': float(item_data.get('totalAmount', 0)),
                    })
                    if item_data.get('vatRate'):
                        vat_rates_in_items.append(item_data.get('vatRate'))
                
                # Ưu tiên vatRate từ invoice_data (parsed từ LTSuat), fallback về items
                root_vat_rate = float(invoice_data.get('vatRate', 0))
                if root_vat_rate == 0 and vat_rates_in_items:
                    try:
                        vat_rate_str = str(vat_rates_in_items[0]).replace('%', '').strip()
                        if vat_rate_str:
                            root_vat_rate = float(vat_rate_str)
                    except (ValueError, TypeError):
                        pass

                doc_data = {
                    'invoiceNo': invoice_no,
                    'invoiceSymbol': invoice_data.get('invoiceSymbol', ''),
                    'invoiceDate': issue_date_str,
                    'invoiceKey': invoice_key,
                    'supplier': {
                        'name': supplier_name,
                        'taxCode': supplier_tax_code,
                        'address': supplier_address
                    },
                    'buyer': buyer_data,
                    'items': items,
                    'totalBeforeVat': float(invoice_data.get('totalBeforeVat', 0)),
                    'vatRate': root_vat_rate,
                    'vatAmount': float(invoice_data.get('vatAmount', 0)),
                    'totalAmount': float(invoice_data.get('totalAmount', 0)),
                    'source': 'gdt',
                    'createdAt': datetime.utcnow()
                }
            else:
                # Schema for internal_invoices (AI/PDF)
                supplier = invoice_data.get('supplier', {})
                supplier_name = supplier.get('name', '') or invoice_data.get('supplierName', '')
                supplier_address = supplier.get('address', '') or invoice_data.get('supplierAddress', '')

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

                doc_data = {
                    'invoiceNo': invoice_no,
                    'invoiceSymbol': invoice_data.get('invoiceSymbol', ''),
                    'invoiceDate': issue_date_str,
                    'invoiceKey': invoice_key,
                    'supplier': {
                        'name': supplier_name,
                        'taxCode': supplier_tax_code,
                        'address': supplier_address
                    },
                    'buyer': invoice_data.get('buyer', {}),
                    'items': items,
                    'totalBeforeVat': float(invoice_data.get('totalBeforeVat', 0)),
                    'vatRate': float(invoice_data.get('vatRate', 0)),
                    'vatAmount': float(invoice_data.get('vatAmount', 0)),
                    'totalAmount': float(invoice_data.get('totalAmount', 0)),
                    'source': 'ai_pdf',
                    'aiModel': 'gemini-3-flash',
                    'confidence': float(invoice_data.get('confidence', 0)),
                    'createdAt': datetime.utcnow()
                }

            # Save to Firestore
            doc_ref = self.db.collection(collection_name).add(doc_data)
            doc_id = doc_ref[1].id

            logger.info(f"Created invoice: {invoice_no} | source={source} | collection={collection_name}")
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
        Lấy danh sách nhà cung cấp unique từ cả 2 collection invoices
        (Không dùng collection suppliers riêng nữa, lấy trực tiếp từ invoices)

        Args:
            search: Tìm theo tên hoặc MST
            limit: Số lượng tối đa

        Returns:
            List of suppliers
        """
        try:
            suppliers_map = {}  # taxCode -> {name, taxCode, address, invoiceCount}

            # Lấy từ tax_invoices
            tax_docs = self.db.collection(self.COLLECTION_TAX_INVOICES).stream()
            for doc in tax_docs:
                data = doc.to_dict()
                supplier_obj = data.get('supplier', {})
                tax_code = (
                    supplier_obj.get('taxCode', '') or
                    data.get('supplierTaxCode', '') or
                    data.get('sellerTaxCode', '')
                )
                name = (
                    supplier_obj.get('name', '') or
                    data.get('supplierName', '') or
                    data.get('sellerName', '')
                )
                address = (
                    supplier_obj.get('address', '') or
                    data.get('supplierAddress', '') or
                    data.get('sellerAddress', '')
                )

                if tax_code:
                    if tax_code in suppliers_map:
                        suppliers_map[tax_code]['invoiceCount'] += 1
                    else:
                        suppliers_map[tax_code] = {
                            'taxCode': tax_code,
                            'name': name,
                            'address': address,
                            'invoiceCount': 1
                        }

            # Lấy từ internal_invoices
            internal_docs = self.db.collection(self.COLLECTION_INTERNAL_INVOICES).stream()
            for doc in internal_docs:
                data = doc.to_dict()
                supplier_obj = data.get('supplier', {})
                tax_code = (
                    supplier_obj.get('taxCode', '') or
                    data.get('supplierTaxCode', '')
                )
                name = (
                    supplier_obj.get('name', '') or
                    data.get('supplierName', '')
                )
                address = (
                    supplier_obj.get('address', '') or
                    data.get('supplierAddress', '')
                )

                if tax_code:
                    if tax_code in suppliers_map:
                        suppliers_map[tax_code]['invoiceCount'] += 1
                    else:
                        suppliers_map[tax_code] = {
                            'taxCode': tax_code,
                            'name': name,
                            'address': address,
                            'invoiceCount': 1
                        }

            # Convert to list và sort theo invoiceCount
            suppliers = list(suppliers_map.values())
            suppliers.sort(key=lambda x: x['invoiceCount'], reverse=True)

            # Client-side filter
            if search:
                search_lower = search.lower()
                suppliers = [
                    s for s in suppliers
                    if search_lower in s.get('name', '').lower() or
                       search_lower in s.get('taxCode', '').lower()
                ]

            # Limit
            suppliers = suppliers[:limit]

            logger.info(f"Found {len(suppliers)} unique suppliers from invoices")
            return suppliers

        except Exception as e:
            logger.error(f"Error getting suppliers: {e}")
            import traceback
            logger.error(traceback.format_exc())
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

    def delete_invoice(self, doc_id: str, source: str) -> bool:
        """Xóa 1 hóa đơn"""
        try:
            collection_name = self._get_collection_name(source)
            self.db.collection(collection_name).document(doc_id).delete()
            logger.info(f"Deleted invoice: {doc_id} from {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Error deleting invoice: {e}")
            return False

    def clear_invoices_by_source(self, source: str) -> Dict:
        """Xóa tất cả hóa đơn theo nguồn (xóa toàn bộ collection tương ứng)"""
        try:
            collection_name = self._get_collection_name(source)
            logger.info(f"Clearing all documents in collection: {collection_name}")

            # Lấy tất cả documents trong collection
            docs = self.db.collection(collection_name).stream()
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

            logger.info(f"Deleted {deleted_count} documents from {collection_name}")

            return {'success': True, 'deleted': deleted_count}

        except Exception as e:
            logger.error(f"Error clearing invoices by source: {e}")
            return {'success': False, 'deleted': 0, 'error': str(e)}

    def clear_all_invoices(self) -> Dict:
        """Xóa tất cả hóa đơn từ cả 2 collection"""
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
            # Đếm số lượng trong từng collection
            tax_query = self.db.collection(self.COLLECTION_TAX_INVOICES)
            ai_query = self.db.collection(self.COLLECTION_INTERNAL_INVOICES)

            # Note: Firestore count() aggregation không hỗ trợ filter phức tạp
            # Nên đếm bằng cách stream documents
            tax_docs = list(tax_query.stream())
            ai_docs = list(ai_query.stream())

            # Lấy kết quả đối chiếu từ invoice_reconciliation
            recon_query = self.db.collection(self.COLLECTION_RECONCILIATION)
            recon_docs = list(recon_query.stream())

            matched_count = 0
            unmatched_count = 0
            mismatch_count = 0

            for doc in recon_docs:
                data = doc.to_dict()
                status = data.get('status', '')
                if status == 'MATCH':
                    matched_count += 1
                elif status == 'MISSING_INTERNAL' or status == 'MISSING_TAX':
                    unmatched_count += 1
                elif status == 'MISMATCH':
                    mismatch_count += 1

            return {
                'taxPortalCount': len(tax_docs),
                'aiPdfCount': len(ai_docs),
                'matchedCount': matched_count,
                'unmatchedCount': unmatched_count,
                'mismatchCount': mismatch_count
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
        Chạy đối chiếu tự động - sử dụng logic từ supplies_invoice_service

        Algorithm:
        1. Lấy tất cả hóa đơn từ tax_invoices
        2. Lấy tất cả hóa đơn từ internal_invoices
        3. So khớp theo invoiceKey (invoiceNo|taxCode)
        4. Lưu kết quả vào invoice_reconciliation
        """
        try:
            # Get TAX invoices
            tax_docs = list(self.db.collection(self.COLLECTION_TAX_INVOICES).stream())
            logger.info(f"Found {len(tax_docs)} tax_invoices for reconciliation")

            # Get AI/Internal invoices
            internal_docs = list(self.db.collection(self.COLLECTION_INTERNAL_INVOICES).stream())
            logger.info(f"Found {len(internal_docs)} internal_invoices for reconciliation")

            # Build maps for quick lookup
            # Key: invoiceNo|taxCode
            tax_map = {}
            for doc in tax_docs:
                data = doc.to_dict()
                data['id'] = doc.id
                key = data.get('invoiceKey', f"{data.get('invoiceNo', '')}|{data.get('sellerTaxCode', '')}")
                tax_map[key] = data

            internal_map = {}
            for doc in internal_docs:
                data = doc.to_dict()
                data['id'] = doc.id
                key = data.get('invoiceKey', f"{data.get('invoiceNo', '')}|{data.get('supplierTaxCode', '')}")
                internal_map[key] = data

            # Get all unique keys
            all_keys = set(tax_map.keys()) | set(internal_map.keys())

            # Reconcile each invoice
            reconciliations = []
            summary = {
                'totalTax': len(tax_docs),
                'totalInternal': len(internal_docs),
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
                    'fieldDiffs': [],  # Chi tiết sai lệch từng field
                    'checkedAt': datetime.utcnow()
                }

                if tax_inv and internal_inv:
                    # So sánh TẤT CẢ fields quan trọng
                    field_diffs = self._compare_invoice_fields(tax_inv, internal_inv)

                    if not field_diffs:
                        recon_record['status'] = 'MATCH'
                        summary['matched'] += 1
                    else:
                        recon_record['status'] = 'MISMATCH'
                        recon_record['fieldDiffs'] = field_diffs
                        summary['mismatch'] += 1

                elif tax_inv and not internal_inv:
                    recon_record['status'] = 'MISSING_INTERNAL'
                    summary['missingInternal'] += 1

                elif not tax_inv and internal_inv:
                    recon_record['status'] = 'MISSING_TAX'
                    summary['missingTax'] += 1

                # Add invoice data for UI display
                if tax_inv:
                    # Lấy supplier info từ nhiều nguồn có thể: sellerName, supplierName, hoặc nested supplier
                    tax_supplier = tax_inv.get('supplier', {})
                    recon_record['taxData'] = {
                        'invoiceNo': tax_inv.get('invoiceNo', ''),
                        'invoiceSymbol': tax_inv.get('invoiceSymbol', ''),
                        'invoiceDate': tax_inv.get('invoiceDate', ''),
                        'supplierName': (
                            tax_supplier.get('name', '') or
                            tax_inv.get('sellerName', '') or
                            tax_inv.get('supplierName', '')
                        ),
                        'supplierTaxCode': (
                            tax_supplier.get('taxCode', '') or
                            tax_inv.get('sellerTaxCode', '') or
                            tax_inv.get('supplierTaxCode', '')
                        ),
                        'totalBeforeVat': tax_inv.get('totalBeforeVat', 0),
                        'vatRate': tax_inv.get('vatRate', 0),
                        'vatAmount': tax_inv.get('vatAmount', 0),
                        'totalAmount': tax_inv.get('totalAmount', 0)
                    }

                if internal_inv:
                    # Lấy supplier info từ nested object hoặc flat fields
                    supplier = internal_inv.get('supplier', {})
                    recon_record['internalData'] = {
                        'invoiceNo': internal_inv.get('invoiceNo', ''),
                        'invoiceSymbol': internal_inv.get('invoiceSymbol', ''),
                        'invoiceDate': internal_inv.get('invoiceDate', ''),
                        'supplierName': supplier.get('name', '') or internal_inv.get('supplierName', ''),
                        'supplierTaxCode': supplier.get('taxCode', '') or internal_inv.get('supplierTaxCode', ''),
                        'supplierAddress': supplier.get('address', '') or internal_inv.get('supplierAddress', ''),
                        'totalBeforeVat': internal_inv.get('totalBeforeVat', 0),
                        'vatRate': internal_inv.get('vatRate', 0),
                        'vatAmount': internal_inv.get('vatAmount', 0),
                        'totalAmount': internal_inv.get('totalAmount', 0)
                    }

                reconciliations.append(recon_record)

            # Save reconciliation results to Firestore
            self._save_reconciliation_results(reconciliations, month_key)

            # CẬP NHẬT reconcileStatus trong invoice documents
            self._update_invoice_reconcile_status(reconciliations)

            logger.info(f"Reconciliation complete: {summary}")

            return {
                'success': True,
                'processed': len(all_keys),
                'matched': summary['matched'],
                'unmatched': summary['missingInternal'] + summary['missingTax'],
                'mismatch': summary['mismatch'],
                'summary': summary
            }

        except Exception as e:
            logger.error(f"Error running reconciliation: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e)
            }

    def _save_reconciliation_results(self, reconciliations: List[Dict], month_key: Optional[str] = None):
        """Lưu kết quả đối chiếu vào Firestore"""
        try:
            # Xóa kết quả cũ
            period_key = month_key or 'all'

            old_docs = self.db.collection(self.COLLECTION_RECONCILIATION).where(
                filter=FieldFilter('periodKey', '==', period_key)
            ).stream()

            for doc in old_docs:
                doc.reference.delete()

            # Lưu kết quả mới
            batch = self.db.batch()
            batch_count = 0

            for recon in reconciliations:
                recon['periodKey'] = period_key
                doc_ref = self.db.collection(self.COLLECTION_RECONCILIATION).document()
                batch.set(doc_ref, recon)
                batch_count += 1

                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0

            if batch_count > 0:
                batch.commit()

            logger.info(f"Saved {len(reconciliations)} reconciliation records")

        except Exception as e:
            logger.error(f"Error saving reconciliation results: {e}")

    def _update_invoice_reconcile_status(self, reconciliations: List[Dict]):
        """
        Cập nhật reconcileStatus trong invoice documents sau khi đối chiếu
        Để filter theo trạng thái hoạt động và cột TT hiển thị đúng màu
        """
        try:
            # Map status từ reconciliation sang invoice
            # MATCH, MISMATCH -> giữ nguyên
            # MISSING_INTERNAL -> chỉ có tax invoice, status = UNMATCHED
            # MISSING_TAX -> chỉ có internal invoice, status = UNMATCHED
            status_map = {
                'MATCH': 'MATCHED',
                'MISMATCH': 'MISMATCH',
                'MISSING_INTERNAL': 'UNMATCHED',
                'MISSING_TAX': 'UNMATCHED'
            }

            batch = self.db.batch()
            batch_count = 0
            updated_count = 0

            for recon in reconciliations:
                status = recon.get('status')
                invoice_status = status_map.get(status, 'PENDING')

                # Cập nhật tax_invoices
                if recon.get('taxInvoiceId'):
                    doc_ref = self.db.collection(self.COLLECTION_TAX_INVOICES).document(recon['taxInvoiceId'])
                    batch.update(doc_ref, {
                        'reconcileStatus': invoice_status,
                        'matchedInvoiceId': recon.get('internalInvoiceId'),
                        'reconciledAt': datetime.utcnow()
                    })
                    batch_count += 1
                    updated_count += 1

                # Cập nhật internal_invoices
                if recon.get('internalInvoiceId'):
                    doc_ref = self.db.collection(self.COLLECTION_INTERNAL_INVOICES).document(recon['internalInvoiceId'])
                    batch.update(doc_ref, {
                        'reconcileStatus': invoice_status,
                        'matchedInvoiceId': recon.get('taxInvoiceId'),
                        'reconciledAt': datetime.utcnow()
                    })
                    batch_count += 1
                    updated_count += 1

                # Commit batch every 500 operations
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0

            # Commit remaining
            if batch_count > 0:
                batch.commit()

            logger.info(f"Updated reconcileStatus for {updated_count} invoice documents")

        except Exception as e:
            logger.error(f"Error updating invoice reconcile status: {e}")
            import traceback
            logger.error(traceback.format_exc())

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def _compare_invoice_fields(self, tax_inv: Dict, internal_inv: Dict) -> List[Dict]:
        """
        So sánh chi tiết TẤT CẢ fields giữa hóa đơn từ trang thuế và hóa đơn từ AI

        Returns:
            List of diffs: [
                {
                    'field': 'totalAmount',
                    'fieldLabel': 'Tổng tiền',
                    'taxValue': 22000000,
                    'internalValue': 11000000,
                    'diff': 11000000,
                    'diffType': 'number'  # 'number', 'string', 'date'
                },
                ...
            ]
        """
        diffs = []

        # Helper to get supplier info from a unified invoice object
        def get_supplier_info(inv: Dict) -> Tuple[str, str]:
            supplier_obj = inv.get('supplier', {})
            name = supplier_obj.get('name', '') or inv.get('supplierName', '')
            tax_code = supplier_obj.get('taxCode', '') or inv.get('supplierTaxCode', '')
            return name, tax_code

        tax_supplier_name, tax_supplier_tax_code = get_supplier_info(tax_inv)
        internal_supplier_name, internal_supplier_tax_code = get_supplier_info(internal_inv)
        
        # Định nghĩa các fields cần so sánh
        # Format: (tax_field, internal_field, label, diff_type, tolerance)
        fields_to_compare = [
            # Số tiền - cho phép sai số 1đ
            ('totalAmount', 'totalAmount', 'Tổng tiền thanh toán', 'number', 1),
            ('vatAmount', 'vatAmount', 'Tiền thuế GTGT', 'number', 1),
            ('totalBeforeVat', 'totalBeforeVat', 'Tổng tiền trước thuế', 'number', 1),

            # Thông tin hóa đơn - so sánh chính xác
            ('invoiceNo', 'invoiceNo', 'Số hóa đơn', 'string', 0),
            ('invoiceSymbol', 'invoiceSymbol', 'Ký hiệu hóa đơn', 'string', 0),
            ('invoiceDate', 'invoiceDate', 'Ngày hóa đơn', 'date', 0),

            # VAT rate
            ('vatRate', 'vatRate', 'Thuế suất (%)', 'number', 0),
        ]

        for tax_field, internal_field, label, diff_type, tolerance in fields_to_compare:
            tax_value = tax_inv.get(tax_field)
            internal_value = internal_inv.get(internal_field)

            # Xử lý None values
            if tax_value is None:
                tax_value = 0 if diff_type == 'number' else ''
            if internal_value is None:
                internal_value = 0 if diff_type == 'number' else ''

            # So sánh dựa trên loại
            has_diff = False
            diff_value = None

            if diff_type == 'number':
                tax_num = float(tax_value) if tax_value else 0
                internal_num = float(internal_value) if internal_value else 0
                diff_value = tax_num - internal_num
                has_diff = abs(diff_value) > tolerance
            elif diff_type == 'string':
                tax_str = str(tax_value).strip().lower()
                internal_str = str(internal_value).strip().lower()
                # Normalize số hóa đơn (bỏ số 0 đầu)
                if tax_field == 'invoiceNo':
                    tax_str = tax_str.lstrip('0') or '0'
                    internal_str = internal_str.lstrip('0') or '0'
                has_diff = tax_str != internal_str
                diff_value = f"'{tax_value}' vs '{internal_value}'"
            elif diff_type == 'date':
                # Normalize dates trước khi so sánh
                tax_date = self._normalize_date_string(str(tax_value))
                internal_date = self._normalize_date_string(str(internal_value))
                has_diff = tax_date != internal_date
                diff_value = f"'{tax_value}' vs '{internal_value}'"

            if has_diff:
                diffs.append({
                    'field': tax_field,
                    'fieldLabel': label,
                    'taxValue': tax_value,
                    'internalValue': internal_value,
                    'diff': diff_value,
                    'diffType': diff_type
                })

        # So sánh supplier name (field names khác nhau giữa 2 nguồn)
        if tax_supplier_name.lower() != internal_supplier_name.lower():
            diffs.append({
                'field': 'supplierName',
                'fieldLabel': 'Tên nhà cung cấp',
                'taxValue': tax_supplier_name,
                'internalValue': internal_supplier_name,
                'diff': f"'{tax_supplier_name}' vs '{internal_supplier_name}'",
                'diffType': 'string'
            })

        # So sánh supplier tax code
        if tax_supplier_tax_code != internal_supplier_tax_code:
            diffs.append({
                'field': 'supplierTaxCode',
                'fieldLabel': 'MST nhà cung cấp',
                'taxValue': tax_supplier_tax_code,
                'internalValue': internal_supplier_tax_code,
                'diff': f"'{tax_supplier_tax_code}' vs '{internal_supplier_tax_code}'",
                'diffType': 'string'
            })

        return diffs

    def _normalize_date_string(self, date_str: str) -> str:
        """Normalize date string to YYYY-MM-DD for comparison"""
        if not date_str:
            return ''

        parsed = self._parse_date(date_str)
        if parsed:
            return parsed.strftime('%Y-%m-%d')
        return date_str

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



# Singleton instance
invoice_service_v2 = InvoiceServiceV2()
