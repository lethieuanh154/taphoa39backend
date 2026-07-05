# PUBLIC API — `/api/public/*` (cho app DatHang)

File: `routes/firebase_public.py` — blueprint `create_firebase_public_bp(product_service, promotion_service, order_service, customer_service, socketio)`, đăng ký trong `app.py`.

## Mục đích
Che giấu dữ liệu nội bộ khỏi khách hàng (F12/Network) và chống sửa giá qua client. Route nội bộ cũ (`/api/firebase/*`) giữ nguyên cho BanHang/Management (full data).

## Endpoints

| Method | Path | Thay cho (nội bộ) |
|---|---|---|
| GET | `/api/public/products/featured?limit&offset` | `/api/firebase/products/featured` |
| GET | `/api/public/products/by-category/<id>?limit&offset` | `/api/firebase/get/products/by-category/<id>` |
| GET | `/api/public/products/search?q&limit` | `/api/firebase/products/search` |
| GET | `/api/public/promotions/active` | `/api/firebase/promotions/active` |
| GET | `/api/public/orders/<id>` | `/api/firebase/orders/<id>` (giờ đã GATE admin) |
| POST | `/api/public/add_order` | `/api/firebase/add_order` |

## Whitelist sản phẩm (`_public_product`) — đã làm gọn
GIỮ (13 field FE thực dùng): `Id, Code, Name, FullName, Image, BasePrice, Unit, Description, CategoryId, ConversionValue` (product-detail), `MasterUnitId` (GroupService grouping), `NormalizedName` (offline search có dấu), `OnHand` (đã gộp clone).
CẮT: `Cost, OldCost, PackCost, _original*, OnHandNV, CloneOnHandNV (raw), SyncChecksum, SyncTimestamp, Revision, MasterCode, kiotViet*` + `NormalizedCode, MasterProductId, isActive, isDeleted` (BE đã lọc sẵn → FE default khi thiếu).

Lọc **server-side** (không để FE tự lọc bằng field nhạy cảm): bỏ clone / KM `(km)` Cost=0 / danh mục ẩn (`1440125, 1787413`) / deleted-inactive. **Gộp `CloneOnHandNV` vào `OnHand`** (ẩn cơ chế clone, vẫn báo đúng tồn kho).

## Whitelist khuyến mãi (`_public_promotion`) — đã làm gọn
GIỮ: `id, type, name, hasGift, hasPercentDiscount, hasFixedDiscount, discountPercent, discountAmount, minQuantity, giftQuantity, giftProductId, giftProductName, targetProductId, targetProductName, targetProduct` (đã whitelist).
CẮT toàn bộ `kiotViet*`, `createdDate/modifiedDate/priority/isEnabled` + `giftItems` (FE lấy từ `/promotions/apply`), `fromDate, toDate, giftProductCode, giftProductBasePrice, targetProductCode` (không đọc ở DatHang). → giảm mạnh size (bỏ mảng `giftItems`).

## `POST /api/public/add_order` — DỰNG LẠI đơn server-side
`_recompute_order_economics()` **KHÔNG tin gì từ client trừ `{productId, quantity}`** của dòng mua thật. Dựng lại toàn bộ `cartItems` + tiền từ Firestore:
- **Bỏ mọi dòng `isGift`/`isPromotionItem` client gửi** → gift/Type3 tạo lại từ `apply_promotions()` (chống tiêm hàng tặng giả để lấy free).
- **Giá bán**: `BasePrice` từ Firestore; giảm giá Type2/Type3 tính server-side (khớp làm tròn floor-1000 của FE).
- **Ship**: port `calculateShipCost()`; tính lại `distanceKm` từ `lat/lng` (store `16.019693, 108.197694`, ROAD_FACTOR 1.3, `Math.round`→`floor(x/1000+0.5)*1000`).
- **Điểm thưởng**: cap theo số dư THẬT (`_calc_gift_point()` trong `verify-identity`), không tin `giftPoint` client.
- **Giá vốn**: `totalCost` từ `Cost` server → BanHang theo dõi lợi nhuận. Dòng cartItems dùng `_public_product` → **KHÔNG lưu `Cost` per-line** (tránh rò qua GET order).
- **Chống overwrite (atomic)**: dùng `orders_ref.document(id).create()` → `409` nếu id tồn tại (không còn race read+set). Không có id → server tự sinh `DH+timestamp`.
- **SP orderable**: reject nếu SP không active / đã xóa / clone / danh mục ẩn / KM (`_is_orderable`, tái dùng filter list). *Stock: chưa hard-check (do clone-stock cần enrich riêng, tránh reject oan).*
- **Delivery**: reject nếu thiếu `lat/lng` hợp lệ (bounds VN, KHÔNG fallback `distanceKm` client) hoặc subtotal < 200.000đ.
- **Validate**: SĐT (≥9 số), quantity (>0, ≤100000), reject giỏ rỗng/không có SP thật.
- **Flag**: client trả thiếu hơn server > 1000đ → `suspiciousOrder=true` + `priceAudit` + log. Override im lặng (không reject → khỏi mất đơn thật do giỏ cũ).

## `GET /api/public/orders/<id>` — chi tiết đơn SLIM (cho my-orders/confirm)
`_public_order()`: chỉ trả `id, status, createdDate, customerPaid, wantDelivery, desiredDelivery*, cartItems[{product.Name/Image, quantity, unitPrice}]`. **CẮT** SĐT/địa chỉ/lat-lng/`totalCost`/`discountAmount`. `/api/firebase/orders/<id>` (full) giờ đã **GATE admin**. FE `order-api.getOrderById` đã repoint sang path này.

Ràng buộc: `_STORE_LAT/_STORE_LNG`, tier ship, dòng phí ship (`Id 43370064 / Code SP170288`) phải khớp FE. Đơn nội bộ (BanHang/Management) vẫn qua `/api/firebase/add_order` cũ.

## CÒN MỞ (ngoài scope `firebase_public.py`)
- **`/api/firebase/*` không auth**: ĐÃ FIX bằng admin-auth gate (`X-Id-Token`, `ENFORCE_ADMIN_AUTH`). Xem `ADMIN-AUTH.md`.
- **`GET /api/firebase/orders/<id>` rò PII/totalCost**: ĐÃ FIX — endpoint full giờ gate admin; DatHang dùng `/api/public/orders/<id>` slim. (Residual nhỏ: nội dung đơn — tên món/giá — vẫn xem được nếu đoán ID; muốn kín hẳn thì token theo đơn.)
- **`/api/firebase/promotions/apply` tin `basePrice` client**: chỉ ảnh hưởng số HIỂN THỊ; số TÍNH TIỀN đã đúng vì add_order tự chạy lại engine với giá server.
- **Stock hard-check trong add_order**: chưa làm (cần enrich clone-stock để tránh reject oan SP bán qua clone).
