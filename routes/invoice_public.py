from __future__ import annotations

import html
import os
import re
from datetime import datetime

from flask import Blueprint, Response

SHOP_NAME = os.getenv("SHOP_NAME", "Song Minh")
SHOP_SITE = os.getenv("SHOP_SITE", "https://songminhcr.com/")

_HEX = set("0123456789abcdef")


# Favicon nhung thang vao HTML: khong khai bao thi trinh duyet tu xin /favicon.ico
# cua domain, va nginx tra favicon mac dinh cua app DatHang (logo Angular).
# Data URI de dung duoc tren ca songminhcr.com lan api.songminhcr.com.
_FAVICON = "data:image/png;base64," + (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAMAAACdt4HsAAABgFBMVEX9/fyNt0hWpcriqi4hbDIXZin+/v7+/v3t6tHn6und"
    "pi7U5u8mcTeGsTzR1tdmq8sZI0TktlHs16rY5M9MnsWlxG/H2al4s9Dv8dwPGDqWxdqzyo2905MuN1SmqbaUmKjpy4dxdoqt"
    "xa+y1OTcrUVNhlaFu9XmxHdpmHI2d0UjLEzHydHR3eSsx9WIq0mEiZqZu2JOVW6IqI4RXCJbkmfT4raBqzjjvGR+qoyVtJe4"
    "u8VViWLC1p2kvnRDSmWdwGa80sPgr0OrtrZ2oXZ8ozU7Q2ACCi5cY3ns05lobYJGfUy60LOWt6Hfs09iaH5GeSN8gpJ2nVr4"
    "47qYx+CozuDdu23isD8VH0Ly8tikuYSLkJ6Kj6B2nC57h3hKmL9fjT5AdRueobM5QlwbcSwPWh4AAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABvJ4++AAAA"
    "gHRSTlP+/v/+//8mFP3+/v///v////76/v/+/f/+//////////7////+//////////////////////7//v//////////////"
    "////////////////////////////FP///////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAK2ghuQAAASwSURB"
    "VHjapVdnY6M4FBQGbmkGDNhAsLFxL3FLcXpvm7L9tlyv//83nESVADvO3vuQUDyj0bz3JAR++J8BVoVegaFz4LuCq5YpiprN"
    "zsownMpLWSpUsUglgW7Ku+vDqxSOTkgq68F38+ABx1oUTj68CAP+KT9rRjmDLy6QA+VqFdm6WDwjIiO/SJWPOQvwIgw/OVT5"
    "JfgiVbWA2DKVgmEYhYL5CZI4s+X4WXr8Y/iwZRawUFrAquaXXTM1/yKCtxCmQIQp5o9+BSokHhkupsBBtPLwHyqAVB/qFFvd"
    "gpFm2MjiD/5IFUBSuJAircPIMOh/OqQArF7ETVEcK89o+PCOO17k4/3gxW5Kw4/E++a7DpECK8ekcUoDkYsHpo/N4Cw/TaJJ"
    "mKngAlj2KiE4i8bP6NgwltjQYdl9KybQw66cTCYzfRVDPAmZYSBBEateP04WM+oa9V6lks/QjWuAldiriCAxgJuUKyfXlj65"
    "ri7REEnoQ4KdaApYu1cXM8d5PClP9CWzCF3gB5CgA/AClmUe/Zv8OnF05+SE8MHMJEJmJImVAFrFqWDFmtqqOvKXx+qus5su"
    "KqwoN8MkSpL0j15FJgTrPz8aze9G9Xrdrf/105bL19Gz9+OoHtJzeEIEbJODBE48jKsOayiGzd/qP9/KAHi39WxNmlESIMEO"
    "cHAHZTv+Paiph+Dy63CUscEMCLZYiWEYCS6IFGa36iZi4PXwpsYnRR16aHZRIvktFuIZtgkofLX0bK9+6Jt0+vb0F28+rWEv"
    "/dZUFMVf3fSQoAN0Bze7fjNU1ZoLJyPfq0P+bh6/0YBo+PhgedT7TMBwnum/zcO3Ng+HntouqE3jCm1rMJWKEq2v+tEgINjJ"
    "aWHeHv89BTwPePUyJhDacLH2qyHw4OjBJ5DYRwLret79fe3UtWV0N1I34xkIbSuspqCdOoEChh0QBFN7Pp97/OmNf3cY8KDo"
    "CRdcmMmgkPrbTBDsPk4wUv28eUH6+VMvnADYo0ufrU9+TwXFuRURkD7y6vtNGXaVKKOIi4DTSvQX4bVoJDuMzMYEEo/nUa2p"
    "tg37Sv06tOMkNgSapoWeiDUTOIoYUFfjGtyRHIR7GDFzb2gUJd9FRYzWVCZmwHPpqV6kJRHg4+k3votm9HSAMfQTgqFqBxpr"
    "9u2YEEC3UTUnG9xBbCOhYRopcId3UQoDPC2ArhFbQEiADEeJCekLTUgIiK0lccGvaX7Z12s7xEMTTfIzoZ9MAuXi8Rm8nwWF"
    "eDkgNEhb+ko83QNKan/WGYKB6TT11EQ4IcELmmgoKX6ZxRmgiH5Txnfwjxgeerjxe+ZTS2ZIBpbB56HheLoBjJzPJHmwzTDk"
    "PPqXetTCOB4uKEquzZ1/CRESVCGhyuRKOBw6AJS8THMaeJIIJ+B+8XAeNiCNp2Cc/635+jMA+8w2G8U2c4CefiHhsAbAkm9V"
    "6FQDgPP9owEavdN/kgGXHp2mL1adGDRB6GmcxfvBfWyUMnC6tPrEYe0JgkCXUNDo6qX4TMJTIfTWOXQ1hGUccEta78zZa+dR"
    "IIfXPrZqe21Sh1BqWC89+2qN3t4esvOCLjW+8wDNcxoMbiX61Vrx7duyN/8BR4R2g0lFumgAAAAASUVORK5CYII="
)


