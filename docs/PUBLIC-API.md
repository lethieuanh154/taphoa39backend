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
GIỮ (13 field FE thực dùng): `Id, Code, Name, FullName, Image, BasePrice, Unit, CategoryId, CategoryName, ConversionValue` (product-detail), `MasterUnitId` (GroupService grouping), `NormalizedName` (offline search có dấu), `OnHand` (đã gộp clone).
`CategoryName` thêm vào để DatHang **dựng lại danh mục offline** từ IndexedDB khi cả 2 endpoint danh mục chết.
CẮT: `Cost, OldCost, PackCost, _original*, OnHandNV, CloneOnHandNV (raw), SyncChecksum, SyncTimestamp, Revision, MasterCode, kiotViet*` + `NormalizedCode, MasterProductId, isActive, isDeleted` (BE đã lọc sẵn → FE default khi thiếu).

**`Description` đã bị cắt (2026-09-14).** Field này trong Firestore đang chứa ghi chú nội bộ của nhân viên — `"k vat"`, `"1T = 12c"`, `"1T (20g) = 570k"`, `"21/3: 4.4/gói"` (giá sỉ / giá nhập) — và trước đó lọt nguyên vào response public. Khoảng 6-13% sản phẩm có nội dung dạng này, phần còn lại rỗng.
Muốn mở lại (ví dụ để nút info mô tả trên card DatHang hoạt động): làm sạch `Description` trên KiotViet trước, rồi thêm lại `"Description": p.get("Description") or ""` vào `_public_product`. FE đã strip HTML sẵn trong `mapProduct()`.

Lọc **server-side** (không để FE tự lọc bằng field nhạy cảm): bỏ clone / KM `(km)` Cost=0 / danh mục ẩn (`1440125, 1787413`) / deleted-inactive. **Gộp `CloneOnHandNV` vào `OnHand`** (ẩn cơ chế clone, vẫn báo đúng tồn kho).

### Ảnh sản phẩm — `ImageVariant` ưu tiên hơn `Image`
`"Image": p.get("ImageVariant") or p.get("Image")`.

Sync toàn bộ dùng `resource/fetch?resourceName=Products`, field `Image` trả về là **ảnh cấp master product**, dùng chung cho mọi biến thể trong nhóm → nhiều SP khác mã vạch hiển thị **trùng một ảnh** trên DatHang. Ví dụ master `SPC004308` "Trà Tea plus 1L" gồm 3 mã vạch × 4 đơn vị = 12 biến thể, cả 12 doc cùng một URL ảnh.

Ảnh riêng từng biến thể chỉ có ở `POST branchs/{branchId}/masterproducts?MasterProductId=...` — client mới: `FromKiotViet/get_master_product_variants.py` (`get_variants()`, `get_variant_images()`).

Backfill: `python scripts/fix_variant_images_from_kiotviet.py [--dry-run] [--master <id>] [--limit N] [--yes]`. Script gom products theo `MasterProductId`, **chỉ** gọi API cho nhóm có ≥2 SP trùng URL `Image` (1 request/nhóm), rồi ghi field **`ImageVariant`**.

Vì sao dùng field riêng thay vì ghi đè thẳng `Image`: `sync_products_from_kiotviet()` ghi bằng `batch.set(..., merge=True)` với payload thô từ KiotViet → `Image` sẽ bị ảnh master ghi đè lại ở lần sync sau. `ImageVariant` không nằm trong payload nên sống sót, và **sync đã được patch để tôn trọng nó**: bước 1 `select([... , "ImageVariant"])` dựng map `variant_images`, bước 3 gán `product_to_store["Image"] = variant_images[doc_id]` **sau** khi tính checksum (checksum vẫn theo dữ liệu KiotViet → không ghi lại vô hạn). Clone tự nhận ảnh đúng qua `_sync_clones_with_originals()` vì `Image` nằm trong `SYNC_FIELDS`.

Giới hạn còn lại: doc có checksum không đổi thì sync bỏ qua, `Image` giữ nguyên ảnh master cũ → BanHang/Management (đọc doc thô qua `/api/firebase/products/*`) vẫn thấy sai cho tới lần sync có thay đổi. DatHang không bị vì `_public_product` ưu tiên `ImageVariant`.

## Whitelist khuyến mãi (`_public_promotion`)
GIỮ: `id, type, name, hasGift, hasPercentDiscount, hasFixedDiscount, discountPercent, discountAmount, minQuantity, giftQuantity, giftProductId, giftProductName, giftProductCode, giftProductBasePrice, giftItems, giftProducts, fromDate, toDate, priority, targetProductId, targetProductName, targetProduct` (đã whitelist).
CẮT toàn bộ `kiotViet*`, `createdDate/modifiedDate/isEnabled`, `targetProductCode`.

**Mở lại (cho trang `/khuyen-mai` của DatHang)** — trước đây từng cắt để giảm size:
- `giftItems`: chuẩn hoá bởi `_public_gift_entries()` → `[{productId, code, name, basePrice, quantity}]`. Fallback field scalar cũ (`giftProductId/giftQuantity`) khi doc chưa có mảng → FE chỉ đọc 1 dạng.
- `giftProducts`: mảng `_public_product` của từng quà + `GiftQuantity` → trang KM render ảnh/giá quà tặng và SP mua kèm (Type 3) mà không phải gọi thêm API.
- `fromDate/toDate`: hiển thị hạn KM + đếm ngược trên trang chủ.
- `priority`: sắp xếp thứ tự hiển thị.

