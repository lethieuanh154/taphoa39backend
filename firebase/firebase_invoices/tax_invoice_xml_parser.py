
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)

class TaxInvoiceXMLParser:
    """
    Parses XML tax invoices from the tax authority's format.
    """

    @staticmethod
    def parse(xml_content: bytes) -> Tuple[List[Dict], List[str]]:
        """
        Parses the XML content and extracts invoice data.

        Args:
            xml_content: The byte content of the XML file.

        Returns:
            A tuple containing a list of parsed invoices and a list of errors.
        """
        all_invoices = []
        errors = []

        try:
            # The XML might have a namespace, which we need to handle.
            # We'll try to find it dynamically.
            # We also need to remove the XML declaration if it exists, as it can interfere with parsing
            xml_content_str = xml_content.decode('utf-8').lstrip('\ufeff')
            root = ET.fromstring(xml_content_str)
            
            # Find all HDon tags, which likely represent individual invoices
            # In case the structure is different, we can add more potential tags here
            invoice_tags = root.findall('.//HDon')
            
            if not invoice_tags:
                invoice_tags = root.findall('.//Invoice')

            if not invoice_tags:
                 # Fallback to root if no specific invoice tag is found
                invoice_tags = [root] if root.tag.endswith('HDon') or root.tag.endswith('Invoice') else []


            if not invoice_tags:
                errors.append("No <HDon> or <Invoice> tags found in the XML file.")
                return [], errors

            for inv_tag in invoice_tags:
                try:
                    invoice_data = TaxInvoiceXMLParser._extract_invoice_data(inv_tag, root)
                    all_invoices.append(invoice_data)
                except Exception as e:
                    errors.append(f"Error parsing an invoice entry: {str(e)}")

        except ET.ParseError as e:
            errors.append(f"XML Parse Error: {e}")
        except Exception as e:
            errors.append(f"An unexpected error occurred during parsing: {e}")
            logger.exception("Unexpected error in TaxInvoiceXMLParser")

        return all_invoices, errors

    @staticmethod
    def _find_tag(element: ET.Element, path: str):
        # Helper to find a tag, ignoring namespaces
        return element.find(f".//{{*}}{path}")

    @staticmethod
    def _get_text(element: ET.Element, path: str, default: str = '') -> str:
        # Helper to get text from a tag, ignoring namespaces
        el = TaxInvoiceXMLParser._find_tag(element, path)
        return el.text.strip() if el is not None and el.text else default

    @staticmethod
    def _get_float(element: ET.Element, path: str, default: float = 0.0) -> float:
        # Helper to get a float value from a tag
        text_val = TaxInvoiceXMLParser._get_text(element, path)
        try:
            return float(text_val)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _get_ttkhac_float(element: ET.Element, *field_names) -> float:
        """
        Tìm giá trị số trong TTKhac/TTin của element.
        TTKhac chứa các TTin, mỗi TTin có TTruong (tên field) và DLieu (giá trị).
        """
        for child in element:
            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag == 'TTKhac':
                for ttin in child:
                    ttin_tag = ttin.tag.split('}')[-1] if '}' in ttin.tag else ttin.tag
                    if ttin_tag != 'TTin':
                        continue
                    ttruong_el = ttin.find('TTruong')
                    dlieu_el = ttin.find('DLieu')
                    if ttruong_el is not None and ttruong_el.text and dlieu_el is not None and dlieu_el.text:
                        if ttruong_el.text.strip() in field_names:
                            try:
                                return float(dlieu_el.text.strip())
                            except (ValueError, TypeError):
                                return 0.0
        return 0.0

    @staticmethod
    def _extract_invoice_data(inv_tag: ET.Element, root: ET.Element) -> Dict:
        """Extracts data from a single invoice XML element."""
        
        # Seller info often outside the main invoice block
        seller_name = TaxInvoiceXMLParser._get_text(root, 'NBanTen')
        seller_tax_code = TaxInvoiceXMLParser._get_text(root, 'NBanMST')
        
        # Invoice details
        invoice_no = TaxInvoiceXMLParser._get_text(inv_tag, 'SHDon')
        invoice_date_str = TaxInvoiceXMLParser._get_text(inv_tag, 'NLap') # Ngay Lap
        
        # Buyer info
        buyer_name = TaxInvoiceXMLParser._get_text(inv_tag, 'NMuaTen')
        buyer_tax_code = TaxInvoiceXMLParser._get_text(inv_tag, 'NMuaMST')
        buyer_address = TaxInvoiceXMLParser._get_text(inv_tag, 'NMuaDChi')
        
        # Financials
        total_before_vat = TaxInvoiceXMLParser._get_float(inv_tag, 'TgTCThue')  # Tong tien chua thue (before VAT)
        vat_amount = TaxInvoiceXMLParser._get_float(inv_tag, 'TgTThue')  # Tong tien thue (VAT amount)
        total_amount = TaxInvoiceXMLParser._get_float(inv_tag, 'TgTTToan')  # Tong tien thanh toan (total)
        
        # VAT Rate is tricky, it might be on each item or a summary field.
        # Let's look for a summary field first.
        vat_rate_str = TaxInvoiceXMLParser._get_text(inv_tag, 'TSuat') # Thue suat
        vat_rate = 0
        if "%" in vat_rate_str:
            try:
                vat_rate = float(vat_rate_str.replace('%','').strip())
            except ValueError:
                vat_rate = 0 # Or some other default
        
        # Items
        items = []
        item_tags = inv_tag.findall('.//HHDVu') # Hang hoa, dich vu
        for item_tag in item_tags:
            amount = TaxInvoiceXMLParser._get_float(item_tag, 'ThTien')
            # Chiết khấu giảm trừ dòng (STCKhau). ThTien = SL×DGia CHƯA trừ chiết khấu,
            # nên base trước thuế thực tế = ThTien - STCKhau.
            discount = TaxInvoiceXMLParser._get_float(item_tag, 'STCKhau')
            gross = TaxInvoiceXMLParser._get_float(item_tag, 'SLuong') * TaxInvoiceXMLParser._get_float(item_tag, 'DGia')
            # MISA: ThTien đã trừ CK sẵn (ThTien ≈ SL×ĐG - STCKhau) → không trừ lần nữa
            ck_already_deducted = discount > 0 and gross > 0 and abs(amount - (gross - discount)) < 2
            net_before_tax = amount if ck_already_deducted else amount - discount
            # Lấy thuế per-item: ưu tiên TThue direct tag, fallback TTKhac/VATAmount
            tax_amount = TaxInvoiceXMLParser._get_float(item_tag, 'TThue')
            if tax_amount == 0:
                tax_amount = TaxInvoiceXMLParser._get_ttkhac_float(item_tag, 'VATAmount', 'VATAmountOC', 'TongTien_Thue', 'Tiền thuế dòng (Tiền thuế GTGT)')
            # Fallback: tính tax từ per-item TSuat khi không có TThue (trên base đã trừ chiết khấu)
            if tax_amount == 0 and net_before_tax > 0:
                item_tsuat_str = TaxInvoiceXMLParser._get_text(item_tag, 'TSuat')
                item_tsuat = 0
                if '%' in item_tsuat_str:
                    try:
                        item_tsuat = float(item_tsuat_str.replace('%', '').strip())
                    except ValueError:
                        item_tsuat = 0
                # Nếu per-item không có TSuat, dùng vat_rate từ summary
                if item_tsuat == 0 and vat_rate > 0:
                    item_tsuat = vat_rate
                logger.info(f"[TAX DEBUG] item_tsuat_str='{item_tsuat_str}', item_tsuat={item_tsuat}, net_before_tax={net_before_tax}")
                if item_tsuat > 0:
                    tax_amount = round(net_before_tax * item_tsuat / 100)
                    logger.info(f"[TAX DEBUG] computed tax_amount={tax_amount}")
            # Lấy thành tiền sau thuế:
            # - TTKhac/Amount = thành tiền thanh toán (đã trừ chiết khấu + gồm thuế) nếu > net_before_tax
            # - Ngược lại (dạng B MISA: Amount = trước thuế) thì tính = net_before_tax + tax_amount
            ttkhac_amount = TaxInvoiceXMLParser._get_ttkhac_float(item_tag, 'Amount', 'AmountOC', 'TongTien_CoThue', 'Thành tiền thanh toán của hàng hóa')
            # MISA (Tâm Bảo Phương): TTKhac/Amount = SL × ĐG (trước CK, trước thuế) → KHÔNG phải sau thuế
            is_gross_amount = discount > 0 and gross > 0 and abs(ttkhac_amount - gross) < 2
            if ttkhac_amount > net_before_tax and not is_gross_amount:
                amount_after_tax = ttkhac_amount
            else:
                amount_after_tax = net_before_tax + tax_amount
            logger.info(f"[TAX DEBUG] FINAL: amount={amount}, discount={discount}, net_before_tax={net_before_tax}, tax_amount={tax_amount}, amount_after_tax={amount_after_tax}")
            item = {
                'name': TaxInvoiceXMLParser._get_text(item_tag, 'THHDVu'),
                'unit': TaxInvoiceXMLParser._get_text(item_tag, 'DVTinh'),
                'quantity': TaxInvoiceXMLParser._get_float(item_tag, 'SLuong'),
                'unitPrice': TaxInvoiceXMLParser._get_float(item_tag, 'DGia'),
                'total': net_before_tax,
                'discount': discount,
                'taxAmount': tax_amount,
                'amountAfterTax': amount_after_tax,
            }
            items.append(item)

        return {
            'invoiceNo': invoice_no,
            'invoiceSymbol': TaxInvoiceXMLParser._get_text(inv_tag, 'KHHDon'), # Ki hieu hoa don
            'invoiceDate': invoice_date_str,
            'buyerName': buyer_name,
            'buyerTaxCode': buyer_tax_code,
            'buyerAddress': buyer_address,
            'sellerName': seller_name,
            'sellerTaxCode': seller_tax_code,
            'totalBeforeVat': total_before_vat,
            'totalAmount': total_amount,
            'vatAmount': vat_amount,
            'vatRate': vat_rate, # This is an approximation
            'items': items
        }

