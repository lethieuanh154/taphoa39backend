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
GIỮ (13 field FE thực dùng): `Id, Code, Name, FullName, Image, BasePrice, Unit, CategoryId, CategoryName, ConversionValue` (product-detail), `MasterUnitId` (GroupService grouping), `NormalizedName` (offline search có dấu), `OnHand` (tồn KiotViet) + `CloneOnHandNV` (tổng tồn clone của SP — xem dưới).
`CategoryName` thêm vào để DatHang **dựng lại danh mục offline** từ IndexedDB khi cả 2 endpoint danh mục chết.
CẮT: `Cost, OldCost, PackCost, _original*, OnHandNV, SyncChecksum, SyncTimestamp, Revision, MasterCode, kiotViet*` + `NormalizedCode, MasterProductId, isActive, isDeleted` (BE đã lọc sẵn → FE default khi thiếu).

**`Description` đã bị cắt (2026-09-14).** Field này trong Firestore đang chứa ghi chú nội bộ của nhân viên — `"k vat"`, `"1T = 12c"`, `"1T (20g) = 570k"`, `"21/3: 4.4/gói"` (giá sỉ / giá nhập) — và trước đó lọt nguyên vào response public. Khoảng 6-13% sản phẩm có nội dung dạng này, phần còn lại rỗng.
Muốn mở lại (ví dụ để nút info mô tả trên card DatHang hoạt động): làm sạch `Description` trên KiotViet trước, rồi thêm lại `"Description": p.get("Description") or ""` vào `_public_product`. FE đã strip HTML sẵn trong `mapProduct()`.

Lọc **server-side** (không để FE tự lọc bằng field nhạy cảm): bỏ clone + hàng nội bộ (`isClone` true/"true" hoặc `KiotVietSync === false`) / KM `(km)` Cost=0 / danh mục ẩn (`1440125, 1787413`) / deleted-inactive.

**Trả lại `CloneOnHandNV` (đổi 27/09/2026).** User chốt: original hết/không đủ thì DatHang bán tiếp bằng tồn clone. `_public_product(p, clone_map)` trả `CloneOnHandNV` riêng (FE cộng `OnHand + CloneOnHandNV`), `add_order` validate theo `OnHand + clone − reserved`. Map lấy từ `ProductService.get_public_clone_stock_map()`: query `isClone in [True,"true"]` (KHÔNG full scan), cache `public_clone_stock` 600s dạng `{clone_id: [source_id, nv]}`, `patch_stock_caches()` vá tại chỗ khi BanHang ghi `OnHandNV`. Bỏ qua clone deleted/inactive và hàng nội bộ (`CloneSourceId` = chính Id). SP clone/hàng nội bộ vẫn không bao giờ được public.
Lịch sử — **18/09/2026 từng bỏ gộp:** Trước đây có gộp, với lý do "ẩn cơ chế clone, vẫn báo đúng tồn kho" — sai: **DatHang không bán hàng clone**. SP hết hàng trên KiotViet nhưng còn tồn clone vẫn hiện "còn hàng", khách đặt được thứ nhân viên không lấy ra bán được. `_public_product()` giờ trả `OnHand` thuần từ KiotViet. `_clone_stock_map()` và `_enrich_clone_stock()` đã xoá khỏi `firebase_public.py` (hết chỗ gọi; cache key `clone_stock_map` vẫn còn dùng ở `firebase_products.py` cho đường nội bộ).

**`OnHand` đã trừ phần đơn online đang giữ (2026-09-14).** `_serialize_public_products(products, reserved_map)` trừ số giữ hàng còn hạn khỏi `OnHand` trước khi trả về, nên khách không đặt trùng phần hàng khách khác đã giữ. `add_order` cũng chặn oversell theo `OnHand + clone − reserved` (cộng lại clone từ 27/09/2026). Chi tiết: `docs/RESERVATION.md`.

### Ảnh sản phẩm — `ImageVariant` ưu tiên hơn `Image`
`"Image": p.get("ImageVariant") or p.get("Image")`.

