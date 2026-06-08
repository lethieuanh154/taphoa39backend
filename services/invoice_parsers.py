"""
Invoice Parsers
Xử lý các định dạng file hóa đơn từ cơ quan thuế và folder local

Supported formats:
- XML từ trang thuế (hoadondientu.gdt.gov.vn)
- Excel xuất từ trang thuế
- JSON từ OCR (Gemini Flash)
"""

import logging
import json
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


class TaxInvoiceXMLParser:
    """
    Parser cho file XML từ trang thuế hoadondientu.gdt.gov.vn

    Cấu trúc XML điển hình từ trang thuế:
    <HDon>
        <TTChung>
            <SHDon>0001234</SHDon>
            <NLap>2024-01-15</NLap>
            ...
        </TTChung>
        <NBan>
            <MST>0301234567</MST>
            <Ten>Công ty ABC</Ten>
            ...
        </NBan>
        <TToan>
            <TgTTTBSo>7830000</TgTTTBSo>
            <TgThue>711818</TgThue>
            ...
        </TToan>
    </HDon>
    """

    # Common XML namespaces used by GDT
    NAMESPACES = {
        'inv': 'http://laphoadon.gdt.gov.vn/2014/09/invoicexml/v1',
        'ds': 'http://www.w3.org/2000/09/xmldsig#'
    }

    @staticmethod
    def parse(xml_content: bytes) -> Tuple[List[Dict], List[str]]:
        """
        Parse XML file từ trang thuế

        Args:
            xml_content: Nội dung file XML dạng bytes

        Returns:
            (list_invoices, list_errors)
        """
        invoices = []
        errors = []

        try:
            # Parse XML
            root = ET.fromstring(xml_content)
            root_tag = root.tag.split('}')[-1] if '}' in root.tag else root.tag

            logger.info(f"XML root tag: {root_tag}")
            print(f"[PARSER DEBUG] XML root tag: {root_tag}")

            # Try multiple possible structures
            # Structure 1: HDon với DLHDon bên trong (format mới từ GDT)
            # <HDon><DLHDon><TTChung>...</TTChung><NDHDon>...</NDHDon></DLHDon></HDon>
            if root_tag == 'HDon':
                # Tìm DLHDon hoặc parse trực tiếp
                dlhdon = None
                for elem in root:
                    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                    if tag == 'DLHDon':
                        dlhdon = elem
                        break

                if dlhdon is not None:
                    # Parse từ DLHDon (chứa TTChung và NDHDon)
                    invoice = TaxInvoiceXMLParser._parse_single_invoice(dlhdon)
                    if invoice:
                        invoices.append(invoice)
                else:
                    # Không có DLHDon, parse trực tiếp từ HDon
                    invoice = TaxInvoiceXMLParser._parse_single_invoice(root)
                    if invoice:
                        invoices.append(invoice)

            # Structure 2: HoaDonDienTu hoặc Invoice as root
            elif root_tag in ('HoaDonDienTu', 'Invoice'):
                invoice = TaxInvoiceXMLParser._parse_single_invoice(root)
                if invoice:
                    invoices.append(invoice)

            # Structure 3: Container with multiple invoices (DLHDon as root, or list)
            else:
                # Find all invoice elements
                found_any = False

                # Tìm các HDon hoặc DLHDon elements
                for elem in root.iter():
                    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

                    # Nếu tìm thấy HDon, check xem có DLHDon bên trong không
                    if tag == 'HDon':
                        found_any = True
                        dlhdon = None
                        for child in elem:
                            child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                            if child_tag == 'DLHDon':
                                dlhdon = child
                                break

                        target = dlhdon if dlhdon is not None else elem
                        invoice = TaxInvoiceXMLParser._parse_single_invoice(target)
                        if invoice:
                            invoices.append(invoice)

                    elif tag in ('HoaDonDienTu', 'Invoice', 'DLHDon'):
                        found_any = True
                        invoice = TaxInvoiceXMLParser._parse_single_invoice(elem)
                        if invoice:
                            invoices.append(invoice)

                # If no known invoice tags found, try parsing root directly
                if not found_any:
                    invoice = TaxInvoiceXMLParser._parse_single_invoice(root)
                    if invoice:
                        invoices.append(invoice)

            if not invoices:
                errors.append("Không tìm thấy hóa đơn trong file XML")

            logger.info(f"Parsed {len(invoices)} invoices from XML")

        except ET.ParseError as e:
            errors.append(f"Lỗi parse XML: {str(e)}")
            logger.error(f"XML parse error: {e}")
        except Exception as e:
            errors.append(f"Lỗi xử lý file: {str(e)}")
            logger.error(f"Error parsing XML: {e}")

        return invoices, errors

    @staticmethod
    def _parse_single_invoice(hdon_element) -> Optional[Dict]:
        """
        Parse một hóa đơn từ element HDon hoặc HoaDonDienTu

        Cấu trúc XML phổ biến:
        1. <HDon> với các section: TTChung, NBan, NMua, TToan
        2. <HoaDonDienTu> với các section tương tự
        3. Flat structure với tất cả fields ở root level
        """
        try:
            invoice = {}

            # Helper function để tìm text trong element (xử lý cả namespace)
            def find_text(parent, *paths):
                for path in paths:
                    for elem in parent.iter():
                        # Strip namespace if present
                        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                        # Chỉ khớp chính xác tag name, không dùng endswith để tránh KHMSHDon khớp với SHDon
                        if tag == path:
                            if elem.text:
                                return elem.text.strip()
                return ''

            # Helper để tìm trong section cụ thể (TTChung, NBan, TToan, etc.)
            def find_in_section(parent, section_names, *paths):
                """
                Tìm trong section cụ thể trước, sau đó fallback to toàn bộ document

                Xử lý cấu trúc lồng nhau như:
                <DLHDon>
                    <TTChung>...</TTChung>
                    <NDHDon>
                        <NBan>...</NBan>
                        <NMua>...</NMua>
                        <TToan>...</TToan>
                    </NDHDon>
                </DLHDon>
                """
                # Tìm section trực tiếp hoặc trong NDHDon
                for elem in parent.iter():
                    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                    if tag in section_names:
                        result = find_text(elem, *paths)
                        if result:
                            return result
                    # Nếu là NDHDon, tìm section bên trong
                    elif tag == 'NDHDon':
                        for child in elem.iter():
                            child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                            if child_tag in section_names:
                                result = find_text(child, *paths)
                                if result:
                                    return result
                # Fallback: tìm trong toàn bộ document
                return find_text(parent, *paths)

            # Helper để tìm trong NBan/BenBan (người bán/seller section)
            def find_in_seller(parent, *paths):
                return find_in_section(
                    parent,
                    ('NBan', 'BenBan', 'NguoiBan', 'Seller', 'NCC'),
                    *paths
                )

            # Helper để tìm trong TTChung (thông tin chung)
            def find_in_ttchung(parent, *paths):
                return find_in_section(
                    parent,
                    ('TTChung', 'ThongTinChung', 'GeneralInfo', 'Header'),
                    *paths
                )

            # Helper để tìm trong TToan (thanh toán)
            def find_in_ttoan(parent, *paths):
                return find_in_section(
                    parent,
                    ('TToan', 'ThanhToan', 'TongHop', 'Summary', 'Payment'),
                    *paths
                )

            # Helper để tìm text trong các element con trực tiếp (không dùng iter)
            def find_direct_child_text(parent, *tag_names):
                """Tìm text trong các element con trực tiếp của parent"""
                for child in parent:
                    child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if child_tag in tag_names and child.text:
                        return child.text.strip()
                return ''

            # Helper để tìm giá trị trong TTKhac section của một element
            def find_in_ttkhac(parent, *field_names):
                """
                Tìm giá trị trong TTKhac/TTin của parent element.
                TTKhac chứa các TTin, mỗi TTin có TTruong (tên field) và DLieu (giá trị).

                Ví dụ XML:
                <TTKhac>
                    <TTin><TTruong>VATAmount</TTruong><DLieu>27439.0</DLieu></TTin>
                    <TTin><TTruong>Amount</TTruong><DLieu>370439.0</DLieu></TTin>
                </TTKhac>
                """
                for child in parent:
                    child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if child_tag == 'TTKhac':
                        for ttin in child:
                            ttin_tag = ttin.tag.split('}')[-1] if '}' in ttin.tag else ttin.tag
                            if ttin_tag != 'TTin':
                                continue
                            ttruong_el = None
                            dlieu_el = None
                            for sub in ttin:
                                sub_tag = sub.tag.split('}')[-1] if '}' in sub.tag else sub.tag
                                if sub_tag == 'TTruong':
                                    ttruong_el = sub
                                elif sub_tag == 'DLieu':
                                    dlieu_el = sub
                            if ttruong_el is not None and ttruong_el.text and dlieu_el is not None and dlieu_el.text:
                                if ttruong_el.text.strip() in field_names:
                                    return dlieu_el.text.strip()
                return ''

            # ================================================================
            # 1. SỐ HÓA ĐƠN - tìm trong TTChung trước
            # ================================================================
            invoice['invoiceNo'] = find_in_ttchung(
                hdon_element,
                'SHDon', 'SoHoaDon', 'So', 'InvoiceNo', 'InvoiceNumber'
            )

            # Nếu không tìm thấy, thử tìm ở root
            if not invoice['invoiceNo']:
                invoice['invoiceNo'] = find_text(
                    hdon_element,
                    'SHDon', 'SoHoaDon', 'So', 'InvoiceNo', 'InvoiceNumber'
                )

            # ================================================================
            # 2. KÝ HIỆU HÓA ĐƠN (invoice symbol/serial)
            # KHMSHDon (mẫu số) + KHHDon (ký hiệu) = ký hiệu đầy đủ
            # Ví dụ: KHMSHDon="1" + KHHDon="C26TTY" = "1C26TTY"
            # ================================================================
            khmshdon = find_in_ttchung(hdon_element, 'KHMSHDon')
            khhdon = find_in_ttchung(
                hdon_element,
                'KHHDon', 'KyHieu', 'KyHieuHoaDon', 'SerialNo', 'Symbol', 'MauSo'
            )
            invoice['invoiceSymbol'] = (khmshdon or '') + (khhdon or '')

            # ================================================================
            # 3. NGÀY LẬP - tìm trong TTChung trước
            # ================================================================
            date_str = find_in_ttchung(
                hdon_element,
                'NLap', 'NgayLap', 'Ngay', 'InvoiceDate', 'Date', 'TDLap'
            )
            if not date_str:
                date_str = find_text(
                    hdon_element,
                    'NLap', 'NgayLap', 'Ngay', 'InvoiceDate', 'Date'
                )
            invoice['invoiceDate'] = TaxInvoiceXMLParser._normalize_date(date_str)

            # ================================================================
            # 4. THÔNG TIN NGƯỜI BÁN - tìm trong NBan section
            # ================================================================
            invoice['sellerTaxCode'] = find_in_seller(
                hdon_element,
                'MST', 'MaSoThue', 'TaxCode', 'SellerTaxCode', 'MSTNBan'
            )
            invoice['sellerName'] = find_in_seller(
                hdon_element,
                'Ten', 'TenDonVi', 'TenNguoiBan', 'TenCty', 'CompanyName',
                'SellerName', 'TenNBan', 'TenNCC','supplierName'
            )
            invoice['sellerAddress'] = find_in_seller(
                hdon_element,
                'DChi', 'DiaChi', 'Address', 'DChiNBan'
            )
            invoice['sellerPhone'] = find_in_seller(
                hdon_element,
                'SDThoai', 'DThoai', 'Phone', 'SellerPhone'
            )
            invoice['sellerEmail'] = find_in_seller(
                hdon_element,
                'DCTDTu', 'Email', 'SellerEmail'
            )

            # ================================================================
            # 5. THÔNG TIN NGƯỜI MUA (optional)
            # Tìm trực tiếp trong NMua section để đảm bảo lấy đúng
            # ================================================================
            # Tìm NMua section trước
            nmua_section = None
            for elem in hdon_element.iter():
                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if tag == 'NMua':
                    nmua_section = elem
                    break

            if nmua_section is not None:
                # Tìm trực tiếp trong NMua section
                invoice['buyerTaxCode'] = find_text(nmua_section, 'MST', 'MaSoThue', 'TaxCode')
                invoice['buyerName'] = find_text(nmua_section, 'Ten', 'TenDonVi', 'TenNguoiMua')
                invoice['buyerAddress'] = find_text(nmua_section, 'DChi', 'DiaChi', 'Address')
                invoice['buyerCode'] = find_text(nmua_section, 'MKHang', 'MaKH', 'BuyerCode')
                print(f"[PARSER DEBUG] NMua found: name={invoice['buyerName']}, address={invoice['buyerAddress']}")
                logger.info(f"[NMua] Found section, name={invoice['buyerName']}, taxCode={invoice['buyerTaxCode']}, address={invoice['buyerAddress']}")
            else:
                # Fallback: tìm theo cách cũ
                invoice['buyerTaxCode'] = find_in_section(
                    hdon_element,
                    ('NMua', 'BenMua', 'NguoiMua', 'Buyer'),
                    'MST', 'MaSoThue', 'TaxCode', 'MSTNMua'
                )
                invoice['buyerName'] = find_in_section(
                    hdon_element,
                    ('NMua', 'BenMua', 'NguoiMua', 'Buyer'),
                    'Ten', 'TenDonVi', 'TenNguoiMua', 'TenNMua', 'BuyerName'
                )
                invoice['buyerAddress'] = find_in_section(
                    hdon_element,
                    ('NMua', 'BenMua', 'NguoiMua', 'Buyer'),
                    'DChi', 'DiaChi', 'Address', 'DChiNMua'
                )
                invoice['buyerCode'] = find_in_section(
                    hdon_element,
                    ('NMua', 'BenMua', 'NguoiMua', 'Buyer'),
                    'MKHang', 'MaKH', 'BuyerCode'
                )
                logger.info(f"[NMua] Fallback used, name={invoice['buyerName']}, address={invoice['buyerAddress']}")

            # ================================================================
            # 6. TIỀN HÀNG TRƯỚC THUẾ - TgTCThue
            # ================================================================
            before_vat_str = find_in_ttoan(
                hdon_element,
                'TgTCThue', 'TgTHang', 'TienHang', 'TotalBeforeVat',
                'SubTotal', 'THTTLTSuat'
            )
            if not before_vat_str:
                before_vat_str = find_text(
                    hdon_element,
                    'TgTCThue', 'TgTHang', 'TienHang', 'TotalBeforeVat'
                )
            invoice['totalBeforeVat'] = TaxInvoiceXMLParser._parse_amount(before_vat_str)

            # ================================================================
            # 7. THUẾ GTGT - TgTThue (không phải TgThue)
            # ================================================================
            vat_str = find_in_ttoan(
                hdon_element,
                'TgTThue', 'TgThue', 'TienThueGTGT', 'TienThue', 'TThue',
                'VatAmount', 'TaxAmount'
            )
            if not vat_str:
                vat_str = find_text(
                    hdon_element,
                    'TgTThue', 'TgThue', 'TienThueGTGT', 'TienThue', 'VatAmount'
                )
            invoice['vatAmount'] = TaxInvoiceXMLParser._parse_amount(vat_str)

            # ================================================================
            # 7b. THUẾ SUẤT - TSuat (trong LTSuat hoặc trực tiếp)
            # ================================================================
            vat_rate_str = ''
            # Tìm trong LTSuat (Loại thuế suất) trước - duyệt trực tiếp các element con
            for elem in hdon_element.iter():
                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if tag == 'LTSuat':
                    print(f"[DEBUG] Found LTSuat element")
                    # Tìm TSuat trong các element con của LTSuat
                    for child in elem:
                        child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        print(f"[DEBUG] LTSuat child: {child_tag} = {child.text}")
                        if child_tag == 'TSuat' and child.text:
                            vat_rate_str = child.text.strip()
                            print(f"[DEBUG] Found TSuat in LTSuat: {vat_rate_str}")
                            break
                    if vat_rate_str:
                        break
            # Nếu không tìm thấy trong LTSuat, thử tìm trong items (HHDVu)
            if not vat_rate_str:
                print(f"[DEBUG] TSuat not found in LTSuat, searching in HHDVu...")
                for elem in hdon_element.iter():
                    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                    if tag in ('HHDVu', 'HHDV'):
                        for child in elem:
                            child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                            if child_tag == 'TSuat' and child.text:
                                vat_rate_str = child.text.strip()
                                print(f"[DEBUG] Found TSuat in HHDVu: {vat_rate_str}")
                                break
                        if vat_rate_str:
                            break
            print(f"[DEBUG] Final vat_rate_str: '{vat_rate_str}'")
            # Parse thuế suất (loại bỏ ký tự % nếu có)
            if vat_rate_str:
                vat_rate_str = vat_rate_str.replace('%', '').strip()
                try:
                    invoice['vatRate'] = float(vat_rate_str)
                    print(f"[DEBUG] Parsed vatRate: {invoice['vatRate']}")
                except ValueError:
                    invoice['vatRate'] = 0
            else:
                invoice['vatRate'] = 0
                print(f"[DEBUG] vatRate defaulted to 0")

            # ================================================================
            # 8. TỔNG TIỀN THANH TOÁN - TgTTTBSo
            # ================================================================
            total_str = find_in_ttoan(
                hdon_element,
                'TgTTTBSo', 'TongTienThanhToan', 'TongTien',
                'TgTTTBQT', 'TTCKTMai', 'TotalAmount', 'GrandTotal'
            )
            if not total_str:
                total_str = find_text(
                    hdon_element,
                    'TgTTTBSo', 'TongTienThanhToan', 'TongTien', 'TotalAmount'
                )
            invoice['totalAmount'] = TaxInvoiceXMLParser._parse_amount(total_str)
            
            invoice['totalAmountInWords'] = find_in_ttoan(
                hdon_element,
                'TgTTTBChu', 'VietBangChu', 'InWords'
            )

            # ================================================================
            # 9. DANH SÁCH HÀNG HÓA, DỊCH VỤ (items)
            # DSHHDVu: Danh sách hàng hóa dịch vụ (có thể là DSHHDV hoặc DSHHDVu tùy format)
            # ================================================================
            invoice['items'] = []
            dshhdv_element = None
            for elem in hdon_element.iter():
                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                # Hỗ trợ cả DSHHDV và DSHHDVu (format mới từ GDT)
                if tag in ('DSHHDV', 'DSHHDVu'):
                    dshhdv_element = elem
                    break

            if dshhdv_element is not None:
                print(f"[PARSER DEBUG] DSHHDVu found, parsing items...")
                logger.info(f"[DSHHDVu] Found items container")
                # Duyệt qua các element con trực tiếp của DSHHDVu
                for hhdv_element in dshhdv_element:
                    tag = hhdv_element.tag.split('}')[-1] if '}' in hhdv_element.tag else hhdv_element.tag
                    # Hỗ trợ cả HHDV và HHDVu (format mới từ GDT)
                    if tag not in ('HHDV', 'HHDVu'):
                        continue

                    stt_str = find_direct_child_text(hhdv_element, 'STT') or '0'
                    try:
                        stt = int(float(stt_str))  # Handle "1.0" format
                    except ValueError:
                        stt = 0

                    # Lấy tên hàng từ THHDVu (format mới) hoặc THHDV/TenHang (format cũ)
                    item_name = find_direct_child_text(hhdv_element, 'THHDVu', 'THHDV', 'TenHang') or ''
                    # Lấy đơn vị tính
                    item_unit = find_direct_child_text(hhdv_element, 'DVTinh', 'DonViTinh') or ''
                    # Lấy số lượng
                    item_quantity = TaxInvoiceXMLParser._parse_amount(find_direct_child_text(hhdv_element, 'SLuong', 'SoLuong'))
                    # Lấy đơn giá
                    item_unit_price = TaxInvoiceXMLParser._parse_amount(find_direct_child_text(hhdv_element, 'DGia', 'DonGia'))
                    # Lấy thành tiền
                    item_amount = TaxInvoiceXMLParser._parse_amount(find_direct_child_text(hhdv_element, 'ThTien', 'ThanhTien'))

                    # Lấy thuế per-item: ưu tiên TThue direct child, fallback TTKhac/VATAmount
                    _tthue_str = find_direct_child_text(hhdv_element, 'TThue', 'TienThue')
                    _ttkhac_vat_str = find_in_ttkhac(hhdv_element, 'VATAmount', 'VATAmountOC', 'TongTien_Thue', 'Tiền thuế dòng (Tiền thuế GTGT)')
                    has_per_item_tax = bool(_tthue_str or _ttkhac_vat_str)
                    item_tax_amount = TaxInvoiceXMLParser._parse_amount(_tthue_str or _ttkhac_vat_str)

                    # Fallback: tính tax từ per-item TSuat khi không có TThue
                    if item_tax_amount == 0 and item_amount > 0:
                        item_tsuat_str = find_direct_child_text(hhdv_element, 'TSuat', 'ThueSuat') or ''
                        item_tsuat = 0
                        if '%' in item_tsuat_str:
                            try:
                                item_tsuat = float(item_tsuat_str.replace('%', '').strip())
                            except ValueError:
                                item_tsuat = 0
                        if item_tsuat == 0 and vat_rate > 0:
                            item_tsuat = vat_rate
                        if item_tsuat > 0:
                            item_tax_amount = round(item_amount * item_tsuat / 100)
                            has_per_item_tax = True

                    # Lấy thành tiền sau thuế:
                    # - TTKhac/Amount > ThTien → dạng sau thuế (Vinamilk)
                    # - TTKhac/Amount > 0 + STCKhau > 0 → VNPT chiết khấu: Amount = (ThTien-CK)+VAT < ThTien
                    # - has_per_item_tax → tính amount + taxAmount
                    # - Không có per-item tax (dạng C26TTH) → None (FE hiển thị "-")
                    stckhau = TaxInvoiceXMLParser._parse_amount(find_direct_child_text(hhdv_element, 'STCKhau'))
                    ttkhac_amount = TaxInvoiceXMLParser._parse_amount(find_in_ttkhac(hhdv_element, 'Amount', 'AmountOC', 'TongTien_CoThue', 'Thành tiền thanh toán của hàng hóa'))
                    if ttkhac_amount > item_amount:
                        item_amount_after_tax = ttkhac_amount
                    elif ttkhac_amount > 0 and stckhau > 0:
                        # VNPT với chiết khấu: TTKhac/Amount = (ThTien - STCKhau) + VAT = Thành tiền thanh toán
                        item_amount_after_tax = ttkhac_amount
                    elif has_per_item_tax:
                        item_amount_after_tax = item_amount + item_tax_amount
                    else:
                        item_amount_after_tax = None

                    item = {
                        'stt': stt,
                        'name': item_name,  # Thống nhất dùng 'name' như internalData
                        'description': item_name,  # Backup cho template fallback
                        'unit': item_unit,
                        'quantity': item_quantity,
                        'unitPrice': item_unit_price,
                        'amount': item_amount,
                        'totalAmount': item_amount,  # Backup cho template fallback
                        'taxAmount': item_tax_amount,
                        'amountAfterTax': item_amount_after_tax,
                        'vatRate': find_direct_child_text(hhdv_element, 'TSuat', 'ThueSuat')
                    }
                    invoice['items'].append(item)
                    print(f"[PARSER DEBUG] Item {stt}: name='{item_name}', unit='{item_unit}'")
                    logger.info(f"[HHDVu] Item {stt}: name='{item_name}', unit='{item_unit}', qty={item_quantity}, amount={item_amount}")


            # Log để debug
            logger.info(
                f"Parsed invoice: no={invoice['invoiceNo']}, symbol={invoice.get('invoiceSymbol', '')}, "
                f"date={invoice['invoiceDate']}, seller={invoice['sellerName']}, "
                f"tax={invoice['sellerTaxCode']}, beforeVat={invoice.get('totalBeforeVat', 0)}, "
                f"vat={invoice['vatAmount']}, vatRate={invoice.get('vatRate', 0)}, total={invoice['totalAmount']}"
            )
            # Log buyer và items info để debug
            logger.info(
                f"Buyer info: name={invoice.get('buyerName', '')}, "
                f"taxCode={invoice.get('buyerTaxCode', '')}, "
                f"address={invoice.get('buyerAddress', '')}"
            )
            if invoice.get('items'):
                logger.info(f"Items count: {len(invoice['items'])}")
                for idx, item in enumerate(invoice['items'][:2]):  # Log 2 items đầu
                    logger.info(f"  Item {idx+1}: name={item.get('name', '')}, unit={item.get('unit', '')}, amount={item.get('amount', 0)}")

            # Validate required fields
            if not invoice['invoiceNo']:
                logger.warning("Missing invoice number")
                return None

            return invoice

        except Exception as e:
            logger.error(f"Error parsing invoice element: {e}")
            return None

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """Chuẩn hóa ngày về định dạng YYYY-MM-DD"""
        if not date_str:
            return ''

        # Thử các định dạng phổ biến
        formats = [
            '%Y-%m-%d',
            '%d/%m/%Y',
            '%d-%m-%Y',
            '%Y%m%d',
            '%d.%m.%Y'
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str[:10], fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue

        return date_str

    @staticmethod
    def _parse_amount(amount_str: str) -> float:
        """Parse số tiền từ string"""
        if not amount_str:
            return 0.0

        try:
            # Remove non-numeric characters except decimal point
            cleaned = re.sub(r'[^\d.,]', '', amount_str)
            # Handle Vietnamese format (1.234.567,89)
            if ',' in cleaned and '.' in cleaned:
                cleaned = cleaned.replace('.', '').replace(',', '.')
            elif ',' in cleaned:
                cleaned = cleaned.replace(',', '.')

            return float(cleaned)
        except ValueError:
            return 0.0


class TaxInvoiceExcelParser:
    """
    Parser cho file Excel xuất từ trang thuế

    Cấu trúc Excel điển hình:
    | STT | Số hóa đơn | Ngày | MST NCC | Tên NCC | Tổng tiền | Thuế GTGT |
    """

    # Column name mappings (Vietnamese -> internal)
    COLUMN_MAPPINGS = {
        # Invoice number
        'so hoa don': 'invoiceNo',
        'số hóa đơn': 'invoiceNo',
        'so hd': 'invoiceNo',
        'số hđ': 'invoiceNo',
        'shdon': 'invoiceNo',

        # Date
        'ngay': 'invoiceDate',
        'ngày': 'invoiceDate',
        'ngay hd': 'invoiceDate',
        'ngày hđ': 'invoiceDate',
        'ngay lap': 'invoiceDate',
        'ngày lập': 'invoiceDate',

        # Seller tax code
        'mst': 'sellerTaxCode',
        'ma so thue': 'sellerTaxCode',
        'mã số thuế': 'sellerTaxCode',
        'mst ncc': 'sellerTaxCode',
        'mst nguoi ban': 'sellerTaxCode',

        # Seller name
        'ten ncc': 'sellerName',
        'tên ncc': 'sellerName',
        'ten nguoi ban': 'sellerName',
        'tên người bán': 'sellerName',
        'nha cung cap': 'sellerName',
        'nhà cung cấp': 'sellerName',

        # Total amount
        'tong tien': 'totalAmount',
        'tổng tiền': 'totalAmount',
        'tien hang': 'totalAmount',
        'tiền hàng': 'totalAmount',
        'thanh tien': 'totalAmount',
        'thành tiền': 'totalAmount',
        'tong thanh toan': 'totalAmount',

        # VAT amount
        'thue': 'vatAmount',
        'thuế': 'vatAmount',
        'thue gtgt': 'vatAmount',
        'thuế gtgt': 'vatAmount',
        'tien thue': 'vatAmount',
        'tiền thuế': 'vatAmount',
        'vat': 'vatAmount'
    }

    @staticmethod
    def parse(excel_content: bytes) -> Tuple[List[Dict], List[str]]:
        """
        Parse file Excel từ trang thuế

        Args:
            excel_content: Nội dung file Excel dạng bytes

        Returns:
            (list_invoices, list_errors)
        """
        invoices = []
        errors = []

        try:
            # Try import openpyxl
            try:
                import openpyxl
                from io import BytesIO
            except ImportError:
                errors.append("Thiếu thư viện openpyxl. Chạy: pip install openpyxl")
                return invoices, errors

            # Load workbook
            wb = openpyxl.load_workbook(BytesIO(excel_content), data_only=True)
            ws = wb.active

            # Find header row and column mapping
            header_row = None
            column_map = {}

            for row_idx, row in enumerate(ws.iter_rows(max_row=10), start=1):
                for col_idx, cell in enumerate(row):
                    if cell.value:
                        cell_text = str(cell.value).lower().strip()
                        # Remove accents for matching
                        cell_text_no_accent = TaxInvoiceExcelParser._remove_accents(cell_text)

                        for key, field in TaxInvoiceExcelParser.COLUMN_MAPPINGS.items():
                            key_no_accent = TaxInvoiceExcelParser._remove_accents(key)
                            if key_no_accent in cell_text_no_accent or cell_text_no_accent in key_no_accent:
                                column_map[col_idx] = field
                                header_row = row_idx
                                break

                if header_row and len(column_map) >= 3:  # At least invoice number, date, and amount
                    break

            if not header_row:
                errors.append("Không tìm thấy header row trong file Excel")
                return invoices, errors

            logger.info(f"Found header at row {header_row}, columns: {column_map}")

            # Parse data rows
            for row_idx, row in enumerate(ws.iter_rows(min_row=header_row + 1), start=header_row + 1):
                invoice = {}
                has_data = False

                for col_idx, cell in enumerate(row):
                    if col_idx in column_map and cell.value is not None:
                        field = column_map[col_idx]
                        value = cell.value

                        if field == 'invoiceDate':
                            if isinstance(value, datetime):
                                value = value.strftime('%Y-%m-%d')
                            else:
                                value = TaxInvoiceXMLParser._normalize_date(str(value))
                        elif field in ['totalAmount', 'vatAmount']:
                            if isinstance(value, (int, float)):
                                value = float(value)
                            else:
                                value = TaxInvoiceXMLParser._parse_amount(str(value))
                        else:
                            value = str(value).strip()

                        invoice[field] = value
                        if value:
                            has_data = True

                # Only add if has invoice number
                if has_data and invoice.get('invoiceNo'):
                    # Set defaults for missing fields
                    invoice.setdefault('invoiceDate', '')
                    invoice.setdefault('sellerTaxCode', '')
                    invoice.setdefault('sellerName', '')
                    invoice.setdefault('totalAmount', 0.0)
                    invoice.setdefault('vatAmount', 0.0)

                    invoices.append(invoice)

            logger.info(f"Parsed {len(invoices)} invoices from Excel")

        except Exception as e:
            errors.append(f"Lỗi xử lý file Excel: {str(e)}")
            logger.error(f"Error parsing Excel: {e}")

        return invoices, errors

    @staticmethod
    def _remove_accents(text: str) -> str:
        """Remove Vietnamese accents"""
        accent_map = {
            'á': 'a', 'à': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
            'ă': 'a', 'ắ': 'a', 'ằ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
            'â': 'a', 'ấ': 'a', 'ầ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
            'đ': 'd',
            'é': 'e', 'è': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
            'ê': 'e', 'ế': 'e', 'ề': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
            'í': 'i', 'ì': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
            'ó': 'o', 'ò': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
            'ô': 'o', 'ố': 'o', 'ồ': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
            'ơ': 'o', 'ớ': 'o', 'ờ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
            'ú': 'u', 'ù': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
            'ư': 'u', 'ứ': 'u', 'ừ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
            'ý': 'y', 'ỳ': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y'
        }
        result = text.lower()
        for accented, plain in accent_map.items():
            result = result.replace(accented, plain)
        return result


class LocalInvoiceJSONParser:
    """
    Parser cho file JSON từ OCR (Gemini Flash)

    Cấu trúc JSON điển hình từ Gemini OCR:
    {
        "invoice_number": "0001234",
        "invoice_date": "2024-01-15",
        "seller": {
            "tax_code": "0301234567",
            "name": "Công ty ABC"
        },
        "total_amount": 7830000,
        "vat_amount": 711818,
        "confidence": 0.92
    }

    Hoặc định dạng đơn giản:
    {
        "invoiceNo": "0001234",
        "invoiceDate": "2024-01-15",
        "supplierTaxCode": "0301234567",
        "supplierName": "Công ty ABC",
        "totalAmount": 7830000,
        "vatAmount": 711818
    }
    """

    @staticmethod
    def parse(json_content: bytes) -> Tuple[List[Dict], List[str]]:
        """
        Parse file JSON từ OCR

        Args:
            json_content: Nội dung file JSON dạng bytes

        Returns:
            (list_invoices, list_errors)
        """
        invoices = []
        errors = []

        try:
            # Decode and parse JSON
            content_str = json_content.decode('utf-8')
            data = json.loads(content_str)

            # Handle both single invoice and array of invoices
            if isinstance(data, list):
                for item in data:
                    invoice = LocalInvoiceJSONParser._normalize_invoice(item)
                    if invoice:
                        invoices.append(invoice)
            elif isinstance(data, dict):
                # Check if it's a wrapper object
                if 'invoices' in data:
                    for item in data['invoices']:
                        invoice = LocalInvoiceJSONParser._normalize_invoice(item)
                        if invoice:
                            invoices.append(invoice)
                elif 'data' in data:
                    for item in data['data']:
                        invoice = LocalInvoiceJSONParser._normalize_invoice(item)
                        if invoice:
                            invoices.append(invoice)
                else:
                    # Single invoice
                    invoice = LocalInvoiceJSONParser._normalize_invoice(data)
                    if invoice:
                        invoices.append(invoice)

            if not invoices:
                errors.append("Không tìm thấy hóa đơn hợp lệ trong file JSON")

            logger.info(f"Parsed {len(invoices)} invoices from JSON")

        except json.JSONDecodeError as e:
            errors.append(f"Lỗi parse JSON: {str(e)}")
            logger.error(f"JSON parse error: {e}")
        except Exception as e:
            errors.append(f"Lỗi xử lý file: {str(e)}")
            logger.error(f"Error parsing JSON: {e}")

        return invoices, errors

    @staticmethod
    def _normalize_invoice(data: Dict) -> Optional[Dict]:
        """Chuẩn hóa cấu trúc hóa đơn từ JSON"""
        try:
            invoice = {}

            # Invoice number - try multiple field names
            invoice['invoiceNo'] = (
                data.get('invoiceNo') or
                data.get('invoice_number') or
                data.get('soHoaDon') or
                data.get('so_hoa_don') or
                data.get('SHDon') or
                ''
            )

            if not invoice['invoiceNo']:
                return None

            # Invoice date
            date_val = (
                data.get('invoiceDate') or
                data.get('invoice_date') or
                data.get('ngayHoaDon') or
                data.get('ngay_hoa_don') or
                data.get('NLap') or
                ''
            )
            invoice['invoiceDate'] = TaxInvoiceXMLParser._normalize_date(str(date_val))

            # Supplier info - may be nested or flat
            seller = data.get('seller') or data.get('nguoi_ban') or {}

            invoice['supplierTaxCode'] = (
                data.get('supplierTaxCode') or
                data.get('supplier_tax_code') or
                data.get('maSoThueNCC') or
                data.get('mst') or
                seller.get('tax_code') or
                seller.get('mst') or
                ''
            )

            invoice['supplierName'] = (
                data.get('supplierName') or
                data.get('supplier_name') or
                data.get('tenNCC') or
                data.get('ten_ncc') or
                seller.get('name') or
                seller.get('ten') or
                ''
            )

            # Amounts
            invoice['totalAmount'] = float(
                data.get('totalAmount') or
                data.get('total_amount') or
                data.get('tongTien') or
                data.get('tong_tien') or
                0
            )

            invoice['vatAmount'] = float(
                data.get('vatAmount') or
                data.get('vat_amount') or
                data.get('thueGTGT') or
                data.get('thue_gtgt') or
                data.get('tien_thue') or
                0
            )

            # OCR confidence
            invoice['ocrConfidence'] = float(
                data.get('ocrConfidence') or
                data.get('confidence') or
                data.get('do_chinh_xac') or
                0
            )

            return invoice

        except Exception as e:
            logger.error(f"Error normalizing invoice: {e}")
            return None


def detect_and_parse(content: bytes, filename: str) -> Tuple[List[Dict], List[str], str]:
    """
    Tự động detect loại file và parse

    Args:
        content: Nội dung file
        filename: Tên file

    Returns:
        (list_invoices, list_errors, file_type)
    """
    filename_lower = filename.lower()

    if filename_lower.endswith('.xml'):
        invoices, errors = TaxInvoiceXMLParser.parse(content)
        return invoices, errors, 'xml'

    elif filename_lower.endswith(('.xlsx', '.xls')):
        invoices, errors = TaxInvoiceExcelParser.parse(content)
        return invoices, errors, 'excel'

    elif filename_lower.endswith('.json'):
        invoices, errors = LocalInvoiceJSONParser.parse(content)
        return invoices, errors, 'json'

    else:
        # Try to detect by content
        try:
            # Try JSON first
            json.loads(content.decode('utf-8'))
            invoices, errors = LocalInvoiceJSONParser.parse(content)
            return invoices, errors, 'json'
        except:
            pass

        try:
            # Try XML
            ET.fromstring(content)
            invoices, errors = TaxInvoiceXMLParser.parse(content)
            return invoices, errors, 'xml'
        except:
            pass

        return [], [f"Không hỗ trợ định dạng file: {filename}"], 'unknown'
