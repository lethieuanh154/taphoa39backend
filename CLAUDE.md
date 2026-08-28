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
- Product cache: TTL=1h, `_smart_invalidate_product()` for single, `invalidate_all_product_caches()` for batch/sync
- XML invoice: 8 formats (A1-TH Milk, A2-Vinamilk, B-MISA, C-Vinh An, D-Nguyen Thinh, E-chỉ TSuat, F-CK chưa trừ, G-CK đã trừ sẵn, H-Mixed KKKNT) → `docs/INVOICE-XML-FORMATS.md`
- XML parser chính: `services/invoice_parsers.py` (route `/v1/parse-xml`), KHÔNG phải `firebase/firebase_invoices/tax_invoice_xml_parser.py`
- **Trang hóa đơn điện tử `/hd/*`** (`routes/invoice_public.py`): render HTML server-side cho khách quét QR. KHÔNG dưới `/api/` nên không bị admin gate — chủ đích, khách không có tài khoản cửa hàng. Bảo vệ bằng `publicToken` ngẫu nhiên (invoice id đoán được, tuyệt đối không dùng làm link). → `docs/INVOICE-PUBLIC-PAGE.md`

- **Truoc khi deploy PHAI chay `python -m scripts.smoke_boot`** (exit 0 moi duoc deploy). No dung app that voi Firestore gia, bat duoc ten undefined va loi import — nhung thu `py_compile`/`ast.parse` khong thay, va chi lo ra khi container khoi dong, luc do ca he thong da 502. Da tung xay ra: xoa nham `db = init_firestore(...)` khi don code khien backend sap hoan toan.

## Docs
`docs/`: PROJECT-STRUCTURE, EMPLOYEE-API, FIRESTORE-SCHEMA, INVOICE-XML-FORMATS, PUBLIC-API, INVOICE-PUBLIC-PAGE
`scripts/smoke_boot.py`: kiem tra khoi dong truoc khi deploy
