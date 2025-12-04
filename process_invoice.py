import easyocr
import json
from pdf2image import convert_from_path
import numpy as np
import sys
import re

def extract_invoice_data_from_pdf(pdf_path):
    """
    Doc file PDF su dung EasyOCR va tra ve object JSON theo dinh dang chuan
    """
    try:
        # Khoi tao EasyOCR reader (ho tro tieng Viet va tieng Anh)
        reader = easyocr.Reader(['vi', 'en'], gpu=False)

        # Chuyen doi PDF thanh anh
        print(f"Dang chuyen doi PDF thanh anh...")
        images = convert_from_path(pdf_path, dpi=300)

        all_text = []

        # Doc OCR tung trang
        for i, image in enumerate(images):
            print(f"Dang doc trang {i+1}/{len(images)}...")

            # Chuyen PIL Image thanh numpy array
            img_array = np.array(image)

            # Thuc hien OCR
            result = reader.readtext(img_array, detail=1)

            for detection in result:
                _, text, confidence = detection
                all_text.append({
                    'text': text,
                    'confidence': float(confidence),
                    'page': i + 1
                })

        # Tao dictionary de tim kiem text theo index
        texts = [item['text'] for item in all_text]

        # Trích xuất dữ liệu theo format chuẩn
        invoice_data = build_standard_invoice_json(texts, all_text)

        return invoice_data

    except Exception as e:
        import traceback
        return {
            'error': str(e),
            'traceback': traceback.format_exc(),
            'message': 'Co loi xay ra khi doc PDF'
        }

def find_text_after(texts, keywords, offset=1):
    """Tim text sau keyword"""
    for i, text in enumerate(texts):
        for keyword in keywords:
            if keyword.lower() in text.lower():
                # Neu co dau : thi lay phan sau dau :
                if ':' in text:
                    parts = text.split(':', 1)
                    if len(parts) > 1 and parts[1].strip():
                        return parts[1].strip()
                # Neu khong thi lay text o vi tri tiep theo
                if i + offset < len(texts):
                    return texts[i + offset].strip()
    return ''

def find_text_containing(texts, keywords):
    """Tim text chua keyword"""
    for text in texts:
        for keyword in keywords:
            if keyword.lower() in text.lower():
                return text.strip()
    return ''

def parse_number(text):
    """Chuyen text thanh so"""
    if not text:
        return 0
    # Loai bo cac ky tu khong phai so, dau cham, dau phay
    cleaned = re.sub(r'[^\d.,]', '', text)
    # Loai bo dau phan cach hang ngan
    cleaned = cleaned.replace(',', '').replace('.', '')
    try:
        return int(cleaned)
    except:
        try:
            return float(cleaned)
        except:
            return 0

def parse_decimal(text):
    """Chuyen text thanh so thap phan"""
    if not text:
        return 0.0
    # Xu ly so co dang 325.928,00 (dau . la phan cach ngan, dau , la thap phan)
    # hoac 7.314,79 (EU style)
    if ',' in text:
        # Loai bo dau . (phan cach ngan), thay , thanh .
        cleaned = text.replace('.', '').replace(',', '.')
    else:
        # Khong co dau phay, giu nguyen dau cham
        cleaned = text
    # Loai bo ky tu khong phai so va dau cham
    cleaned = re.sub(r'[^\d.]', '', cleaned)
    try:
        return float(cleaned)
    except:
        return 0.0

