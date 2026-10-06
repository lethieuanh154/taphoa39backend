# Chuyển data Firestore sang project Firebase khác

Dùng khi project Firebase cũ hết quota, bị khóa, hoặc cần chuyển sang tài khoản khác.

Lần gần nhất: **2026-09-27**, chuyển project products `products-d8de3` → `products-c22e0`. Đã chạy thành công.

---

## 1. Script có sẵn trong `scripts/`

| Script | Nguồn → Đích | Credentials | Collection mặc định |
|---|---|---|---|
| `migrate_hanghoa_to_product.py` | Hằng `SOURCE_NAME` → `TARGET_NAME` | Dict service account **viết thẳng trong file** (`FIREBASE_SERVICE_ACCOUNT_HANGHOA` = nguồn, `FIREBASE_SERVICE_ACCOUNT_PRODUCT` = đích) | `products` |
| `migrate_hoadon_to_output_invoice.py` | Env `SOURCE_ACCOUNT` → env `TARGET_ACCOUNT` | Đọc `.env` qua `firebase.init_firebase.init_firestore` | `invoices` |

Cả hai script đều có:
- `--dry-run`: chỉ đếm và in 5 document mẫu, không ghi gì.
- `--collection <tên>`: chỉ migrate 1 collection.
- `--all` (chỉ có trong `migrate_hanghoa_to_product.py`): chạy lần lượt danh sách trong `migrate_all_collections()`.

Cách script hoạt động:
- Đọc hết document của collection vào bộ nhớ (`stream()`), rồi ghi sang đích bằng `batch.set()`, mỗi batch 500 document, giữ nguyên doc id.
- Chạy lại nhiều lần không sinh bản trùng. **Không xóa** document nào trên đích mà nguồn không có.
- **Không copy subcollection.** Hiện không collection nào dùng subcollection. Nếu sau này có thì phải sửa script.

> ⚠️ `migrate_hanghoa_to_product.py` chứa `private_key` của service account. **Không commit file này.** Xong việc thì nên xóa key khỏi file.

---

## 2. Project `products` — danh sách collection phải chuyển

Mọi collection bên dưới đều dùng env `FIREBASE_SERVICE_ACCOUNT_PRODUCT`:

| Collection | Nơi dùng trong BE | Số doc (2026-09-27) |
|---|---|---|
| `products` | `firebase/firebase_service/product_service.py` | 16.838 |
| `product_history` | `routes/product_history_routes.py` | 3.661 |
| `product_reservations` | `firebase/firebase_service/reservation_service.py` | 7 |
| `merged_products` | `firebase/firebase_service/merged_products_service.py` | 2 |
| `merged_products_audit` | `firebase/firebase_service/merged_products_audit_service.py` | 1 |
| `app_config` | `product_service.py` (`CONFIG_COLLECTION`, snapshot danh mục) | 1 |

Khi thêm collection mới vào project products → **thêm tên vào `migrate_all_collections()`**, nếu không lần migrate sau sẽ bị sót.

---

## 3. Quy trình (theo đúng thứ tự)

### Bước 0 — Chuẩn bị project đích trên Firebase Console
1. **Firestore Database → Create database**. Giữ tên `(default)`, nên chọn cùng location với project cũ.
   Nếu quên bước này, mọi lệnh gọi sẽ lỗi `404 The database (default) does not exist for project ...`.
2. **Copy Firestore Rules** từ project cũ sang. BanHang và Management đọc `products` trực tiếp từ trình duyệt bằng `onSnapshot`; thiếu rule thì realtime sync không hoạt động.
3. **Project settings → Service accounts → Generate new private key**: lấy JSON cho BE và script.
4. **Project settings → General → Add app (Web)**: lấy config cho FE (`apiKey`, `appId`, `messagingSenderId`, `measurementId`).

### Bước 1 — Sửa script
Trong `scripts/migrate_hanghoa_to_product.py`:
- `FIREBASE_SERVICE_ACCOUNT_HANGHOA` = JSON của project **cũ**
- `FIREBASE_SERVICE_ACCOUNT_PRODUCT` = JSON của project **mới**
- `SOURCE_NAME` / `TARGET_NAME` = project id (chỉ dùng để in log)

### Bước 2 — Dừng ghi vào project cũ
- Dừng BE, gồm cả scheduler tự sync KiotViet 15 phút/lần (`KIOTVIET_AUTO_SYNC_MINUTES`).
- Tạm ngừng bán hàng. Dữ liệu ghi vào project cũ sau lúc migrate sẽ **không có** ở project mới.

### Bước 3 — Chạy migrate
```bash
cd TapHoa39BackEnd
python scripts/migrate_hanghoa_to_product.py --all --dry-run
python scripts/migrate_hanghoa_to_product.py --all      # hỏi xác nhận y/N
```

