from __future__ import annotations

import html
import os
from datetime import datetime

from flask import Blueprint, Response, redirect

SHOP_NAME = os.getenv("SHOP_NAME", "Song Minh")
SHOP_SITE = os.getenv("SHOP_SITE", "https://songminhcr.com/")

_HEX = set("0123456789abcdef")


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
  body { margin:0; padding:16px; background:#f2f3f5; color:#1f2328;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }
  .wrap { max-width:420px; margin:0 auto; }
  #bill { background:#fff; border-radius:14px; padding:22px 18px; box-shadow:0 2px 12px rgba(0,0,0,.08); }
  .shop { text-align:center; font-size:17px; font-weight:700; letter-spacing:.3px; }
  .head { text-align:center; font-size:12px; color:#6b7280; margin-top:4px; }
  .meta { margin:18px 0 12px; font-size:13px; line-height:1.7; }
  .meta b { font-weight:600; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.4px;
       color:#6b7280; border-bottom:1px solid #e5e7eb; padding:8px 0; font-weight:600; }
  th.c-amount, td.c-amount { text-align:right; white-space:nowrap; }
  td { padding:9px 0; border-bottom:1px dashed #e5e7eb; vertical-align:top; }
  td.c-name { padding-right:10px; }
  .c-sub { font-size:11.5px; color:#6b7280; margin-top:3px; }
  .tag { background:#eef7ee; color:#2f7a34; border-radius:4px; padding:1px 5px; font-size:10.5px; }
  .sums { margin-top:14px; font-size:13px; }
  .sum-row { display:flex; justify-content:space-between; padding:5px 0; color:#4b5563; }
  .sum-total { display:flex; justify-content:space-between; padding:11px 0 0; margin-top:6px;
               border-top:1px solid #e5e7eb; font-size:16px; font-weight:700; }
  .foot { text-align:center; font-size:11.5px; color:#6b7280; margin-top:18px; line-height:1.7; }
  .actions { margin-top:14px; }
  button { width:100%; padding:13px; font-size:15px; font-weight:600; color:#fff; background:#1f6feb;
           border:0; border-radius:10px; cursor:pointer; font-family:inherit; }
  button:disabled { opacity:.6; cursor:default; }
  .hint { text-align:center; font-size:11.5px; color:#6b7280; margin-top:9px; }
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
        f"<title>{_esc(title)}</title>\n"
        f"<style>{_MESSAGE_CSS}</style></head>\n"
        f'<body><div class="card"><h1>{_esc(title)}</h1><p>{_esc(message)}</p></div></body></html>'
    )
    response = Response(body, status=status, mimetype="text/html")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _render_invoice(invoice: dict) -> Response:
    items = _line_items(invoice)
    total_price = _to_float(invoice.get("totalPrice"))
    discount = _to_float(invoice.get("discountAmount"))
    final_total = total_price - discount

    customer = invoice.get("customer") or {}
    customer_name = customer.get("Name") or "Khách lẻ"
    created = _format_date(invoice.get("paidAt") or invoice.get("createdDate"))
    invoice_id = _esc(invoice.get("id"))

    rows = []
    for item in items:
        if item["is_gift"]:
            price_html = f'<s>{_money(item["base_price"])}</s> <span class="tag">Quà tặng</span>'
        elif item["discounted"]:
            price_html = f'<s>{_money(item["base_price"])}</s> {_money(item["unit_price"])}'
        else:
            price_html = _money(item["unit_price"])

        name = _esc(item["name"])
        if item["variant"]:
            name += " - " + _esc(item["variant"])
        qty_text = f'{item["quantity"]:g}'

        rows.append(
            "<tr>"
            f'<td class="c-name">{name}'
            f'<div class="c-sub">{price_html} &times; {qty_text} {_esc(item["unit"])}</div></td>'
            f'<td class="c-amount">{_money(item["amount"])}</td>'
            "</tr>"
        )

    discount_row = ""
    if discount > 0:
        discount_row = (
            f'<div class="sum-row"><span>Chiết khấu</span><span>-{_money(discount)}</span></div>'
        )

    body = (
        '<!doctype html>\n<html lang="vi"><head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        f"<title>Hóa đơn {invoice_id}</title>\n"
        f'<style id="bill-style">{_BILL_CSS}</style></head>\n'
        '<body>\n<div class="wrap">\n'
        '  <div id="bill">\n'
        f'    <div class="shop">{_esc(SHOP_NAME)}</div>\n'
        '    <div class="head">HÓA ĐƠN BÁN HÀNG</div>\n'
        '    <div class="meta">\n'
        f"      <div>Số HĐ: <b>{invoice_id}</b></div>\n"
        f"      <div>Thời gian: <b>{_esc(created)}</b></div>\n"
        f"      <div>Khách hàng: <b>{_esc(customer_name)}</b></div>\n"
        "    </div>\n"
        "    <table>\n"
        '      <thead><tr><th>Mặt hàng</th><th class="c-amount">Thành tiền</th></tr></thead>\n'
        f"      <tbody>{''.join(rows)}</tbody>\n"
        "    </table>\n"
        '    <div class="sums">\n'
        f'      <div class="sum-row"><span>Tổng tiền hàng</span><span>{_money(total_price)}</span></div>\n'
        f"      {discount_row}\n"
        f'      <div class="sum-total"><span>Tổng thanh toán</span><span>{_money(final_total)}</span></div>\n'
        "    </div>\n"
        '    <div class="foot">\n'
        "      Quý khách vui lòng không đổi trả khi đã thanh toán. Xin cảm ơn!<br>\n"
        f"      Đặt hàng online tại {_esc(SHOP_SITE)}\n"
        "    </div>\n"
        "  </div>\n"
        f'  <div class="actions"><button id="save" type="button" data-filename="hoa-don-{invoice_id}.png">'
        "Lưu hóa đơn về máy (.png)</button></div>\n"
        '  <div class="hint">Không lưu được? Bạn có thể chụp màn hình để giữ hóa đơn.</div>\n'
        "</div>\n"
        f"<script>{_SAVE_SCRIPT}</script>\n"
        "</body></html>"
    )

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

    @bp.route("/hd/last/<machine_code>", methods=["GET"])
    def claim_latest_invoice(machine_code: str):
        """QR tinh dan tai quay: tra hoa don moi nhat cua may, mot lan duy nhat."""
        try:
            token, reason = invoice_service.claim_machine_pointer(machine_code)
        except Exception as exc:
            print(f"[invoice_public] claim pointer failed for {machine_code}: {exc}")
            return _render_message(
                "Không tải được hóa đơn",
                "Hệ thống đang bận. Vui lòng nhờ nhân viên hỗ trợ.",
                503,
            )

        if token:
            return redirect(f"/hd/{token}", code=302)

        if reason == "claimed":
            message = "Hóa đơn này đã được tải trên một thiết bị khác. Vui lòng nhờ nhân viên hỗ trợ."
        elif reason == "expired":
            message = "Mã đã hết hạn. Vui lòng quét lại ngay sau khi thanh toán."
        else:
            message = "Chưa có hóa đơn nào vừa được thanh toán trên máy này."
        return _render_message("Không tìm thấy hóa đơn", message, 404)

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