Sync toàn bộ dùng `resource/fetch?resourceName=Products`, field `Image` trả về là **ảnh cấp master product**, dùng chung cho mọi biến thể trong nhóm → nhiều SP khác mã vạch hiển thị **trùng một ảnh** trên DatHang. Ví dụ master `SPC004308` "Trà Tea plus 1L" gồm 3 mã vạch × 4 đơn vị = 12 biến thể, cả 12 doc cùng một URL ảnh.

Ảnh riêng từng biến thể chỉ có ở `POST branchs/{branchId}/masterproducts?MasterProductId=...` — client mới: `FromKiotViet/get_master_product_variants.py` (`get_variants()`, `get_variant_images()`).

Backfill: `python scripts/fix_variant_images_from_kiotviet.py [--dry-run] [--master <id>] [--limit N] [--yes]`. Script gom products theo `MasterProductId`, **chỉ** gọi API cho nhóm có ≥2 SP trùng URL `Image` (1 request/nhóm), rồi ghi field **`ImageVariant`**.

Vì sao dùng field riêng thay vì ghi đè thẳng `Image`: `sync_products_from_kiotviet()` ghi bằng `batch.set(..., merge=True)` với payload thô từ KiotViet → `Image` sẽ bị ảnh master ghi đè lại ở lần sync sau. `ImageVariant` không nằm trong payload nên sống sót, và **sync đã được patch để tôn trọng nó**: bước 1 `select([... , "ImageVariant"])` dựng map `variant_images`, bước 3 gán `product_to_store["Image"] = variant_images[doc_id]` **sau** khi tính checksum (checksum vẫn theo dữ liệu KiotViet → không ghi lại vô hạn). Clone tự nhận ảnh đúng qua `_sync_clones_with_originals()` vì `Image` nằm trong `SYNC_FIELDS`.

Giới hạn còn lại: doc có checksum không đổi thì sync bỏ qua, `Image` giữ nguyên ảnh master cũ → BanHang/Management (đọc doc thô qua `/api/firebase/products/*`) vẫn thấy sai cho tới lần sync có thay đổi. DatHang không bị vì `_public_product` ưu tiên `ImageVariant`.

## Whitelist khuyến mãi (`_public_promotion`)
GIỮ: `id, type, name, hasGift, hasPercentDiscount, hasFixedDiscount, discountPercent, discountAmount, minQuantity, giftQuantity, giftProductId, giftProductName, giftProductCode, giftProductBasePrice, giftItems, giftProducts, fromDate, toDate, priority, isFlashBanner, targetProductId, targetProductName, targetProduct` (đã whitelist).
CẮT toàn bộ `kiotViet*`, `createdDate/modifiedDate/isEnabled`, `targetProductCode`.

**Mở lại (cho trang `/khuyen-mai` của DatHang)** — trước đây từng cắt để giảm size:
- `giftItems`: chuẩn hoá bởi `_public_gift_entries()` → `[{productId, code, name, basePrice, quantity}]`. Fallback field scalar cũ (`giftProductId/giftQuantity`) khi doc chưa có mảng → FE chỉ đọc 1 dạng.
- `giftProducts`: mảng `_public_product` của từng quà + `GiftQuantity` → trang KM render ảnh/giá quà tặng và SP mua kèm (Type 3) mà không phải gọi thêm API.
- `fromDate/toDate`: hiển thị hạn KM + đếm ngược trên trang chủ.
- `priority`: sắp xếp thứ tự hiển thị.
- `isFlashBanner` (bool, **tính toán, không lưu Firestore**): `is_flash_banner()` = `toDate - fromDate < 7 ngày` → popup banner Home DatHang. Giới hạn 4 SP chồng thời gian validate ở `_flash_banner_error` (`routes/firebase_promotions.py`).

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
- **Ship**: port `calculateShipCost()`; tính lại `distanceKm` từ `lat/lng` (store `16.019693, 108.197694`, ROAD_FACTOR 1.3, `Math.round`→`floor(x/1000+0.5)*1000`). Bảng phí (23/09/2026, **bỏ phụ phí hàng nặng**):

  | Subtotal | freeKm | đ/km | minKm |
  |---|---|---|---|
  | < 200.000 | — không giao — | | |
  | < 500.000 | 0 | 13.000 | **1,0** |
  | < 1.000.000 | 1 | 6.000 | 0 |
  | < 2.000.000 | 2 | 5.000 | 0 |
  | < 5.000.000 | 3 | 5.000 | 0 |
  | < 10.000.000 | 5 | 5.000 | 0 |
  | ≥ 10.000.000 | 8 | 4.000 | 0 |

  `chargeable = max(minKm, distanceKm - freeKm)`. `minKm` chỉ khác 0 ở bậc đầu — đơn nhỏ ở rất gần vẫn phải trả tối thiểu 1km, vì chi phí giao có phần cố định ~10.000đ không phụ thuộc quãng đường.