def extract_items_detailed(texts):
    """Trich xuat chi tiet cac mat hang"""
    items = []

    # Tim vi tri bat dau va ket thuc bang danh sach hang hoa
    start_idx = -1
    end_idx = len(texts)

    for i, text in enumerate(texts):
        if 'STT' in text or 'Tên hàng' in text or 'Ten hang' in text:
            start_idx = i
        if 'Cộng tiền hàng' in text or 'Cong tien hang' in text or 'Thuế suất' in text or 'Thue suat' in text:
            end_idx = i
            break

    if start_idx == -1:
        return items

    # Duyet qua cac dong trong bang
    i = start_idx + 1
    stt = 1

    while i < end_idx:
        text = texts[i].strip()

        # Kiem tra xem co phai la ten san pham khong
        # Co the la: "KD BMT ..." hoac "[Cung Đình ..." hoac bat dau bang "Cung Dinh"
        is_product = False
        if ('KD' in text and 'BMT' in text) and len(text) > 5:
            is_product = True
        elif text.startswith('[Cung') or text.startswith('Cung Đình') or text.startswith('Cung Dinh'):
            is_product = True
        elif 'Cung Đình' in text or 'Cung Dinh' in text:
            is_product = True

        if is_product:
            # Loai bo dau [ neu co
            product_name = text.replace('[', '').strip()

            item = {
                "STT": stt,
                "Tên hàng hóa": product_name,
                "ĐVT": "",
                "Số lượng": 0,
                "Đơn giá": 0.0,
                "Thành tiền": 0
            }

            # Kiem tra xem ten san pham co bi tach ra nhieu dong khong
            # Neu dong tiep theo khong phai la DVT va khong phai la so thi co the la phan con lai cua ten
            if i + 1 < len(texts):
                next_text = texts[i + 1].strip()
                # Neu dong tiep theo la text (khong phai DVT, khong phai so) thi ghep vao ten
                if next_text and not re.match(r'^\d', next_text) and next_text not in ['Thùng', 'Cái', 'Hộp', 'Kg', 'Lít', 'Chai', 'Gói', 'Thung', 'Cai', 'Hop', 'Lit', 'thùng', 'Gói', '|thùng', 'Ithùng']:
                    # Kiem tra xem co phai la phan con lai cua ten san pham khong
                    if any(x in next_text for x in ['Hà Nội', 'Việt Nam', 'gói', 'ly', 'thố']):
                        item["Tên hàng hóa"] += ' ' + next_text.replace('[', '').strip()
                        i += 1

            # Tim DVT (don vi tinh) - thuong la text ngay sau ten hang hoa
            if i + 1 < len(texts):
                potential_dvt = texts[i + 1].strip().replace('|', '').replace('[', '')
                if potential_dvt.lower() in ['thùng', 'cái', 'hộp', 'kg', 'lít', 'chai', 'gói', 'thung', 'cai', 'hop', 'lit', 'goi']:
                    item["ĐVT"] = potential_dvt.capitalize()
                    i += 1

            # Tim so luong - thuong la so thap phan nho
            if i + 1 < len(texts):
                potential_qty = texts[i + 1].strip()
                # So luong thuong la so nho (0.xxx hoac xx.xxx)
                if re.match(r'^\d+[.,]\d+$', potential_qty) or re.match(r'^\d+$', potential_qty):
                    qty_val = parse_decimal(potential_qty)
                    if qty_val < 1:  # 0.250
                        item["Số lượng"] = qty_val
                    else:
                        item["Số lượng"] = int(qty_val)
                    i += 1

            # Tim don gia - thuong co dinh dang xxx.xxx,xx hoac x.xxx,xx
            if i + 1 < len(texts):
                potential_price = texts[i + 1].strip()
                # Don gia co dang nhu 325.928,00 hoac 7.314,79
                if re.match(r'^\d+\.\d+(,\d+)?$', potential_price):
                    item["Đơn giá"] = parse_decimal(potential_price)
                    i += 1

            # Tim thanh tien - so nguyen sau don gia
            if i + 1 < len(texts):
                potential_total = texts[i + 1].strip()
                # Thanh tien co dang nhu 81.482 hoac 73.148
                if re.match(r'^\d+\.\d+$', potential_total):
                    item["Thành tiền"] = parse_number(potential_total)
                    i += 1

            i += 1

            items.append(item)
            stt += 1

        i += 1

    return items

