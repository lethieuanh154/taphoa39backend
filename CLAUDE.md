# TapHoa39BackEnd

Flask REST API backend cho ung dung quan ly ban le TapHoa39.

## Tech Stack
- Flask 3.1.0, Firebase Firestore, Flask-SocketIO, Google Gemini AI, KiotViet API

## Architecture
```
HTTP Request → routes/*.py → services/*.py → firebase/firebase_service/*.py → Firestore/KiotViet
```

## Key Directories
- `routes/` - Flask blueprints (API endpoints)
- `firebase/firebase_service/` - Firestore CRUD services + cache
- `firebase/firebase_hanghoa/` - Product management (import, clone detection)
- `firebase/firebase_hoadon/` - Invoice management
- `services/` - Business logic (ai_extractor, invoice_parsers, ocr_engine)
- `FromKiotViet/` - KiotViet API integration
- `models/` - Pydantic data models

## Critical Rules
- Clone detection: `isClone=true` OR `(OnHandNV > 0 AND OnHand == 0)` - must match frontend
- Product cache: TTL=1h, use `_smart_invalidate_product()` for single writes, `invalidate_all_product_caches()` only for batch/sync
- KiotViet Name vs FullName: `Name`=base name, `FullName`=full with attrs+unit
- XML invoice parser: 5 vendor formats (A1-TH Milk, A2-Vinamilk, B-MISA, C-Vinh An, D-Nguyen Thinh) - see `docs/INVOICE-XML-FORMATS.md`

## Docs
- `docs/PROJECT-STRUCTURE.md` - Full project structure + API endpoints
- `docs/EMPLOYEE-API.md` - Employee/schedule/payroll API docs
- `docs/FIRESTORE-SCHEMA.md` - Invoice Firestore schema design
- `docs/INVOICE-XML-FORMATS.md` - XML parser vendor formats (CRITICAL domain knowledge)

## Doc Maintenance Rule
Khi thay doi code lien quan den logic/architecture/API/model, PHAI update file .md tuong ung trong `docs/`.
- Thay doi route/API → update `docs/PROJECT-STRUCTURE.md` hoac `docs/EMPLOYEE-API.md`
- Thay doi Firestore schema → update `docs/FIRESTORE-SCHEMA.md`
- Thay doi XML parser/vendor → update `docs/INVOICE-XML-FORMATS.md`
- Thay doi critical rules (clone detection, cache, KiotViet naming) → update CLAUDE.md
- Neu tao file/service/route moi → them vao doc tuong ung
- Neu xoa file/feature → xoa khoi doc tuong ung
