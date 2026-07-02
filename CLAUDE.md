# TapHoa39BackEnd

Flask REST API backend. Tech: Flask 3.1.0, Firebase Firestore, Flask-SocketIO, Google Gemini AI, KiotViet API.

## Architecture
`HTTP Request → routes/*.py → services/*.py → firebase/firebase_service/*.py → Firestore/KiotViet`

## Key Directories
- `routes/` - API endpoints | `services/` - Business logic (ai, invoice parsers, OCR)
- `firebase/firebase_service/` - Firestore CRUD + cache | `firebase/firebase_hanghoa/` - Products
- `firebase/firebase_hoadon/` - Invoices | `FromKiotViet/` - KiotViet API | `models/` - Pydantic

## Critical Rules
- Product cache: TTL=1h, `_smart_invalidate_product()` for single, `invalidate_all_product_caches()` for batch/sync
- XML invoice: 6 formats (A1-TH Milk, A2-Vinamilk, B-MISA, C-Vinh An, D-Nguyen Thinh, E-chỉ TSuat, F-có chiết khấu STCKhau) → `docs/INVOICE-XML-FORMATS.md`
- XML parser chính: `services/invoice_parsers.py` (route `/v1/parse-xml`), KHÔNG phải `firebase/firebase_invoices/tax_invoice_xml_parser.py`

## Docs
`docs/`: PROJECT-STRUCTURE, EMPLOYEE-API, FIRESTORE-SCHEMA, INVOICE-XML-FORMATS
