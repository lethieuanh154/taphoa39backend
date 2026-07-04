# ADMIN-AUTH — bảo vệ endpoint quản trị `/api/*`

Fix C3: bất kỳ ai cũng gọi được `songminhcr.com/api/firebase/orders` (đọc/sửa/xóa đơn, PII). Thêm 1 lớp xác thực **Firebase ID token** cho các endpoint admin.

## Cơ chế
- `routes/admin_auth.py` → `register_admin_auth(app)` (đăng ký trong `app.py`), dùng `@app.before_request`.
- Gate MỌI `/api/*` **trừ** allowlist (public): `is_gated(method, path)`.
  - **Không gate** (public/DatHang + tự có auth riêng): `/api/public/`, `/api/chat/`, `/api/websocket/`, `/api/auth/`, `/api/gmail/`, `/api/kiotviet/categories`, `/api/kiotviet/product-images`, `/api/item/`, `/api/osrm`, `POST /api/firebase/promotions/apply`, `GET /api/firebase/orders/<id>`.
  - **Gate** (admin): mọi thứ còn lại (`/api/firebase/orders` list, `update_order`, `delete`, `customers`, `employees`, `get/products`, `/api/kiotviet/*` khác…).
- Endpoint admin cần header **`X-Id-Token: <Firebase ID token>`** (hoặc `Authorization: Bearer <token>`). Verify bằng `verify_firebase_token`.

## Fail-safe flag `ENFORCE_ADMIN_AUTH`
- **`false` (mặc định)**: chỉ **log WARN**, KHÔNG chặn → deploy backend an toàn tuyệt đối (không sập gì).
- **`true`**: chặn (401) request admin thiếu/ sai token.

## FE đã cập nhật (Management + BanHang)
- `auth.service.ts`: cache ID token qua `onIdTokenChanged` → `getCachedIdToken()`.
- `auth.interceptor.ts`: thêm header `X-Id-Token` (giữ nguyên `Authorization: <kvToken>`). Chỉ THÊM header → không đổi hành vi cũ.
- DatHang **không** đổi (ẩn danh) → tự động bị chặn khỏi endpoint admin khi enforce.

## ROLLOUT (thứ tự bắt buộc để không sập)
1. **Deploy backend** (flag mặc định `false`). Không gì bị chặn. Xem log `docker logs -f taphoa39backend`.
2. **Build + deploy Management & BanHang** (đã gửi `X-Id-Token`).
3. **Quan sát log**: sau khi 2 app deploy, các dòng `[admin-auth] WARN(off) ...` cho traffic hợp lệ phải **biến mất** (vì giờ có token). Nếu còn WARN cho path admin hợp lệ nào đó → thêm vào allowlist trong `admin_auth.py` HOẶC app đó chưa gửi token.
4. Khi log sạch → đặt **`ENFORCE_ADMIN_AUTH=true`** (env của container) + restart backend. Giờ endpoint admin yêu cầu token.
5. Kiểm tra: `curl https://songminhcr.com/api/firebase/orders` → **401**. Management/BanHang vẫn chạy bình thường.

## Còn lại (tùy chọn)
- `GET /api/firebase/orders/<id>` vẫn mở (DatHang cần cho confirm) → còn rò PII/`totalCost` 1 đơn nếu đoán được ID. Muốn kín: chuyển confirm sang endpoint public có token khách, hoặc gate luôn (đụng DatHang).
- Nên kèm lớp nginx allowlist trên `songminhcr.com` (defense-in-depth, xem lịch sử chat).