def _to_float(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(v) -> str:
    """Dinh dang tien VND: 12500 -> 12.500"""
    return f"{int(round(_to_float(v))):,}".replace(",", ".")


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _format_date(raw) -> str:
    """Doi chuoi ISO thanh dd/MM/yyyy HH:mm. Tra lai nguyen ban neu khong parse duoc."""
    if not raw:
        return ""
    text = str(raw)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text


def _line_items(invoice: dict) -> list:
    """Chi lay field can hien thi. Khong bao gio lo Cost, OnHandNV hay du lieu noi bo."""
    items = []
    for item in invoice.get("cartItems") or []:
        product = item.get("product") or {}
        quantity = _to_float(item.get("quantity"))
        base_price = _to_float(product.get("BasePrice"))
        sale_off = _to_float(item.get("unitPriceSaleOff"))
        is_gift = bool(item.get("isGift"))
        unit_price = 0.0 if is_gift else max(base_price - sale_off, 0.0)

        attributes = product.get("ProductAttributes") or []
        variant = ""
        if attributes and isinstance(attributes[0], dict):
            variant = attributes[0].get("Value") or ""

        items.append({
            "name": product.get("Name") or "",
            "variant": variant,
            "unit": product.get("Unit") or "",
            "quantity": quantity,
            "base_price": base_price,
            "unit_price": unit_price,
            "discounted": (not is_gift) and sale_off > 0,
            "is_gift": is_gift,
            "amount": unit_price * quantity,
        })
    return items


_MESSAGE_CSS = """
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
         background:#f2f3f5; color:#1f2328; padding:24px; }
  .card { background:#fff; border-radius:14px; padding:32px 24px; max-width:420px; text-align:center;
          box-shadow:0 2px 12px rgba(0,0,0,.08); }
  h1 { font-size:19px; margin:0 0 10px; }
  p { font-size:14px; line-height:1.6; color:#5c6470; margin:0; }
"""

_BILL_CSS = """
  * { box-sizing:border-box; }
  body { margin:0; padding:16px 12px; background:#f2f3f5; color:#000;
         font-family:Arial,Helvetica,sans-serif; }
  .wrap { max-width:360px; margin:0 auto; }
  #bill { background:#fff; padding:14px 12px 18px; font-size:11px; line-height:1.45;
          box-shadow:0 2px 12px rgba(0,0,0,.10); }
  #bill table { width:100%; border-collapse:collapse; }
  #bill td, #bill th { word-wrap:break-word; }
  .title { text-align:center; font-weight:bold; font-size:12px; padding:6px 0 0; }
  .head-line { text-align:center; font-size:11px; }
  .party { margin:10px 0 15px; font-size:11px; }
  .items { table-layout:fixed; }
  .items td { padding:3px; }
  .items thead td { border-top:1px solid #000; border-bottom:1px solid #000; font-weight:bold; }
  .items .c-qty, .items .c-unit { text-align:center; }
  .items .c-amount { text-align:right; }
  .items .r-name td { padding-top:3px; }
  .items .r-figures td { border-bottom:1px dashed #000; }
  .sums { table-layout:fixed; margin-top:0; }
  .sums td { padding:3px; }
  .sums .lbl { font-weight:bold; text-align:right; white-space:nowrap; font-size:12px; }
  .sums .val { font-weight:bold; text-align:right; font-size:14px; }
  .note { text-align:center; font-size:10px; font-style:italic; }
  .promo { text-align:center; font-size:10px; }
  .promo b { font-weight:bold; }
  s { color:#000; }
  .actions { margin-top:14px; }
  button { width:100%; padding:13px; font-size:15px; font-weight:600; color:#fff; background:#1f6feb;
           border:0; border-radius:10px; cursor:pointer; font-family:inherit; }
  button:disabled { opacity:.6; cursor:default; }
  .hint { text-align:center; font-size:11.5px; color:#6b7280; margin-top:9px;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }
"""

# Ve lai bill thanh anh bang SVG foreignObject -> canvas. Khong can thu vien ngoai,
# khong can backend render anh.
_SAVE_SCRIPT = """
(function () {
  var btn = document.getElementById('save');
  var bill = document.getElementById('bill');
  var fileName = btn.getAttribute('data-filename');
  var label = btn.textContent;

  btn.addEventListener('click', function () {
    btn.disabled = true;
    btn.textContent = 'Dang tao anh...';

    var scale = 2;
    var width = bill.offsetWidth;
    var height = bill.offsetHeight;
    var styles = document.getElementById('bill-style').textContent;
    var clone = bill.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
    clone.style.boxShadow = 'none';

    var svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + height + '">' +
      '<foreignObject width="100%" height="100%">' +
      '<div xmlns="http://www.w3.org/1999/xhtml"><style>' + styles + '</style>' +
      new XMLSerializer().serializeToString(clone) +
      '</div></foreignObject></svg>';

    var fail = function () {
      btn.disabled = false;
      btn.textContent = 'Khong tao duoc anh - hay chup man hinh';
    };

    var img = new Image();
    img.onload = function () {
      try {
        var canvas = document.createElement('canvas');
        canvas.width = width * scale;
        canvas.height = height * scale;
        var ctx = canvas.getContext('2d');
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.setTransform(scale, 0, 0, scale, 0, 0);
        ctx.drawImage(img, 0, 0);

        var link = document.createElement('a');
        link.download = fileName;
        link.href = canvas.toDataURL('image/png');
        link.click();

        btn.disabled = false;
        btn.textContent = label;
      } catch (err) {
        fail();
      }
    };
    img.onerror = fail;
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  });
})();
"""


def _render_message(title: str, message: str, status: int) -> Response:
    body = (
        '<!doctype html>\n<html lang="vi"><head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        f'<link rel="icon" type="image/png" href="{_FAVICON}">\n'
        f"<title>{_esc(title)}</title>\n"
        f"<style>{_MESSAGE_CSS}</style></head>\n"
        f'<body><div class="card"><h1>{_esc(title)}</h1><p>{_esc(message)}</p></div></body></html>'
    )
    response = Response(body, status=status, mimetype="text/html")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _vietnamese_date(raw) -> str:
    """Ngay dd thang MM nam yyyy - dung dinh dang cua bill in nhiet."""
    if not raw:
        return ""
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return str(raw)
    return f"Ngày {d.day:02d} tháng {d.month:02d} năm {d.year}"


def _price_cell(item: dict) -> str:
    """Cot don gia: gach ngang gia goc khi hang tang hoac co giam gia."""
    if item["is_gift"]:
        return f'<s>{_money(item["base_price"])}</s>'
    if item["discounted"]:
        return f'<s>{_money(item["base_price"])}</s>&nbsp; {_money(item["unit_price"])}'
    return _money(item["unit_price"])


_MACHINE_SUFFIX = re.compile(r"^(HD\d+)-[A-Za-z0-9]{1,6}$")


def _display_invoice_id(raw) -> str:
    """Bo hau to ma may cua hoa don cu: HD1756...-M1 -> HD1756...

    Id van giu nguyen trong Firestore, chi doi cach hien thi. Hoa don moi
    khong con hau to nay nua.
    """
    text = str(raw or "")
    match = _MACHINE_SUFFIX.match(text)
    return match.group(1) if match else text


def _render_invoice(invoice: dict) -> Response:
    items = _line_items(invoice)
    # createInvoiceForCheckout() o FE luu totalPrice DA TRU chiet khau, nhung van
    # giu nguyen discountAmount. Tru them lan nua la sai so tien khach phai tra.
    discount = _to_float(invoice.get("discountAmount"))
    final_total = _to_float(invoice.get("totalPrice"))
    gross_total = final_total + discount

    customer = invoice.get("customer") or {}
    customer_name = _esc(customer.get("Name") or "Khách lẻ")
    customer_phone = _esc(customer.get("ContactNumber") or "")
    invoice_id = _esc(_display_invoice_id(invoice.get("id")))
    date_text = _esc(_vietnamese_date(invoice.get("paidAt") or invoice.get("createdDate")))

    rows = []
    for item in items:
        name = _esc(item["name"])
        if item["variant"]:
            name += " - " + _esc(item["variant"])
        amount = "0" if item["is_gift"] else _money(item["amount"])

        rows.append(
            f'<tr class="r-name"><td colspan="4">{name}</td></tr>'
            '<tr class="r-figures">'
            f'<td>{_price_cell(item)}</td>'
            f'<td class="c-qty">{item["quantity"]:g}</td>'
            f'<td class="c-unit">{_esc(item["unit"])}</td>'
            f'<td class="c-amount">{amount}</td>'
            '</tr>'
        )

    body = f"""<!doctype html>
<html lang="vi"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<link rel="icon" type="image/png" href="{_FAVICON}">
<title>Hóa đơn {invoice_id}</title>
<style id="bill-style">{_BILL_CSS}</style></head>
<body>
<div class="wrap">
  <div id="bill">
    <div class="title">HÓA ĐƠN BÁN HÀNG</div>
    <div class="head-line">Số HĐ: {invoice_id}</div>
    <div class="head-line">{date_text}</div>

    <table class="party"><tbody>
      <tr><td>Khách hàng: {customer_name}</td></tr>
      <tr><td>SĐT: {customer_phone}</td></tr>
    </tbody></table>

    <table class="items" cellpadding="3">
      <colgroup>
        <col style="width:40%"><col style="width:10%">
        <col style="width:25%"><col style="width:25%">
      </colgroup>
      <thead><tr>
        <td>Đơn giá</td>
        <td class="c-qty">SL</td>
        <td class="c-unit">ĐVT</td>
        <td class="c-amount">Thành tiền</td>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>

    <table class="sums" cellpadding="3"><tbody>
      <tr><td colspan="3" class="lbl">Tổng tiền hàng:</td><td class="val">{_money(gross_total)}</td></tr>
      <tr><td colspan="3" class="lbl">Chiết khấu:</td><td class="val">{_money(discount)}</td></tr>
      <tr><td colspan="3" class="lbl">Tổng thanh toán:</td><td class="val">{_money(final_total)}</td></tr>
      <tr><td colspan="4" class="note">
        <u>*Lưu ý:</u><br><br>
        Quý khách vui lòng không đổi trả khi đã thanh toán.<br>Xin cảm ơn!
      </td></tr>
      <tr><td colspan="4" class="promo">
        Hãy đăng ký thành viên và đặt hàng online tại:<br><b>{_esc(SHOP_SITE)}</b>
      </td></tr>
    </tbody></table>
  </div>

  <div class="actions">
    <button id="save" type="button" data-filename="hoa-don-{invoice_id}.png">Lưu hóa đơn về máy (.png)</button>
  </div>
  <div class="hint">Không lưu được? Bạn có thể chụp màn hình để giữ hóa đơn.</div>
</div>
<script>{_SAVE_SCRIPT}</script>
</body></html>"""

    response = Response(body, mimetype="text/html")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "private, no-store"
    return response


def create_invoice_public_bp(invoice_service) -> Blueprint:
    """Trang hoa don dien tu cho khach hang.

    Khong nam duoi /api/ nen khong bi admin_auth gate - dung y do: khach hang khong
    co tai khoan Google cua cua hang. Token ngau nhien la lop bao ve duy nhat, vi vay
    trang chi render field an toan (khong Cost, khong TotalPoint) va luon noindex.
    """
    bp = Blueprint("invoice_public", __name__)

    @bp.route("/hd/<token>", methods=["GET"])
    def view_invoice(token: str):
        normalized = (token or "").lower()
        if len(normalized) < 16 or not set(normalized) <= _HEX:
            return _render_message(
                "Liên kết không hợp lệ",
                "Đường dẫn hóa đơn không đúng định dạng.",
                404,
            )

        try:
            invoice = invoice_service.get_invoice_by_public_token(normalized)
        except Exception as exc:
            print(f"[invoice_public] lookup failed: {exc}")
            return _render_message(
                "Không tải được hóa đơn",
                "Hệ thống đang bận. Vui lòng thử lại sau ít phút.",
                503,
            )

        if not invoice:
            return _render_message(
                "Không tìm thấy hóa đơn",
                "Hóa đơn không tồn tại hoặc liên kết đã bị thay đổi.",
                404,
            )

        return _render_invoice(invoice)

    return bp
