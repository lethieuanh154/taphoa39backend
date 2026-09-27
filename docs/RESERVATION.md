# Giữ hàng cho đơn đặt online (product_reservations)

Đơn đặt từ DatHang giữ chỗ tồn kho trong **24h**. Hết hạn thì tự nhả và đơn bị đánh dấu `expired`.

## Nguyên tắc cốt lõi — KHÔNG trừ `OnHand`

`sync_products_from_kiotviet()` ghi đè `OnHand` bằng payload thô từ KiotViet mỗi lần full reload buổi sáng. Nếu trừ thẳng `OnHand`, số giữ hàng sẽ bốc hơi lúc 8h sáng — đúng lúc cần nhất. Ngoài ra `OnHand` là số đối chiếu với KiotViet, làm lệch nó sẽ kéo sai ở BanHang và báo cáo.

Vì vậy số giữ hàng nằm ở collection riêng:

```
Tồn hiển thị cho khách = OnHand + CloneOnHandNV − Reserved
                         └ KiotViet ┘ └ clone nội bộ ┘ └ của mình ┘
```

> **Đổi lại 27/09/2026:** cộng lại `CloneOnHandNV` (user chốt: original hết/không đủ thì bán tiếp bằng tồn clone). `_deduct_reserved()` trừ Reserved vào `OnHand` trước, phần dư trừ tiếp vào `CloneOnHandNV`. (18/09–27/09 từng bỏ cộng clone.)
> BanHang chặn thanh toán theo cùng công thức (original + clone − reserved, quy đơn vị gốc) — xem `TapHoa39BanHang/docs/RESERVED-PRODUCTS.md`.

Tiền lệ: `OnHandNV` và `ImageVariant` cũng là field tự tạo và sống sót qua sync nhờ `batch.set(..., merge=True)`.

Hệ quả quan trọng: **"restore OnHand" không tồn tại như một thao tác**. `OnHand` chưa bao giờ bị trừ nên nhả hàng chỉ là đổi `status` của bản ghi — không có rủi ro cộng nhầm hay cộng hai lần.

## Schema

`product_reservations/{orderId}` — doc id chính là orderId, nên đặt lại cùng đơn sẽ ghi đè chứ không nhân đôi số giữ.

| Field | Ý nghĩa |
|---|---|
| `orderId`, `customerName`, `customerPhone` | Đơn và khách giữ hàng |
| `createdAt`, `expiresAt` | ISO. `expiresAt = createdAt + RESERVATION_TTL_HOURS` (24) |
| `status` | `active` / `released` / `expired` |
| `releasedAt`, `releaseReason` | `checked` / `canceled` / `edited` / `expired` |
| `items[]` | `{productId, code, name, quantity}` — gồm cả hàng tặng, vì quà cũng xuất kho |

## Hết hạn: lazy là nguồn đúng, scheduler chỉ để hiển thị

`get_reserved_map()` **chỉ cộng bản ghi còn hạn**. Bản quá hạn coi như không tồn tại ngay lập tức, không cần chờ job. Nhờ vậy dù backend restart, mất điện hay scheduler miss thì số tồn vẫn đúng.

`_schedule_reservation_expiry()` trong `app.py` chạy mỗi giờ chỉ để đổi `status` bản ghi thành `expired` và set đơn `pending` quá hạn thành `status: 'expired'`, cho BanHang/Management hiển thị đúng. Nó **không** ảnh hưởng tới số liệu tồn kho.

Đơn đã `checked` hoặc `canceled` không bị job đụng vào.

## Bốn điểm phải nhả hàng

```
active ──[hủy đơn]──────────> released (canceled)
       ──[sửa đơn]──────────> released (edited) + tạo lại bản mới
       ──[quá 24h]──────────> expired  (lazy, không cần job)
       ──[→ hóa đơn]────────> released (checked)   ← BẮT BUỘC
```

Điểm cuối dễ sót nhất: khi đơn thành hóa đơn, `OnHand` giảm thật qua `updateProductsOnHandFromInvoiceToFireBase(..., 'decrease')`. Nếu bản giữ hàng còn sống, hàng bị **trừ hai lần** → DatHang báo hết hàng trong khi kho còn.

## API

| Endpoint | Dùng cho |
|---|---|
| `GET /api/reservations/stock-map` | BanHang: `{productId: qty}` đang giữ, để chặn thanh toán |
| `GET /api/reservations/active?includeExpired=` | Trang quản lý: danh sách bản giữ hàng |
| `GET /api/reservations/by-product` | Trang quản lý: gom theo SP, kèm các đơn đang giữ nó |
| `POST /api/reservations/release` | `{orderId, reason}` — gọi khi checked/canceled/edited |
| `POST /api/reservations/expire-overdue` | Đánh dấu quá hạn thủ công (scheduler đã tự chạy mỗi giờ) |
| `POST /api/reservations/clear-old` | `{keepDays}` — xoá bản đã đóng cũ hơn N ngày (mặc định 7) |

## Chặn oversell khi đặt đơn

`_recompute_order_economics()` nay kiểm tra tồn khả dụng cho từng dòng hàng:

```
available = OnHand + clone − reserved  ← cả hai đọc FRESH, KHÔNG qua cache
qty > available  →  400 "San pham 'X' chi con N, khong du M"
available <= 0   →  400 "San pham 'X' da het hang"
```

