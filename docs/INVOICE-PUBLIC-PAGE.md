# TRANG HÓA ĐƠN ĐIỆN TỬ — `/hd/*` (cho khách hàng)

File: `routes/invoice_public.py` — blueprint `create_invoice_public_bp(invoice_service)`, đăng ký trong `app.py`.

## Mục đích
Thay dần hóa đơn giấy in máy nhiệt. Khách quét QR trên màn hình máy POS → mở trang hóa đơn trên điện thoại → xem hoặc lưu ảnh `.png`.

Trang **render server-side bằng Flask**, không dùng Angular: BanHang chạy local trên máy POS nên link của BanHang (`localhost` / LAN) điện thoại khách không mở được. Backend VPS là nơi duy nhất khách truy cập được.

## Endpoints

| Method | Path | Mô tả |
|---|---|---|
| GET | `/hd/<token>` | Trang hóa đơn của một hóa đơn cụ thể (HTML) |
| GET | `/hd/last/<machine_code>` | QR tĩnh tại quầy: claim hóa đơn mới nhất của máy → 302 sang `/hd/<token>` |

**KHÔNG nằm dưới `/api/`** → `admin_auth.is_gated()` trả `False` → không bị gate. Đây là chủ đích: khách hàng không có tài khoản Google của cửa hàng, không thể bắt login.

## Bảo mật
Token ngẫu nhiên là **lớp bảo vệ duy nhất**:

- `publicToken` = 32 ký tự hex sinh bằng `crypto.getRandomValues()` ở FE (`InvoiceService.ensurePublicToken()`), lưu trong doc `invoices`.
- Invoice id (`HD<timestamp>-<machineCode>`) **đoán được** → tuyệt đối không dùng id làm link.
- Route validate token phải là hex và dài ≥ 16 trước khi query Firestore.
- Response luôn có `X-Robots-Tag: noindex, nofollow` + `Cache-Control: private, no-store`.
- `_line_items()` chỉ whitelist field hiển thị (`Name, Unit, BasePrice, ProductAttributes[0].Value`). Không bao giờ trả `Cost`, `OnHandNV`, `TotalPoint`, `kiotViet*`.
- Mọi giá trị chèn vào HTML đi qua `_esc()` (`html.escape`).

## QR tĩnh `/hd/last/<machine_code>` — one-time claim + TTL
QR tĩnh in ra dán tại quầy, không đổi theo hóa đơn. Rủi ro: khách A quét chậm, máy đã bán cho khách B → A xem nhầm hóa đơn của B.

Xử lý bằng con trỏ `pos_machines/{machineCode}`:

```
{ machineCode, lastPublicToken, updatedAt (server time), claimed: bool }
```

- `FirestoreInvoiceService.set_machine_pointer()` ghi con trỏ trong background task của `POST /api/firebase/add_invoice` (không làm chậm checkout).
- `FirestoreInvoiceService.claim_machine_pointer()` chạy trong Firestore transaction: chỉ trả token khi `claimed == False` **và** `now - updatedAt <= 300s`, rồi set `claimed = True`.
- Quét xong redirect sang `/hd/<token>` → khách reload/bookmark vẫn xem được, vì URL đã là link token cố định.
- Lý do phải có `machineCode`: máy 1 và máy 2 dùng 2 QR tĩnh khác nhau, không lẫn hóa đơn của nhau.

Thông báo cho khách theo `reason`: `claimed` (đã có người tải), `expired` (quá 5 phút), `not_found` (chưa có hóa đơn).

## Tải ảnh `.png`
Backend **không** render ảnh. Trang tự vẽ `#bill` thành PNG ở client: clone DOM → nhúng vào `<svg><foreignObject>` → `<img>` → `<canvas>` (scale 2×) → `toDataURL('image/png')`. Không cần thư viện ngoài, không cần headless Chrome, không lưu file trên server. Nếu trình duyệt chặn, nút báo khách chụp màn hình.

## Biến môi trường
| Biến | Mặc định | Dùng cho |
|---|---|---|
| `SHOP_NAME` | `Tap Hoa Song Minh` | Tiêu đề trên hóa đơn |
| `SHOP_SITE` | `https://songminhcr.com/` | Dòng chân trang |

## Firestore
- Collection `invoices`: thêm `publicToken`, `machineCode`, `paidAt` (do FE ghi).
- Collection `pos_machines`: doc id = mã máy, chỉ backend ghi.
- Query `publicToken == <token>` dùng single-field index tự động, không cần composite index.