### Bước 4 — Kiểm tra số document hai bên
```bash
cd TapHoa39BackEnd
python - <<'EOF'
import sys; sys.path.insert(0, 'scripts')
import migrate_hanghoa_to_product as m
src = m.init_firestore_from_dict(m.FIREBASE_SERVICE_ACCOUNT_HANGHOA, "chk_src")
tgt = m.init_firestore_from_dict(m.FIREBASE_SERVICE_ACCOUNT_PRODUCT, "chk_tgt")
for c in ["app_config", "merged_products", "merged_products_audit",
          "product_history", "product_reservations", "products"]:
    a = src.collection(c).count().get()[0][0].value
    b = tgt.collection(c).count().get()[0][0].value
    print(f"{c:24} src={a:>8} tgt={b:>8} {'OK' if a == b else '<-- LECH'}")
EOF
```

### Bước 5 — Đổi cấu hình sang project mới

| Nơi | Chỗ sửa |
|---|---|
| **TapHoa39BackEnd** (local) | `FIREBASE_SERVICE_ACCOUNT_PRODUCT` trong `firebase/.env` |
| **TapHoa39BackEnd** (VPS) | Biến env `FIREBASE_SERVICE_ACCOUNT_PRODUCT` trên VPS |
| **TapHoa39BanHang** | **Toàn bộ** khối `firebaseProducts` trong `src/environments/environment.ts` và `environment.prod.ts` |
| **TapHoa39Management** | **Toàn bộ** khối `firebaseProducts` trong `src/environments/environment.ts` và `environment.prod.ts` |
| TapHoa39DatHang | Không cần sửa: app này chỉ gọi qua BE |

- FE phải thay cả khối config, không chỉ `projectId`. `apiKey`, `appId` và `messagingSenderId` khác nhau giữa các project.
- `firestore-realtime.service.ts` giống hệt nhau ở BanHang và Management (vùng mirror). Nó đọc `environment.firebaseProducts`.

Kiểm tra không còn chỗ nào trỏ về project cũ:
```bash
grep -rn "<old-project-id>" --include=*.ts --include=*.py --include=.env* \
  TapHoa39BackEnd TapHoa39BanHang/src TapHoa39Management/src TapHoa39DatHang/src
```

### Bước 6 — Deploy và bật lại
1. `python -m scripts.smoke_boot` (phải exit 0).
2. Build BanHang và Management.
3. Deploy BE, Management và DatHang lên VPS. BanHang chạy local.
4. Bật BE lại, mở BanHang để kiểm tra realtime sync sản phẩm.

---

## 4. Lỗi thường gặp

| Lỗi | Nguyên nhân |
|---|---|
| `404 The database (default) does not exist` | Chưa tạo Firestore database ở project đích (Bước 0.1) |
| FE không nhận cập nhật sản phẩm realtime | Thiếu Firestore Rules, hoặc `firebaseProducts` còn trỏ project cũ |
| Thiếu data sau khi chuyển | Có ghi vào project cũ trong lúc migrate (chưa dừng BE/scheduler), hoặc collection mới chưa có trong `migrate_all_collections()` |

## 5. Migrate project khác (không phải products)

Dùng `migrate_hoadon_to_output_invoice.py` làm mẫu: đổi `SOURCE_ACCOUNT`/`TARGET_ACCOUNT` thành tên biến env trong `firebase/.env`. Cách này không phải viết key vào file.
Danh sách env service account hiện có trong `firebase/.env`: `CUSTOMER`, `HOADON`, `NHANVIEN`, `SUPPLIES_INVOICES`, `PRODUCT`, `OUTPUT_INVOICE`, `GMAIL`, `DATHANG` (tiền tố `FIREBASE_SERVICE_ACCOUNT_`).

## 6. Khôi phục dữ liệu ghi nhầm vào project cũ sau khi migrate

Sự cố 28–29/09/2026: BE local ở cửa hàng chưa đổi `.env`, nên vẫn ghi vào `products-d8de3` tới tối 29/09. Script khôi phục: `scripts/recover_products_from_old_project.py`.

- Lấy các doc `products` ở project cũ có `ModifiedDate` trong khoảng `--from-date` → `--to-date` (giờ VN; mặc định từ 27/09 13:00, ngay sau snapshot migrate, tới 29/09 18:41, lúc đổi env), rồi phân loại:
  - Hàng KiotViet gốc: bỏ qua.
  - `CREATE`: tạo mới.
  - `SKIP_RECLONED`: đã clone lại ở project mới nên bỏ qua.
  - `OVERWRITE`: project mới chưa sửa doc, merge từ bản cũ.
  - `CONFLICT_*`: sửa ở cả hai bên. Tồn đề xuất = cũ + (mới − base), base lấy từ `product_history`. Chỉ ghi khi chạy `--apply-conflicts` và trạng thái là `AUTO`/`AUTO_CHILD`.
- Gộp `product_history` (hợp các record, giữ 100 record mới nhất).
- Mặc định là dry-run và xuất CSV vào `scripts/recover_reports/`. `--apply` mới ghi thật: có backup trước khi ghi, và transaction chặn ghi đè nếu doc vừa bị đổi. Các doc được ghi sẽ có `ModifiedDate` = thời điểm khôi phục.
- Sau khi ghi: restart BE, rồi full reload BanHang trên mọi máy.
- **Bài học:** lúc chụp dữ liệu để migrate phải đổi env và restart **mọi** BE (cả local ở cửa hàng lẫn VPS) cùng một lúc.