`OnHand` lấy bằng `read_product_fresh()` (bỏ qua cache doc-lẻ TTL 3600s) — dùng `read_product()` thì lớp chặn này so với số cũ tới 1 tiếng. Tồn clone lấy bằng `read_clone_stock_fresh(pid)` (query `CloneSourceId == pid`); lỗi → coi như 0 (chỉ tính KiotViet).

Trước đây `_is_orderable()` chỉ lọc active/deleted/clone/danh mục ẩn, **không hề kiểm tra tồn** — server nhận đơn cả khi hàng đã hết, chặn oversell chỉ nằm ở FE dựa trên IndexedDB có thể cũ.

Nếu `reservation_service` lỗi, `_reserved_map()` trả `{}` — thà hiển thị dư tồn còn hơn chặn cả trang sản phẩm.

## Log chẩn đoán

Khi đơn được tạo, `add_order` in một dòng cho mỗi đơn:

```
[reserve] don DH123: 2 dong gio hang -> 2 dong giu hang (0 dong bo qua: ship/thieu Id)
[Reservation] Ghi product_reservations/DH123: 2 mat hang, het han 2026-09-15T10:20:30
[reserve] don DH123: DA GIU 2 mat hang, het han 2026-09-15T10:20:30
```

Các dòng bất thường cần chú ý:

| Log | Nghĩa |
|---|---|
| `BO QUA - reservation_service = None` | `app.py` không truyền service vào `create_firebase_public_bp` |
| `KHONG giu hang - khong co dong nao hop le` | Mọi dòng đều là ship hoặc thiếu `product.Id` |
| `GIU HANG THAT BAI - ...` | Firestore từ chối ghi (xem thông báo kèm theo) |
| `LOI NGOAI Y - ...` | Exception ngoài dự kiến |

Khi đọc số liệu: `[Reservation] doc product_reservations: N ban giu hang status=active` rồi `reserved map: M san pham`. Nếu N > 0 mà M = 0 thì mọi bản giữ hàng đều đã quá 24h.

**Nếu trang quản lý trống trong khi trang Đơn hàng có đơn:** kiểm tra `createdDate` của đơn. Đơn đặt **trước** khi backend nạp code giữ hàng sẽ không bao giờ có bản ghi — tính năng chỉ áp dụng cho đơn mới. Đây không phải lỗi.

### Đơn mới vẫn không có bản giữ hàng: kiểm tra đơn đến từ backend NÀO

Firestore dùng chung giữa local và production, nên đơn đặt trên **DatHang bản deploy** (`songminhcr.com`, `environment.prod.ts` có `domainUrl: ''` → gọi cùng origin) đi vào backend **VPS**, không qua backend local. Đơn hiện ở trang Đơn hàng nhưng log local không có dòng nào, và nếu VPS chưa deploy code giữ hàng thì không bản ghi nào được tạo.

Dấu vân tay để biết đơn do backend nào tạo — `cartItems[].product` là snapshot `_public_product()`, mà code mới **đã bỏ `Description`**:

```python
p = order['cartItems'][0]['product']
'Description' in p   # True  -> code CŨ (VPS chưa deploy)
                     # False -> code MỚI
```

Kiểm tra nhanh một backend đang chạy code nào:

```bash
curl -s "<host>/api/public/products/featured?limit=1" | grep -c Description   # 0 = code mới
```

Không dùng HTTP 401 trên `/api/reservations/*` để kết luận endpoint có tồn tại hay không: admin gate chạy ở `before_request`, trả 401 cho cả path không tồn tại.

## Backfill đơn cũ

`scripts/backfill_reservations.py` tạo bản giữ hàng bù cho đơn `pending` đặt trước khi tính năng chạy.

```bash
cd TapHoa39BackEnd
python scripts/backfill_reservations.py --dry-run          # chỉ xem
python scripts/backfill_reservations.py                    # có xác nhận
python scripts/backfill_reservations.py --yes              # chạy luôn
python scripts/backfill_reservations.py --max-age-hours 48
```

Ba quy tắc an toàn trong script:

- **Chỉ đơn `pending`.** Đơn `checked` đã thành hóa đơn và trừ `OnHand` thật rồi — giữ hàng nữa là trừ hai lần.
- **Chỉ đơn trong 24h qua** (bằng TTL giữ hàng). Đơn pending từ tháng trước mà giữ hàng thêm 24h là sai nghiệp vụ.
- **`expiresAt` tính từ `createdDate` của đơn thật**, không phải lúc chạy script — đơn đặt 10:20 vẫn hết hạn 10:20 hôm sau.

Bản ghi backfill có cờ `backfilled: true`. Doc id = orderId nên chạy lại nhiều lần không nhân đôi số giữ.

## Lưu ý vận hành

- Tạo bản giữ hàng thất bại **không** làm hỏng đơn đã lưu: đơn vẫn hợp lệ, chỉ là không giữ được chỗ. Lỗi được log để xử lý tay.
- `_reserve_stock_for_order()` chạy **trước** `_deduct_redeemed_points()`: nếu trừ điểm lỗi thì đơn đã lưu vẫn được giữ chỗ, còn thiếu bản giữ hàng thì tồn kho sai cho mọi khách khác.
- Không dùng emoji trong `print` của module này: backend chạy local trên Windows (cp1252), `print` emoji trong khối `except` sẽ ném `UnicodeEncodeError` và che mất lỗi gốc.
- Cache map giữ hàng TTL 60s, tự invalidate khi tạo/nhả.
