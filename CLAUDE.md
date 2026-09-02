# TapHoa39BackEnd

Flask REST API backend. Tech: Flask 3.1.0, Firebase Firestore, Flask-SocketIO, Google Gemini AI, KiotViet API.

## Architecture
`HTTP Request → routes/*.py → services/*.py → firebase/firebase_service/*.py → Firestore/KiotViet`

## Key Directories
- `routes/` - API endpoints | `services/` - Business logic (ai, invoice parsers, OCR)
- `firebase/firebase_service/` - Firestore CRUD + cache | `firebase/firebase_hanghoa/` - Products
- `firebase/firebase_hoadon/` - Invoices | `FromKiotViet/` - KiotViet API | `models/` - Pydantic

## Critical Rules
- **gunicorn PHẢI `--workers=1`** (Dockerfile CMD + startup.sh). `SocketIO()` trong app.py khởi tạo KHÔNG có `message_queue` → state socket nằm trong RAM từng worker. >1 worker thì `broadcast_products_onhand_updated()` chỉ tới client nối vào đúng worker xử lý request → máy này nhận update tồn kho, máy kia không. Muốn scale phải thêm Redis `message_queue` trước. Lưu ý gunicorn đọc env `WEB_CONCURRENCY` nếu thiếu cờ `--workers`
- **Mọi lệnh gọi Firestore phục vụ request web PHẢI có `timeout=`.** Không deadline thì khi kênh gRPC chết lặng (hay xảy ra sau nhiều giờ nhàn rỗi) lệnh gọi treo vĩnh viễn và **giữ luôn thread gunicorn**. Mỗi request sau mất thêm một thread, cạn pool là toàn bộ API tắt thở — kể cả `/v1/health` là JSON tĩnh. Đã xảy ra 31/08/2026: khách quét QR, `get_invoice_by_public_token()` không deadline, sau vài lần quét thì backend treo hẳn (nginx 504, `curl 127.0.0.1:8001` cũng treo, CPU 5%, RAM 202MiB — tức không phải crash hay OOM). Đã đặt `FIRESTORE_TIMEOUT = 10` cho đường `/hd/` và `services/provisional_invoices.py`; **các service khác vẫn còn nguyên rủi ro này**.
- **`--threads` là ngân sách kết nối long-poll, không phải ngân sách CPU.** Mỗi client Socket.IO đang mở giữ **một thread** suốt thời gian chờ gói (tới `pingInterval` 25s), và client bỏ ngang thì thread còn kẹt tới hết `pingTimeout` (60s). Hết thread thì gunicorn không nhận thêm request nào — **kể cả `/v1/health` là JSON tĩnh cũng timeout**, nginx trả 504 cho mọi thứ. Đã xảy ra một lần vì app Android dựng lại socket ở mọi `AppLifecycleState.resumed`, mỗi lần bỏ lại một phiên mồ côi. Triệu chứng phân biệt: 504 (treo) chứ không phải 502 (container chết), và `songminhcr.com/` tĩnh vẫn 200. Client PHẢI tái sử dụng kết nối thay vì dựng lại.
- **Credentials KiotViet nam o 4 file, PHAI dong bo**: `TapHoa39BackEnd/.env`, `TapHoa39BackEnd/run.sh`, `TapHoa39BanHang/run.sh`, `TapHoa39Management/run.sh` (+ env tren VPS). `load_dotenv()` KHONG ghi de env san co → chay bang `run.sh` thi run.sh thang, chay `python app.py` tran thi `.env` thang. Da tung lech ca `Password` (`LAMBInh123@` vs `LAMBinh123@`) lan `retailer` (`songminhcr` vs `taphoa39dn`) → login tra **200 nhung token rong** → `get_category()`/`get_all()` = None → `/api/kiotviet/*` tra 502 → DatHang mat sach thanh danh muc. Trieu chung nhan dang: log `[AUTH] KiotViet login 200 but empty token`.
- **Danh muc co snapshot du phong**: `ProductService.read_categories()` lay tu KiotViet (cache 6h) roi **ghi snapshot xuong `app_config/categories`**; KiotViet chet thi doc snapshot cu. Dung cho `/api/public/categories` → DatHang khong con phu thuoc KiotViet song hay chet.
- Product cache: TTL=1h, `_smart_invalidate_product()` for single, `invalidate_all_product_caches()` for batch/sync
- XML invoice: 8 formats (A1-TH Milk, A2-Vinamilk, B-MISA, C-Vinh An, D-Nguyen Thinh, E-chỉ TSuat, F-CK chưa trừ, G-CK đã trừ sẵn, H-Mixed KKKNT) → `docs/INVOICE-XML-FORMATS.md`
- XML parser chính: `services/invoice_parsers.py` (route `/v1/parse-xml`), KHÔNG phải `firebase/firebase_invoices/tax_invoice_xml_parser.py`
- **Hóa đơn TẠM TÍNH nằm ở collection `provisional_invoices`, TUYỆT ĐỐI không phải `invoices`** (`services/provisional_invoices.py`). Mọi bản ghi trong `invoices` đều được coi là doanh thu thật (`adjust_invoice_summaries`, `apply_invoice_delta`, số liệu KeToan); hóa đơn tạm có thể bị bỏ giữa chừng nên lọt vào đó là cộng khống doanh thu. Mỗi bản ghi mang `provisionalDay` (ngày giờ VN); đọc/ghi đều lọc theo hôm nay và `_maybe_purge()` dọn ngày cũ một lần mỗi ngày — hóa đơn tạm không bao giờ sống sang hôm sau. `add_invoice` tự gỡ bản tạm cùng id. **Đã thử giữ trong RAM và phải đổi**: máy POS chạy Flask local còn điện thoại khách chạy 4G mở `/hd/` qua VPS, nên bản trong RAM máy POS không tra được → khách quét QR ra 404.
- **Dấu thời gian gửi cho FE phải là giờ VN KHÔNG kèm offset** (`YYYY-MM-DDTHH:mm:ss.SSS`), khớp `formatVietnamISOString()` bên BanHang. Kèm `+07:00` thì `DateTime.parse` của Flutter ra giờ UTC và app hiện lệch 7 tiếng.
- **Trang hóa đơn điện tử `/hd/*`** (`routes/invoice_public.py`): render HTML server-side cho khách quét QR. KHÔNG dưới `/api/` nên không bị admin gate — chủ đích, khách không có tài khoản cửa hàng. Bảo vệ bằng `publicToken` ngẫu nhiên (invoice id đoán được, tuyệt đối không dùng làm link). → `docs/INVOICE-PUBLIC-PAGE.md`

- **Truoc khi deploy PHAI chay `python -m scripts.smoke_boot`** (exit 0 moi duoc deploy). No dung app that voi Firestore gia, bat duoc ten undefined va loi import — nhung thu `py_compile`/`ast.parse` khong thay, va chi lo ra khi container khoi dong, luc do ca he thong da 502. Da tung xay ra: xoa nham `db = init_firestore(...)` khi don code khien backend sap hoan toan.

## Docs
`docs/`: PROJECT-STRUCTURE, EMPLOYEE-API, FIRESTORE-SCHEMA, INVOICE-XML-FORMATS, PUBLIC-API, INVOICE-PUBLIC-PAGE
`scripts/smoke_boot.py`: kiem tra khoi dong truoc khi deploy
