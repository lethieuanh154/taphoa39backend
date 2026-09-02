# GHI CHÚ TẶNG QUÀ (`GiftNotes`)

Nhân viên ghi chú việc tặng quà cho từng khách hàng từ **TapHoa39BanHang `/customers-page`**; khách hàng xem lại trong **TapHoa39DatHang** (profile → "Lịch sử tặng quà").

## Lưu trữ
Field `GiftNotes` (array) trong doc `customers/<Id>` — Firestore `FIREBASE_SERVICE_ACCOUNT_CUSTOMER`.

```json
{ "id": "hex32", "text": "Tặng 1 thùng bia dịp Tết 2026", "createdAt": "2026-09-02T03:12:44+00:00", "createdBy": "nv@songminh.com" }
```

- Ghi/xóa qua `customer_service.update_customer()` → `doc_ref.update()` (merge), không đụng field khác.
- Đọc doc trực tiếp theo `document(str(Id))`, **không** dùng `read_all_customers()` (tránh full scan).
- `text` cắt tối đa 500 ký tự. Danh sách trả về luôn sort `createdAt` giảm dần.

## Endpoints ADMIN — `routes/firebase_customers.py` (gate `X-Id-Token`)

| Method | Path | Body / Trả về |
|---|---|---|
| GET | `/api/firebase/customers/<customer_id>/notes` | → `{ status, notes: [...] }` |
| POST | `/api/firebase/customers/<customer_id>/notes` | `{ text, createdBy? }` → `{ status, note, notes }` |
| DELETE | `/api/firebase/customers/<customer_id>/notes/<note_id>` | → `{ status, notes }` |

POST/DELETE phát `broadcast_customer_updates()` → WS `customer_updated` / `customers_updated` (namespace `/api/websocket/customers`).
404 khi không có doc khách hàng, hoặc `note_id` không tồn tại (DELETE).

## Endpoint KHÁCH HÀNG — `routes/chat_routes.py` (prefix `/api/chat/`, không qua admin gate)

`POST /api/chat/customer-notes` — body `{ identity, token }` (hoặc `{ identity, password }`), trả `{ notes: [{ id, text, createdAt }] }`.
Query Firestore theo `Code` rồi `ContactNumber` (limit 1), **không lộ `createdBy`**.

| Tình huống | Trả về |
|---|---|
| Không có `identity` | 400 |
| Không tìm thấy khách | 404 `{ notes: [] }` |
| Không có token/password hợp lệ | **401** `{ notes: [], message: "Vui lòng đăng nhập lại..." }` |
| OK | 200 `{ notes: [...] }` |

### Token phiên khách hàng
Không dùng được nếu chỉ biết SĐT — phải qua đúng luồng đăng nhập.

- `POST /api/chat/verify-identity` khi `verified: true` trả thêm `token` = `base64url("<Code>|<exp>").<hmac-sha256 32 hex>`, TTL 30 ngày.
- FE DatHang lưu `localStorage.sm_customer_token`, gửi kèm mỗi lần đọc note; xoá khi logout.
- `customer-notes` verify chữ ký + hạn + subject phải khớp `Code` của khách vừa query được.
- Secret: env `CUSTOMER_TOKEN_SECRET`, fallback `GOOGLE_CLIENT_SECRET` → `ZALO_APP_SECRET`. **Không có secret nào → mọi token invalid → 401** (fail-closed). Đổi secret = vô hiệu toàn bộ token đang phát.
- Khách **có** mật khẩu: chỉ lấy được token khi nhập đúng mật khẩu (đúng bằng độ chặt của login). Khách **chưa đặt** mật khẩu: verify-identity vẫn cấp token bằng SĐT — muốn chặt hơn thì bắt khách đặt mật khẩu.

## Frontend
- BanHang: cột "Ghi chú" trong `customers-page` → `customer-notes-dialog.component.*` (thêm/xóa/xem). Service: `getCustomerNotes` / `addCustomerNote` / `deleteCustomerNote` (mirror sang Management theo quy tắc mirror service).
- DatHang: `components/profile-bubble/` — nút "Lịch sử tặng quà".