- **Chiết khấu sỉ hàng thùng** (`_pickup_bulk_discount()`, mới 23/09/2026): **> 10 thùng** hàng nặng (`_HEAVY_PATTERN`, `Unit == "thùng"`) → **2.000đ/thùng**. **CHỈ khi `wantDelivery == false`** — giá sỉ là giá tại cửa hàng, không cộng gộp với giao hàng. Cap ở `subtotal`. Ghi ra `order["pickupBulkDiscount"]` + `order["heavyCaseCount"]`, cộng vào `discountAmount`, và trừ khỏi subtotal **trước** khi cap điểm thưởng (`subtotal_payable`).
- **Điểm thưởng**: cap theo số dư THẬT (`_calc_gift_point()` trong `verify-identity`), không tin `giftPoint` client.
- **Giá vốn**: `totalCost` từ `Cost` server → BanHang theo dõi lợi nhuận. Dòng cartItems dùng `_public_product` → **KHÔNG lưu `Cost` per-line** (tránh rò qua GET order).
- **Chống overwrite (atomic)**: dùng `orders_ref.document(id).create()` → `409` nếu id tồn tại (không còn race read+set). Không có id → server tự sinh `DH+timestamp`.
- **SP orderable**: reject nếu SP không active / đã xóa / clone / danh mục ẩn / KM (`_is_orderable`, tái dùng filter list). *Stock: chưa hard-check (do clone-stock cần enrich riêng, tránh reject oan).*
- **Delivery**: reject nếu thiếu `lat/lng` hợp lệ (bounds VN, KHÔNG fallback `distanceKm` client) hoặc subtotal < 200.000đ.
- **Validate**: SĐT (≥9 số), quantity (>0, ≤100000), reject giỏ rỗng/không có SP thật.
- **Flag**: client trả thiếu hơn server > 1000đ → `suspiciousOrder=true` + `priceAudit` + log. Override im lặng (không reject → khỏi mất đơn thật do giỏ cũ).

## `GET /api/public/orders/<id>` — chi tiết đơn SLIM (cho my-orders/confirm)
`_public_order()`: chỉ trả `id, status, createdDate, customerPaid, wantDelivery, desiredDelivery*, cartItems[{product.Name/Image, quantity, unitPrice}]`. **CẮT** SĐT/địa chỉ/lat-lng/`totalCost`/`discountAmount`. `/api/firebase/orders/<id>` (full) giờ đã **GATE admin**. FE `order-api.getOrderById` đã repoint sang path này.

Ràng buộc: `_STORE_LAT/_STORE_LNG`, tier ship, `_BULK_DISCOUNT_MIN_CASES/_BULK_DISCOUNT_PER_CASE`, `_HEAVY_PATTERN`, dòng phí ship (`Id 43370064 / Code SP170288`) phải khớp FE (`TapHoa39DatHang/src/app/services/shipping.service.ts`). Đơn nội bộ (BanHang/Management) vẫn qua `/api/firebase/add_order` cũ.

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

## Đồng bộ tồn kho KiotViet (thêm 18/09/2026)

Trước đây DatHang chỉ đọc snapshot Firestore, mà Firestore **chỉ đổi khi user bấm full reload thủ công ở BanHang**. KiotViet bán hết trong ngày → DatHang vẫn hiện còn hàng, khách đặt được hàng không có.

### E1 — validate đơn đọc tồn kho FRESH

| | |
|---|---|
| Hàm | `read_product_fresh(product_id)` — `firebase/firebase_service/product_service.py` |
| Vào / ra | `product_id` (str\|int) → `Dict` sản phẩm, hoặc `None` nếu doc không tồn tại |
| Khác `read_product()` | **Bỏ qua cache doc-lẻ** (`CACHE_TTL = 3600`), đọc thẳng Firestore rồi nạp lại cache |
| Gọi từ | `_recompute_order_economics()` trong `routes/firebase_public.py`, đúng vòng validate `qty > available` |