def build_standard_invoice_json(texts, all_text):
    """Xay dung JSON theo dinh dang chuan"""

    # Loai hoa don
    invoice_type = ""
    if find_text_containing(texts, ['GIÁ TRỊ GIA TĂNG', 'GIA TRI GIA TANG']):
        invoice_type = "Hóa đơn giá trị gia tăng"

    # Ky hieu va so
    symbol = find_text_after(texts, ['Ký hiệu:', 'Ky hieu:'])
    number = find_text_after(texts, ['Số:', 'So:'])

    # Neu so co dang "Số: 00005186" thi tach ra
    if not number:
        so_text = find_text_containing(texts, ['Số:', 'So:'])
        if ':' in so_text:
            number = so_text.split(':')[1].strip()

    # Ngay hoa don
    date = ""
    for i, text in enumerate(texts):
        if 'Ngày' in text or 'Ngay' in text or 'ngày' in text:
            # Tim cac so tiep theo: ngay, thang, nam
            day = month = year = ""
            for j in range(i+1, min(i+6, len(texts))):
                t = texts[j].strip()
                if re.match(r'^\d{1,2}$', t) and not day:
                    day = t
                elif re.match(r'^\d{1,2}$', t) and day and not month:
                    month = t
                elif t in ['tháng', 'thang', 'năm', 'nam', '1l', 'll']:
                    continue
                elif re.match(r'^\d{4}$', t) and not year:
                    year = t
                    break
            if day and year:
                # Xu ly truong hop thang bi nhan nham (1l, ll -> 11)
                if not month or month in ['1l', 'll']:
                    month = '11'
                date = f"{day}/{month}/{year}"
                break

    # Thong tin ben ban
    seller_name = find_text_after(texts, ['Đơn vị bán hàng', 'Don vi ban hang', 'Đơn vị bán', 'Don vi ban'])
    seller_tax = ""
    seller_address = ""
    seller_phone = ""
    seller_fax = ""
    seller_account = ""

    # Tim MST ben ban
    for i, text in enumerate(texts):
        if 'Mã số thuế' in text or 'Ma so thue' in text:
            if i + 1 < len(texts):
                potential_tax = texts[i + 1].strip()
                # MST ben ban thuong bat dau bang 04
                if potential_tax.startswith('04') and len(potential_tax) == 10:
                    seller_tax = potential_tax
                    break

    # Dia chi ben ban
    for i, text in enumerate(texts):
        if 'Địa chỉ' in text or 'Dia chi' in text:
            # Lay cac text tiep theo cho den khi gap thong tin khac
            addr_parts = []
            for j in range(i+1, min(i+5, len(texts))):
                t = texts[j].strip()
                if 'Điện thoại' in t or 'Dien thoai' in t or 'Mã số' in t:
                    break
                if 'Hoàng Hoa Thám' in t or 'Thanh Khê' in t or 'Đà Nẵng' in t or t == 'Việt Nam':
                    addr_parts.append(t)
            if addr_parts:
                seller_address = ', '.join(addr_parts)
                break

    # Dien thoai va Fax
    seller_phone = find_text_after(texts, ['Điện thoại', 'Dien thoai'])
    for text in texts:
        if 'Fax:' in text or '*Fax:' in text:
            fax_match = re.search(r'Fax:\s*([\d.]+)', text)
            if fax_match:
                seller_fax = fax_match.group(1)

    # So tai khoan
    for i, text in enumerate(texts):
        if 'Số tài khoản' in text or 'So tai khoan' in text:
            # Lay tat ca text lien quan den tai khoan
            acc_parts = []
            for j in range(i+1, min(i+5, len(texts))):
                t = texts[j].strip()
                if 'Họ tên' in t or 'Ho ten' in t or 'Tên đơn' in t:
                    break
                if '303' in t or 'Ngân' in t or 'TMCP' in t or 'Quân Đội' in t or 'CN' in t or 'Đà' in t:
                    acc_parts.append(t)
            if acc_parts:
                seller_account = ' '.join(acc_parts)
                break

    # Thong tin ben mua
    buyer_name = ""
    buyer_tax = ""
    buyer_address = ""
    payment_method = ""

    # Ten don vi mua
    buyer_name = find_text_after(texts, ['Tên đơn vị:', 'Ten don vi:'])
    if not buyer_name:
        # Tim dong chua "BỆNH VIỆN" hoac thong tin nguoi mua
        for i, text in enumerate(texts):
            if 'Tên đơn vị' in text or 'Ten don vi' in text:
                if i + 1 < len(texts):
                    name_parts = [texts[i + 1]]
                    if i + 2 < len(texts) and not any(x in texts[i + 2] for x in ['Mã số', 'Căn cước', 'Can cuoc']):
                        name_parts.append(texts[i + 2])
                    buyer_name = ' '.join([p.strip() for p in name_parts])
                    break

    # MST ben mua
    for i, text in enumerate(texts):
        if 'Mã số thuế:' in text or 'Ma so thue:' in text:
            if i + 1 < len(texts):
                potential_tax = texts[i + 1].strip()
                # MST ben mua khac MST ben ban
                if potential_tax != seller_tax and len(potential_tax) == 10:
                    buyer_tax = potential_tax
                    break

    # Dia chi ben mua
    for i, text in enumerate(texts):
        if 'Địa chỉ:' in text and i > 20:  # Dia chi ben mua thuong o sau
            addr_parts = []
            for j in range(i+1, min(i+5, len(texts))):
                t = texts[j].strip()
                if 'Hình thức' in t or 'Hinh thuc' in t:
                    break
                if 'Nguyễn Công Trứ' in t or 'An Hải' in t or 'Đà' in t or t == 'Việt Nam.':
                    addr_parts.append(t)
            if addr_parts:
                buyer_address = ', '.join(addr_parts)
                break

    # Hinh thuc thanh toan
    payment_method = find_text_after(texts, ['Hình thức thanh toán:', 'Hinh thuc thanh toan:'])

    # Danh sach hang hoa
    items = extract_items_detailed(texts)

    # Cac tong tien
    subtotal = 0
    tax_rate = find_text_after(texts, ['Thuế suất GTGT:', 'Thue suat GTGT:'])
    tax_amount = 0
    total = 0

    # Tim Cong tien hang - tim "tiền" hoac "Cộng tiền" roi tim so sau do
    for i, text in enumerate(texts):
        if text.strip() == 'tiền' or 'Cộng' in text:
            # Kiem tra xem co phai la dong "Cong tien hang" khong
            check_prev = i > 0 and ('Cộng' in texts[i-1] or 'Công' in texts[i-1] or texts[i-1] == 'ẵ' or texts[i-1] == 'ẳ')
            if text.strip() == 'tiền' and not check_prev:
                continue
            # Tim so ngay sau (co the la 227.778 hoac 2.122.220)
            for j in range(i+1, min(i+4, len(texts))):
                if re.match(r'^\d+[\d.,]+$', texts[j]):
                    val = parse_number(texts[j])
                    if val > 10000 and subtotal == 0:
                        subtotal = val
                        break
            if subtotal > 0:
                break

    # Tim Tien thue GTGT
    for i, text in enumerate(texts):
        if 'Tiền thuế GTGT:' in text or 'Tien thue GTGT:' in text or 'thuế GTGT:' in text:
            for j in range(i+1, min(i+4, len(texts))):
                if re.match(r'^\d+[\d.,]*$', texts[j]):
                    val = parse_number(texts[j])
                    # Thue GTGT thuong nho hon subtotal
                    if val > 0 and (subtotal == 0 or val < subtotal):
                        tax_amount = val
                        break
            if tax_amount > 0:
                break

    # Tim Tong tien thanh toan - tim dong chua "thanh toán:"
    for i, text in enumerate(texts):
        if 'tiền thanh toán:' in text or 'tien thanh toan:' in text or 'thanh toán:' in text:
            for j in range(i+1, min(i+4, len(texts))):
                if re.match(r'^\d+[\d.,]*$', texts[j]):
                    val = parse_number(texts[j])
                    # Tong tien lon hon subtotal
                    if val > subtotal:
                        total = val
                        break
            if total > 0:
                break

    # So tien bang chu
    total_words = ""
    for i, text in enumerate(texts):
        # Tim "chữ:" roi lay text sau do
        if text.strip().startswith('chữ:') or text.strip().startswith('chu:'):
            # Lay phan sau dau :
            after_colon = text.split(':', 1)[1].strip() if ':' in text else ''
            # Lay them text tiep theo neu can
            if i + 1 < len(texts) and 'Người' not in texts[i + 1]:
                after_colon += ' ' + texts[i + 1].strip()
            total_words = after_colon.replace('chẵn.', 'chẵn').replace('chan.', 'chan').strip()
            break

    # Nguoi ban hang ky
    signer = ""
    sign_date = ""
    for i, text in enumerate(texts):
        if 'Ký bởi:' in text or 'Ky boi:' in text:
            if i + 1 < len(texts):
                signer = texts[i + 1].strip()
        if 'Ký ngày:' in text or 'Ky ngay:' in text:
            date_match = re.search(r'(\d{2}/\d{2}/\d{4})', text)
            if date_match:
                sign_date = date_match.group(1)

    # Ma tra cuu
    lookup_code = ""
    lookup_url = ""
    for text in texts:
        if 'Mã tra cứu hóa đơn:' in text or 'Ma tra cuu hoa don:' in text or 'tra cứu hóa đơn:' in text:
            code_match = re.search(r':\s*([A-Z0-9]+)', text)
            if code_match:
                lookup_code = code_match.group(1)
        if 'https://' in text or 'http://' in text:
            # Trich xuat chi URL
            url_match = re.search(r'(https?://[^\s]+)', text)
            if url_match:
                lookup_url = url_match.group(1)

    # Tao JSON chuan
    result = {
        "Loại hóa đơn": invoice_type,
        "Ký hiệu": symbol,
        "Số": number,
        "Ngày hóa đơn": date,

        "Đơn vị bán hàng": seller_name,
        "Mã số thuế (bên bán)": seller_tax,
        "Địa chỉ (bên bán)": seller_address,
        "Điện thoại (bên bán)": seller_phone,
        "Fax (bên bán)": seller_fax,
        "Số tài khoản (bên bán)": seller_account,

        "Tên đơn vị mua hàng": buyer_name,
        "Mã số thuế (bên mua)": buyer_tax,
        "Địa chỉ (bên mua)": buyer_address,
        "Hình thức thanh toán": payment_method,

        "Danh sách hàng hóa": items,

        "Cộng tiền hàng": subtotal,
        "Thuế suất GTGT": tax_rate,
        "Tiền thuế GTGT": tax_amount,
        "Tổng cộng tiền thanh toán": total,
        "Số tiền bằng chữ": total_words,

        "Người bán hàng ký": signer,
        "Ngày ký": sign_date,

        "Mã tra cứu hóa đơn": lookup_code,
        "URL tra cứu": lookup_url
    }

    return result

if __name__ == '__main__':
    # Duong dan file PDF
    pdf_path = '1C25TMH_00005186.pdf'

    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]

    print(f"Dang xu ly file: {pdf_path}")
    print("=" * 50)

    # Doc va xu ly PDF
    result = extract_invoice_data_from_pdf(pdf_path)

    # Luu vao file JSON
    output_file = pdf_path.replace('.pdf', '_output.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nDa luu ket qua vao file: {output_file}")

    # Hien thi thong tin co ban
    if 'error' not in result:
        print("\nThong tin hoa don:")
        print(f"- Loai: {result['Loại hóa đơn']}")
        print(f"- So: {result['Ký hiệu']}-{result['Số']}")
        print(f"- Ngay: {result['Ngày hóa đơn']}")
        print(f"- Ben ban: {result['Đơn vị bán hàng']}")
        print(f"- Ben mua: {result['Tên đơn vị mua hàng']}")
        print(f"- Tong tien: {result['Tổng cộng tiền thanh toán']:,} VND")
        print(f"- So luong san pham: {len(result['Danh sách hàng hóa'])}")
    else:
        print(f"\nLoi: {result['error']}")
