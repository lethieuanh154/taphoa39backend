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
| POST | `/api/public/add_order` | `/api/firebase/add_order` |

## Whitelist sản phẩm (`_public_product`) — đã làm gọn
GIỮ (13 field FE thực dùng): `Id, Code, Name, FullName, Image, BasePrice, Unit, Description, CategoryId, ConversionValue` (product-detail), `MasterUnitId` (GroupService grouping), `NormalizedName` (offline search có dấu), `OnHand` (đã gộp clone).
CẮT: `Cost, OldCost, PackCost, _original*, OnHandNV, CloneOnHandNV (raw), SyncChecksum, SyncTimestamp, Revision, MasterCode, kiotViet*` + `NormalizedCode, MasterProductId, isActive, isDeleted` (BE đã lọc sẵn → FE default khi thiếu).

Lọc **server-side** (không để FE tự lọc bằng field nhạy cảm): bỏ clone / KM `(km)` Cost=0 / danh mục ẩn (`1440125, 1787413`) / deleted-inactive. **Gộp `CloneOnHandNV` vào `OnHand`** (ẩn cơ chế clone, vẫn báo đúng tồn kho).

## Whitelist khuyến mãi (`_public_promotion`) — đã làm gọn
GIỮ: `id, type, name, hasGift, hasPercentDiscount, hasFixedDiscount, discountPercent, discountAmount, minQuantity, giftQuantity, giftProductId, giftProductName, targetProductId, targetProductName, targetProduct` (đã whitelist).
CẮT toàn bộ `kiotViet*`, `createdDate/modifiedDate/priority/isEnabled` + `giftItems` (FE lấy từ `/promotions/apply`), `fromDate, toDate, giftProductCode, giftProductBasePrice, targetProductCode` (không đọc ở DatHang). → giảm mạnh size (bỏ mảng `giftItems`).

## `POST /api/public/add_order` — tính lại tiền server-side
`_recompute_order_economics()` **ghi đè** mọi field tiền (server là nguồn chân lý), chống sửa qua F12:
- **Giá bán**: dùng `BasePrice` từ Firestore; chạy lại `promotion_service.apply_promotions()` cho giảm giá + quà + SP B (Type 3).
- **Ship**: port `calculateShipCost()` của FE; tính lại `distanceKm` từ `lat/lng` (store `16.019693, 108.197694`, ROAD_FACTOR 1.3, `Math.round`→`floor(x/1000+0.5)*1000`).
- **Điểm thưởng**: cap theo số dư THẬT từ Firestore (khớp `_calc_gift_point()` trong `verify-identity`), không tin `giftPoint` client.
- **Giá vốn**: `totalCost` tính từ `Cost` server (vì client đã bị ẩn Cost) → BanHang vẫn theo dõi lợi nhuận.
- **Flag**: nếu client trả thiếu hơn server > 1000đ → gắn `suspiciousOrder=true` + `priceAudit={clientPaid, serverPaid, underpay}` + log để review thủ công. Đơn vẫn được tạo (override im lặng, không reject để khỏi mất đơn thật do giỏ cũ).

Ràng buộc: cấu hình `_STORE_LAT/_STORE_LNG`, tier ship, dòng phí ship (`Id 43370064 / Code SP170288`) phải khớp FE. Đơn nội bộ (BanHang/Management) vẫn qua `/api/firebase/add_order` cũ.