Vì sao cần: `read_product()` cache 1 tiếng → lớp chặn oversell đang so số lượng đặt với **OnHand cũ tới 60 phút**. Chỉ gọi trên vài SP trong giỏ nên chi phí Firestore không đáng kể (không phải vòng lặp toàn bộ products).

> Dòng quà tặng (`read_product(gid)`, ~line 386) **vẫn dùng cache** — chỉ lấy tên/giá để hiển thị, không tham gia check tồn kho.

### E2 — scheduler tự kéo KiotViet → Firestore

| | |
|---|---|
| Hàm | `_schedule_kiotviet_auto_sync(product_service, socketio)` — `app.py` |
| Chu kỳ | env `KIOTVIET_AUTO_SYNC_MINUTES`, mặc định **15**; đặt `0` để **tắt** |
| Thread | daemon riêng, `threading.Lock` non-blocking — tick trước chưa xong thì **bỏ** tick này, không xếp hàng |

Mỗi lượt chạy 3 bước, theo đúng thứ tự:
1. `sync_products_from_kiotviet()` — fetch KiotViet, so `SyncChecksum`, chỉ ghi SP đổi.
2. `refresh_all_products_cache()` — **bắt buộc**: bước 1 kết thúc bằng `invalidate_all_product_caches()` nên cache rỗng; không nạp lại ngay thì request khách kế tiếp tự kéo full scan (đúng vết stampede 11/09/2026 ở mục trên).
3. `broadcast_products_onhand_updated(socketio, changed)` — client đang mở thấy tồn kho mới, không cần reload.

**KHÔNG BAO GIỜ gọi KiotViet trong request của khách.** Một lần fetch là `pageSize: 20000`, thường 30–60s (`FromKiotViet/get_entire_product.py`). Trên gunicorn `--workers=1 --threads=32`, vài khách mở Home cùng lúc là cạn thread → nginx 504 toàn bộ API. `public_categories()` đã có sẵn cảnh báo này.

`sync_products_from_kiotviet()` nay trả thêm key **`changed_products`**: list `{Id, OnHand, BasePrice, Cost, Name, FullName, Code, ModifiedDate}` của SP vừa đổi (chỉ field khác `None`). `Id` ép về **number** để khớp key IndexedDB của client. Quá `MAX_SYNC_BROADCAST = 500` SP thì trả list rỗng + log cảnh báo — emit cả chục nghìn SP sẽ nghẹn socket, client lấy lại ở lần load sau.

### Còn lệch — chưa xử

- ~~**SP có clone**: WS emit `OnHand` thô, IndexedDB DatHang lưu `OnHand` đã gộp clone → WS ghi đè gây lệch.~~ **Hết lệch** sau khi bỏ gộp clone (cùng ngày): cả `_public_product()` lẫn WS giờ cùng nói `OnHand` thuần KiotViet.
- ~~Rác FE DatHang cộng `CloneOnHandNV`~~ — không còn là rác từ 27/09/2026 (BE trả lại field). BanHang bán clone (`update_onhand_batch`) → sau `patch_stock_caches()` BE phát event riêng `clone_stock_updated` `{products: [{Id: original_id, CloneOnHandNV}]}` (namespace `/api/websocket/products`, `ProductService.public_clone_stock_for()` chỉ đọc cache). Không trộn vào `products_updated` để BanHang/Management không ghi field lạ vào IndexedDB. DatHang `ProductApiService.handleCloneStockUpdated()` cập nhật IndexedDB. Giới hạn: số qua WS là tồn clone thô (chưa trừ phần giữ tràn sang clone), sửa SP clone qua trang edit thì chỉ invalidate cache, không phát event.
- **Sync thủ công ở BanHang chạy song song với scheduler**: lock chỉ có trong scheduler. Hai luồng có thể fetch KiotViet cùng lúc; ghi Firestore là `batch.set(merge=True)` nên idempotent, hệ quả chỉ là tốn quota.
- **Realtime thật (push)** cần webhook của KiotViet **Public API** (`public.kiotapi.com`, OAuth `client_id`/`client_secret`). Dự án đang dùng **internal API** (`api-man1.kiotviet.vn`, login UserName/Password + `FingerPrintKey`) — API này **không có webhook**, chỉ pull được.

