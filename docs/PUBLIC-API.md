# PUBLIC API — `/api/public/*` (cho app DatHang)

File: `routes/firebase_public.py` — blueprint `create_firebase_public_bp(product_service, promotion_service, order_service, customer_service, socketio)`, đăng ký trong `app.py`.

## Mục đích
Che giấu dữ liệu nội bộ khỏi khách hàng (F12/Network) và chống sửa giá qua client. Route nội bộ cũ (`/api/firebase/*`) giữ nguyên cho BanHang/Management (full data).

## Endpoints

| Method | Path | Thay cho (nội bộ) |
|---|---|---|
| GET | `/api/public/categories` | `/api/kiotviet/categories` (phụ thuộc token KiotViet) |
| GET | `/api/public/products/featured?limit&offset` | `/api/firebase/products/featured` |
| GET | `/api/public/products/by-category/<id>?limit&offset` | `/api/firebase/get/products/by-category/<id>` |
| GET | `/api/public/products/search?q&limit` | `/api/firebase/products/search` |
| GET | `/api/public/promotions/active` | `/api/firebase/promotions/active` |
| GET | `/api/public/orders/<id>` | `/api/firebase/orders/<id>` (giờ đã GATE admin) |
| POST | `/api/public/add_order` | `/api/firebase/add_order` |

## `GET /api/public/categories` — snapshot, KHÔNG chạm KiotViet/full scan
`/api/kiotviet/categories` gọi thẳng KiotViet: sai/hết credentials → **502** → DatHang nhận `[]` và **mất sạch thanh danh mục** (đã xảy ra thật).

**Hai thứ TUYỆT ĐỐI không được làm trong endpoint này** (cả hai đều đã gây 504 trên prod 02/09/2026):
1. **Gọi KiotViet** — HTTP ra ngoài, chậm/treo là giữ luôn thread gunicorn (`--workers=1`) → nginx 504 lan sang mọi API khác. KiotViet chỉ được gọi trong `refresh_categories_from_kiotviet()`, chạy ở thread nền (warmup + CacheRefresh 55 phút).
2. **`read_all_products()`** — stream cả collection, trên prod trả `503 Query timed out. Please try either limiting the entities scanned`.

Luồng thực tế:
- **Tên danh mục** ← `product_service.read_categories()`: cache RAM (6h) → snapshot Firestore `app_config/categories` → KiotViet **chỉ khi chưa từng có snapshot** (lần chạy đầu).
- **Lọc "còn hàng"** ← chỉ áp dụng khi `get_cached_all_products()` trả về cache đang ấm; cache nguội thì bỏ qua bước lọc chứ **không** kéo thêm full scan. Lọc ra rỗng thì giữ nguyên danh sách gốc (thà thừa còn hơn mất thanh danh mục).
- Trừ `_HIDDEN_CATEGORY_IDS`, sort theo tên, `Path` sinh bằng `_category_path()` (`unidecode`): `"GIA VỊ - ĐỒ KHÔ"` → `GIA_VI_DO_KHO`.

## Whitelist sản phẩm (`_public_product`) — đã làm gọn
GIỮ (14 field FE thực dùng): `Id, Code, Name, FullName, Image, BasePrice, Unit, Description, CategoryId, CategoryName, ConversionValue` (product-detail), `MasterUnitId` (GroupService grouping), `NormalizedName` (offline search có dấu), `OnHand` (đã gộp clone).
`CategoryName` thêm vào để DatHang **dựng lại danh mục offline** từ IndexedDB khi cả 2 endpoint danh mục chết.
CẮT: `Cost, OldCost, PackCost, _original*, OnHandNV, CloneOnHandNV (raw), SyncChecksum, SyncTimestamp, Revision, MasterCode, kiotViet*` + `NormalizedCode, MasterProductId, isActive, isDeleted` (BE đã lọc sẵn → FE default khi thiếu).

Lọc **server-side** (không để FE tự lọc bằng field nhạy cảm): bỏ clone / KM `(km)` Cost=0 / danh mục ẩn (`1440125, 1787413`) / deleted-inactive. **Gộp `CloneOnHandNV` vào `OnHand`** (ẩn cơ chế clone, vẫn báo đúng tồn kho).

## Whitelist khuyến mãi (`_public_promotion`)
GIỮ: `id, type, name, hasGift, hasPercentDiscount, hasFixedDiscount, discountPercent, discountAmount, minQuantity, giftQuantity, giftProductId, giftProductName, giftProductCode, giftProductBasePrice, giftItems, giftProducts, fromDate, toDate, priority, targetProductId, targetProductName, targetProduct` (đã whitelist).
CẮT toàn bộ `kiotViet*`, `createdDate/modifiedDate/isEnabled`, `targetProductCode`.

**Mở lại (cho trang `/khuyen-mai` của DatHang)** — trước đây từng cắt để giảm size:
- `giftItems`: chuẩn hoá bởi `_public_gift_entries()` → `[{productId, code, name, basePrice, quantity}]`. Fallback field scalar cũ (`giftProductId/giftQuantity`) khi doc chưa có mảng → FE chỉ đọc 1 dạng.
- `giftProducts`: mảng `_public_product` của từng quà + `GiftQuantity` → trang KM render ảnh/giá quà tặng và SP mua kèm (Type 3) mà không phải gọi thêm API.
- `fromDate/toDate`: hiển thị hạn KM + đếm ngược trên trang chủ.
- `priority`: sắp xếp thứ tự hiển thị.

Product của target/gift resolve qua **cache dict trong 1 request** (`_resolve`) → không đọc Firestore trùng khi nhiều KM dùng chung 1 SP.

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