### Resolve product của target/gift — batch, KHÔNG N+1 (sửa 13/09/2026)
Bản cũ `_resolve()` gọi `read_product()` từng SP một: **120 KM → 157 doc.get() tuần tự** → cold cache mất **>60s** → nginx trả **504**, DatHang nuốt lỗi và Home mất luôn dải "Khuyến mại".

Cách hiện tại:
1. Gom hết `targetProductId` + `giftItems[].productId` → **`product_service.read_products_bulk(ids)`**: đọc cache RAM trước, phần thiếu gọi `db.get_all()` theo lô 300 → **1 round-trip** thay vì N. Trả `{product_id: product}`, id không tồn tại thì không có key.
2. Cache luôn **response đã dựng xong** ở `promotion_service.cache` key `public_active_promotions` (`PUBLIC_ACTIVE_PROMOS_TTL` = 300s). `_invalidate_cache()` của promotion service xoá key này cùng `active_promotions`, nên tạo/sửa/xoá/toggle KM là thấy ngay.

`/api/firebase/promotions/active` (BanHang/Management) dùng cùng `read_products_bulk`, và **copy dict** thay vì gán `promo["targetProduct"]` in-place — bản cũ mutate đúng object đang nằm trong cache `active_promotions`.

> nginx cần bật `gzip` cho `application/json`: payload endpoint này ~280KB thô, gzip còn ~30KB (xem `TapHoa39DatHang/deployDataOnline`).

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

## Cache sản phẩm — chống stampede (sửa 11/09/2026)

`search` và `featured` đều đi qua `read_all_products()`. Cache hit ~5ms; cache **miss = full scan 13.4k doc, 14 query tuần tự, 18–20s**. Nên mọi thứ ở đây xoay quanh một luật: **cache không bao giờ được rỗng**.

| Hàm (`firebase/firebase_service/product_service.py`) | Vai trò |
|---|---|
| `_build_all_products(include_inactive, include_deleted)` | Full scan thuần → `List[Dict]`. **Không đọc, không ghi cache.** Lỗi giữa chừng thì raise (không cache kết quả dang dở). |
| `read_all_products(...)` | Đường phục vụ request. Cache hit → trả ngay. Miss → **single-flight**: 1 thread build, các thread khác chờ lock rồi dùng chung (double-check cache sau khi lấy được lock). |
| `refresh_all_products_cache()` | Đường của scheduler (`_warmup_product_cache` trong `app.py`, 55 phút/lần). Build xong **rồi mới swap** vào cache, sau đó mới xoá các key dẫn xuất (`featured_products:*`, `products_by_category:*`, `clone_stock_map`). Fetch fail → raise, **cache cũ giữ nguyên**. |

**Ba lỗi đã gây ra sự cố prod 11/09/2026** (API `search` treo 20s–3 phút):
1. Scheduler `invalidate_all_product_caches()` **trước** khi fetch → 18–20s cache rỗng → mọi request khách tự kéo full scan riêng.
2. Không có single-flight → N request đồng thời = N full scan song song trên `--workers=1` → đè nhau, `DEADLINE_EXCEEDED`, thời gian phình **18s → 96s → 234s → fail**.
3. `query.stream(timeout=...)` **không truyền `retry=`** → firestore rơi vào nhánh `retry is DEFAULT`, đọc `gapic_callable._retry` (`query.py:264`) → `AttributeError: '_UnaryStreamMultiCallable' object has no attribute '_retry'` (google-cloud-firestore 2.20.2 + google-api-core 2.25.0). Lỗi này **che mất `DEADLINE_EXCEEDED` thật** và làm retry không bao giờ chạy.

→ `PRODUCT_PAGE_RETRY` (`gapi_retry.Retry`) giờ được truyền tường minh vào `query.stream()`. **Không được bỏ `retry=`** khi đụng vào `_stream_all_product_docs()`.

`invalidate_all_product_caches()` vẫn giữ (xoá thẳng, để cache rỗng) — **chỉ** dùng cho KiotViet full sync / cleanup batch, **không** dùng ở đường refresh định kỳ.

## CÒN MỞ (ngoài scope `firebase_public.py`)
- **`/api/firebase/*` không auth**: ĐÃ FIX bằng admin-auth gate (`X-Id-Token`, `ENFORCE_ADMIN_AUTH`). Xem `ADMIN-AUTH.md`.
- **`GET /api/firebase/orders/<id>` rò PII/totalCost**: ĐÃ FIX — endpoint full giờ gate admin; DatHang dùng `/api/public/orders/<id>` slim. (Residual nhỏ: nội dung đơn — tên món/giá — vẫn xem được nếu đoán ID; muốn kín hẳn thì token theo đơn.)
- **`/api/firebase/promotions/apply` tin `basePrice` client**: chỉ ảnh hưởng số HIỂN THỊ; số TÍNH TIỀN đã đúng vì add_order tự chạy lại engine với giá server.
- **Stock hard-check trong add_order**: chưa làm (cần enrich clone-stock để tránh reject oan SP bán qua clone).