## BanHang bán hàng → cache RAM phải được vá (sửa 18/09/2026)

`PUT /api/firebase/products/update_onhand_batch` gọi `update_products_from_banhang_app_to_firestore()` (`firebase/firebase_hanghoa/import_to_firestore.py`) — hàm này ghi Firestore bằng **transaction trực tiếp, không đi qua `product_service`**, nên trước đây **không đụng một dòng cache nào**.

Hậu quả: Firestore đúng, cache RAM sai → nghịch lý
- khách **đang mở** DatHang: `broadcast_products_onhand_updated()` bắn ngay → IndexedDB đúng tức thì;
- khách **mới vào / F5**: đọc `/api/public/*` từ cache → thấy tồn cũ tới **15–55 phút**.

Triệu chứng nhận dạng: *card hiện "còn 3", bấm Đặt hàng thì báo "đã hết hàng"* (validate dùng `read_product_fresh()` nên luôn đúng — xem E1).

Route nay gọi `product_service.patch_stock_caches(updates)` trước khi broadcast. Chiến lược **khác nhau theo từng loại cache**, cốt để không phát sinh đọc Firestore:

| Cache | Xử lý | Vì sao |
|---|---|---|
| `all_products*` | patch in-place | Invalidate = full scan 15k doc |
| `products_by_category:*` | patch in-place | Invalidate = `read_products_by_category()` query lại Firestore |
| `featured_products:*` | **xoá hẳn** | `get_featured_products()` giữ bản sao riêng đã sort nên patch không đủ. Build lại chỉ là filter+sort trên `all_products` đã nằm sẵn trong RAM — **~3 ms/15k SP, 0 read Firestore** |
| doc lẻ theo id | xoá | Lần đọc sau lấy bản mới |

`Cache.bulk_update_items_in_lists(prefix, id_field, updates_by_id)` duyệt mỗi list **đúng 1 lần** cho cả lô. Gọi `update_item_in_lists()` trong vòng lặp thì chi phí tăng tuyến tính theo số món:

| Hoá đơn | `bulk_update_items_in_lists` | vòng lặp từng món |
|---|---|---|
| 1 món | 3,0 ms | 1,9 ms |
| 20 món | **3,3 ms** | 26,1 ms |
| 50 món | **3,1 ms** | 64,0 ms |

Tổng chi phí mỗi hoá đơn ≈ **3,3 ms** (patch) + **3,3 ms** (rebuild featured ở request kế tiếp) ≈ **6,6 ms**, không tốn read Firestore. Với nhịp 1–2 hoá đơn/phút là không đáng kể.

> **Trần đồng thời của backend KHÔNG phải CPU.** `transports=['polling']` (app.py) → mỗi client Socket.IO đang mở **giữ một thread** gunicorn tới `pingInterval` 25s, trong khi `--threads=32`. Xem rule trong `CLAUDE.md`. Đừng dùng số ms ở trên để suy ra số người đồng thời.

### Lọc trước, serialize sau — `_paginate_public_products()` (sửa 18/09/2026)
Trước đây `public_featured()` / `public_by_category()` dựng dict cho cả ~15k SP **rồi mới** cắt `[offset:offset+limit]` lấy 20 cái — **14 ms CPU mỗi request**, kể cả khi khách chỉ cuộn thêm một trang.

`_paginate_public_products(products, reserved_map)` đảo thứ tự: `_is_orderable()` (không dựng dict, rất rẻ) → cắt trang → `_public_product()` **chỉ cho trang thực sự trả về** → trừ `reserved_map` trên đúng trang đó. Trả `(page, total, offset)`.

| | mỗi request | RAM thêm |
|---|---|---|
| Cũ: serialize 15k rồi cắt | 14,1 ms | — |
| **Nay: lọc → cắt → serialize 20** | **4,2 ms** | **0** |
| (đã cân nhắc) cache list đã serialize | 0,01 ms | 2–4 MB |

