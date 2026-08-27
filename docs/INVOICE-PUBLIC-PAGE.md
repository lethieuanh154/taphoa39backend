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

## QR tĩnh `/hd/last/<machine_code>` — claim + grace + TTL
QR tĩnh in ra dán tại quầy, không đổi theo hóa đơn. Rủi ro: khách A quét chậm, máy đã bán cho khách B → A xem nhầm hóa đơn của B.

Xử lý bằng con trỏ `pos_machines/{machineCode}`:

```
{ machineCode, lastPublicToken, updatedAt (server time), claimed: bool }
```

- `FirestoreInvoiceService.set_machine_pointer()` ghi con trỏ trong background task của `POST /api/firebase/add_invoice` (không làm chậm checkout).
- `FirestoreInvoiceService.claim_machine_pointer()` chạy trong Firestore transaction: trả token khi `claimed == False` **và** `now - updatedAt <= 300s`, rồi set `claimed = True` + `claimedAt = now`.
- **Grace window 120s** (`MACHINE_POINTER_CLAIM_GRACE_SECONDS`): sau lần claim đầu, vẫn trả **cùng token** cho các lần quét trong 120s tiếp theo, bỏ qua TTL gốc vì lần claim trước đã hợp lệ.

  Không có grace thì tính năng gần như không dùng được: Zalo/Messenger tự gọi GET để preview link ngay khi camera nhận ra URL, nên lần claim duy nhất bị tiêu **trước khi khách kịp bấm vào**. Nhân viên quét thử, hoặc khách bấm back rồi quét lại, cũng tiêu mất. Đã gặp thật trên production.

  Doc ghi từ trước khi có grace (`claimed: True`, không có `claimedAt`) được coi là hết grace → trả `claimed`.
- Quét xong redirect sang `/hd/<token>` → khách reload/bookmark vẫn xem được, vì URL đã là link token cố định.
- Lý do phải có `machineCode`: máy 1 và máy 2 dùng 2 QR tĩnh khác nhau, không lẫn hóa đơn của nhau.

Thông báo cho khách theo `reason`: `claimed` (đã có người tải, quá grace), `expired` (quá 5 phút), `not_found` (chưa có hóa đơn).

Khi khách quét hụt, lối thoát là nhân viên mở trang Hóa đơn trong BanHang → bấm nút QR của đúng hóa đơn đó. QR token trực tiếp không có TTL và không giới hạn số lần.

## Tải ảnh `.png`
Backend **không** render ảnh. Trang tự vẽ `#bill` thành PNG ở client: clone DOM → nhúng vào `<svg><foreignObject>` → `<img>` → `<canvas>` (scale 2×) → `toDataURL('image/png')`. Không cần thư viện ngoài, không cần headless Chrome, không lưu file trên server. Nếu trình duyệt chặn, nút báo khách chụp màn hình.

## Nginx BẮT BUỘC cấu hình — dễ quên nhất

Flask nhận `/hd/*` đúng, nhưng nginx đứng trước mới quyết định request có tới được Flask hay không.

- `api.songminhcr.com` proxy `location /` sang `127.0.0.1:8001` → `/hd/*` chạy sẵn, không cần làm gì.
- `songminhcr.com` có `root /apps/taphoa39dathang` + `location / { try_files $uri $uri/ /index.html; }` và chỉ proxy `/api/`, `/socket.io/` → **`/hd/*` bị Angular DatHang nuốt, trả index.html kèm HTTP 200**. Triệu chứng: trang trắng / trang đặt hàng thay vì hóa đơn.

Muốn dùng URL `songminhcr.com/hd/...` phải thêm vào server block của `songminhcr.com`:

```nginx
location /hd/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

`proxy_pass` không có `/` ở cuối để giữ nguyên path. Kiểm tra bằng `curl -I`: đúng thì có `Content-Type: text/html; charset=utf-8` và **không** có `ETag`/`Last-Modified` (hai header đó là dấu hiệu nginx đang serve file tĩnh).

## `POST /api/firebase/invoices/<id>/public-token`

Cấp `publicToken` cho hóa đơn tạo **trước** tính năng này, gọi khi user bấm nút QR trong trang Hóa đơn (không backfill cả collection).

Body `{"publicToken": "<32 hex>"}`. Idempotent: hóa đơn đã có token thì trả token cũ kèm `created: false`, không ghi đè.

**Cố ý không dùng `PUT /invoices/<id>`**: route đó đọc lại hóa đơn, reverse toàn bộ summary rồi apply lại và tính `apply_invoice_delta` cho customer — quá nhiều rủi ro lệch báo cáo chỉ để thêm một field. Endpoint này chỉ ghi đúng một field.

Nằm dưới `/api/` nên **bị** admin gate — đúng ý đồ, chỉ nhân viên đã đăng nhập mới cấp được token.

## Tổng tiền — `totalPrice` đã trừ chiết khấu
`createInvoiceForCheckout()` ở FE lưu `totalPrice = tiền hàng - discountAmount`, nhưng **vẫn giữ nguyên** `discountAmount` trong doc. Nên trang public phải lấy:

```
Tổng thanh toán = totalPrice          (KHÔNG trừ discountAmount lần nữa)
Tổng tiền hàng  = totalPrice + discountAmount
```

Tính `totalPrice - discountAmount` là trừ chiết khấu hai lần, khách thấy số tiền thấp hơn thực tế.

## Favicon
`_FAVICON` là logo Song Minh 64×64 (1.8 KB) nhúng thẳng vào HTML dưới dạng data URI, khai báo trong `<head>` của **cả** trang hóa đơn lẫn trang báo lỗi.

Không khai báo thì trình duyệt tự xin `/favicon.ico` của domain, và nginx trả favicon mặc định của app DatHang (logo Angular) — khách thấy logo Angular trên tab hóa đơn.

Dùng data URI thay vì link tới file để trang hiển thị đúng trên cả `songminhcr.com` và `api.songminhcr.com` (backend không serve thư mục static của DatHang).

Nguồn: `TapHoa39DatHang/public/iconSongMinh.png`, resize 64×64 + quantize 128 màu.

## Biến môi trường
| Biến | Mặc định | Dùng cho |
|---|---|---|
| `SHOP_NAME` | `Tap Hoa Song Minh` | Tiêu đề trên hóa đơn |
| `SHOP_SITE` | `https://songminhcr.com/` | Dòng chân trang |

## Firestore
- Collection `invoices`: thêm `publicToken`, `machineCode`, `paidAt` (do FE ghi).
- Collection `pos_machines`: doc id = mã máy, chỉ backend ghi.
- Query `publicToken == <token>` dùng single-field index tự động, không cần composite index.
