
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
            item = {
                'name': TaxInvoiceXMLParser._get_text(item_tag, 'THHDVu'),
                'unit': TaxInvoiceXMLParser._get_text(item_tag, 'DVTinh'),
                'quantity': TaxInvoiceXMLParser._get_float(item_tag, 'SLuong'),
                'unitPrice': TaxInvoiceXMLParser._get_float(item_tag, 'DGia'),
                'total': TaxInvoiceXMLParser._get_float(item_tag, 'ThTien'),
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