**Đã cân nhắc và bỏ** phương án cache list đã serialize, dù nhanh hơn 1369×: nó thêm **một cache key nữa phải nhớ invalidate mỗi khi tồn kho đổi** — đúng họ với bug `featured_products:*` bị quên xoá ở mục trên. Mua 4 ms bằng một mầm bug cùng loại là lỗ.

`_serialize_public_products()` **vẫn giữ** cho `public_search()`: search trả tối đa 200 SP và không phân trang, nên không có gì để tiết kiệm.

> Đây là tối ưu **latency đuôi lúc burst**, không phải tăng trần người dùng. Ở tải thường (~5 req/s) endpoint này chỉ ăn ~7% một core; giá trị thật là khi cả nhà cùng mở app một lúc (60 request dồn: ~840 ms → ~250 ms CPU qua GIL). Trần đồng thời vẫn là 32 thread long-poll — xem cảnh báo ở mục trên.

## WebSocket `/api/websocket/products` — tách room staff/public (27/09/2026)

Namespace này dùng chung cho DatHang (khách, không login) và BanHang/Management. Trước đây mọi client nhận **cùng** payload → khách đọc được `Cost` (giá vốn), `OnHandNV`, `Description` (ghi chú giá sỉ/giá nhập), SP clone/hàng nội bộ mới tạo và dữ liệu hàng gộp.

`ProductsRoomNamespace` (`routes/firebase_websocket.py`):
- Connect → room **`public`**. Có Firebase ID token hợp lệ (socket `auth: {idToken}` lúc connect, hoặc event `authenticate {idToken}` sau đó, ack `{ok}`) → room **`staff`**.
- `ENFORCE_ADMIN_AUTH=false` (BE local tại quầy) → mọi client là staff, như trước.
- `subscribe` bị vô hiệu ở namespace này (không cho tự join `staff`).

Phát theo room:
| Event | staff | public |
|---|---|---|
| `products_updated` | đủ field | `_public_ws_product()` whitelist: `Id, Code, Name, FullName, NormalizedName, NormalizedCode, OnHand, BasePrice, Unit, CategoryId, ConversionValue, MasterUnitId, isActive, isDeleted, ModifiedDate`; entry chỉ còn Id → bỏ |
| `products_added` | đủ field | chỉ SP `_is_orderable` qua `_public_product` (bỏ clone/hàng nội bộ/KM/danh mục ẩn) |
| `merged_products_updated` | có | **không** |
| relay `POST .../notify` namespace `products` | có | **không** |
| `products_onhand_updated` (chỉ Id), `promotions_updated`, `clone_stock_updated`, `product_onhand_updated` | có | có |

Replay khi connect (`LAST_NOTIFIES`): `set_last_notify(ns, event, data, public_data)` — room public nhận `public_data` (None → không replay).

FE staff: `websocket-realtime.service.ts` (mirror BanHang ⇄ Management) gửi token qua `auth` + `authenticate` khi `onIdTokenChanged`. **Thứ tự deploy:** FE Management trước, BE sau (BE cũ bỏ qua event lạ; ngược lại Management sẽ rơi vào room public → mất Cost/OnHandNV/hàng gộp realtime).

## CÒN MỞ (ngoài scope `firebase_public.py`)
- **`/api/firebase/*` không auth**: ĐÃ FIX bằng admin-auth gate (`X-Id-Token`, `ENFORCE_ADMIN_AUTH`). Xem `ADMIN-AUTH.md`.
- **`GET /api/firebase/orders/<id>` rò PII/totalCost**: ĐÃ FIX — endpoint full giờ gate admin; DatHang dùng `/api/public/orders/<id>` slim. (Residual nhỏ: nội dung đơn — tên món/giá — vẫn xem được nếu đoán ID; muốn kín hẳn thì token theo đơn.)
- **`/api/firebase/promotions/apply` tin `basePrice` client**: chỉ ảnh hưởng số HIỂN THỊ; số TÍNH TIỀN đã đúng vì add_order tự chạy lại engine với giá server.
- ~~**Stock hard-check trong add_order**: chưa làm~~ → ĐÃ LÀM. `_recompute_order_economics()` chặn `qty > OnHand - reserved`, và từ 18/09/2026 đọc tồn kho FRESH (E1, mục trên) nên không còn so với cache 1 tiếng.
