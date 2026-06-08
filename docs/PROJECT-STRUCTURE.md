# TapHoa39BackEnd - Cấu Trúc Dự Án

## Tổng Quan

**TapHoa39BackEnd** là REST API backend Python Flask cho ứng dụng quản lý bán lẻ TapHoa39. Hệ thống tích hợp Firebase để lưu trữ dữ liệu, KiotViet API để đồng bộ kho hàng, và Gemini AI để xử lý hóa đơn tự động.

---

## Công Nghệ Sử Dụng

| Thành phần | Công nghệ |
|------------|-----------|
| Framework | Flask 3.1.0 |
| Database | Firebase Firestore |
| Real-time | Flask-SocketIO |
| AI/ML | Google Gemini 3, EasyOCR |
| POS Integration | KiotViet API |
| Deployment | Docker, Gunicorn |
| Validation | Pydantic |

---

## Cấu Trúc Thư Mục

```
TapHoa39BackEnd/
├── app.py                          # Entry point chính - Flask app initialization
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Docker configuration
├── .env                            # Biến môi trường (credentials, API keys)
│
├── firebase/                       # Tích hợp Firebase
│   ├── init_firebase.py            # Khởi tạo Firebase
│   ├── firebase_auth/              # Authentication services
│   ├── firebase_service/           # Firestore service classes
│   │   ├── product_service.py      # CRUD sản phẩm
│   │   ├── customer_service.py     # CRUD khách hàng
│   │   ├── invoice_service.py      # CRUD hóa đơn
│   │   ├── employee_service.py     # CRUD nhân viên, chấm công, lương
│   │   ├── order_service.py        # CRUD đơn hàng
│   │   └── cache.py                # TTL-based caching
│   ├── firebase_hanghoa/           # Quản lý hàng hóa
│   ├── firebase_hoadon/            # Quản lý hóa đơn
│   └── firebase_khachhang/         # Quản lý khách hàng
│
├── routes/                         # Flask blueprints - API endpoints
│   ├── firebase_products.py        # /api/firebase/...products
│   ├── firebase_customers.py       # /api/firebase/...customers
│   ├── firebase_invoices.py        # /api/firebase/...invoices
│   ├── firebase_employees.py       # /api/firebase/...employees
│   ├── firebase_orders.py          # /api/firebase/...orders
│   ├── firebase_merged_products.py  # /api/firebase/merged-products
│   ├── firebase_websocket.py       # WebSocket handlers
│   ├── invoice_processing.py       # /api/invoice/... (OCR/AI processing)
│   ├── auth_routes.py              # /api/auth/...
│   ├── kiotviet_routes.py          # /api/kiotviet/...
│   ├── sync_routes.py              # /api/sync/...
│   ├── shared.py                   # Common utilities, error handlers
│   └── static_routes.py            # Static content
│
├── services/                       # Business logic services
│   ├── ai_extractor.py             # Gemini AI invoice extraction
│   ├── invoice_parsers.py          # **Parser XML chính** (TaxInvoiceXMLParser - dùng cho /v1/parse-xml)
│   ├── ocr_engine.py               # EasyOCR wrapper
│   ├── invoice_validator.py        # Invoice validation logic
│   └── config.py                   # Configuration management
│
├── models/                         # Pydantic data models
│   └── invoice.py                  # Invoice data structures
│
├── FromKiotViet/                   # KiotViet API integration
│   ├── get_authorization.py        # OAuth authentication
│   ├── get_entire_product.py       # Fetch products
│   ├── Model/                      # Data models
│   │   ├── product.py
│   │   └── customer.py
│   └── [other operations]
│
├── Utility/                        # Helper utilities
│   └── get_env.py                  # Environment variable helpers
│
└── Documentation/
    ├── EMPLOYEE_API_DOCS.md        # Employee API documentation
    └── GEMINI.md                   # Gemini/AI integration guide
```

---

## Kiến Trúc Hệ Thống

```
HTTP Request → Flask Routes (routes/*.py)
       ↓
Services (services/*.py) + Business Logic
       ↓
Data Access Layer (firebase/firebase_service/*.py)
       ↓
Firebase Firestore / KiotViet API
```

---

## API Endpoints

| Prefix | Module | Chức năng |
|--------|--------|-----------|
| `/api/firebase/` | firebase_products.py | CRUD sản phẩm, batch updates |
| `/api/firebase/` | firebase_customers.py | Quản lý khách hàng |
| `/api/firebase/` | firebase_invoices.py | Quản lý hóa đơn |
| `/api/firebase/` | firebase_employees.py | Nhân viên, chấm công, lương |
| `/api/firebase/` | firebase_orders.py | Quản lý đơn hàng |
| `/api/firebase/merged-products` | firebase_merged_products.py | Merged products, auto-merge history (GET/POST/DELETE) |
| `/api/kiotviet/` | kiotviet_routes.py | Đồng bộ KiotViet |
| `/api/sync/` | sync_routes.py | Data synchronization |
| `/api/auth/` | auth_routes.py | Authentication |
| `/api/invoice/` | invoice_processing.py | Xử lý hóa đơn AI |

---

## Firestore Collections

| Collection | Service | Mô tả |
|------------|---------|-------|
| `products` | product_service.py | Danh sách sản phẩm |
| `customers` | customer_service.py | Thông tin khách hàng |
| `invoices` | invoice_service.py | Hóa đơn bán hàng |
| `employeeList` | employee_service.py | Danh sách nhân viên |
| `workSchedule` | employee_service.py | Lịch làm việc |
| `timeSheet` | employee_service.py | Bảng chấm công |
| `payroll` | employee_service.py | Bảng lương |
| `orders` | order_service.py | Đơn hàng |

---

## Invoice Processing Pipeline (AI)

```
PDF Upload
    ↓
OCR Engine (EasyOCR) - Trích xuất text
    ↓
Gemini Flash Model - Extraction nhanh
    ↓
Invoice Validator - Kiểm tra dữ liệu
    ↓
Nếu lỗi → Gemini Pro Model - Re-extraction chính xác
    ↓
Return Structured Data (JSON)
```

---

## Biến Môi Trường (.env)

```env
e=local                                    # Environment
KIOTVIET_USER=...                          # KiotViet credentials
KIOTVIET_PASSWORD=...
KIOTVIET_RETAILER=...
GEMINI_API_KEY=...                         # Google Gemini API
GEMINI_FLASH_MODEL=gemini-1.5-flash
GEMINI_PRO_MODEL=gemini-1.5-pro
OCR_LANGUAGES=vi,en
OCR_GPU=False

# Firebase Service Accounts (JSON strings)
FIREBASE_SERVICE_ACCOUNT_HANGHOA=...
FIREBASE_SERVICE_ACCOUNT_CUSTOMER=...
FIREBASE_SERVICE_ACCOUNT_HOADON=...
FIREBASE_SERVICE_ACCOUNT_NHANVIEN=...
```

---

## Chạy Ứng Dụng

```bash
# Development
flask run

# Production
gunicorn app:app --bind 0.0.0.0:8000

# Docker
docker build -t taphoa39backend .
docker run -p 5000:5000 taphoa39backend
```

---

## Tính Năng Chính

1. **Quản lý sản phẩm** - CRUD, filtering, grouping, inventory sync
2. **Quản lý khách hàng** - Thông tin, lịch sử mua hàng
3. **Quản lý hóa đơn** - Tạo, cập nhật, truy vấn
4. **Quản lý nhân viên** - HR, chấm công, lương
5. **Đồng bộ KiotViet** - Sync sản phẩm, khách hàng real-time
6. **Xử lý hóa đơn AI** - OCR + Gemini extraction
7. **WebSocket** - Real-time updates qua Socket.IO
8. **Caching** - TTL-based in-memory cache với smart invalidation

---

## Ghi Chú Kỹ Thuật

- **Blueprint-based Routing**: Mỗi feature có blueprint riêng
- **Service Layer**: Business logic tách biệt khỏi routes
- **Pydantic Validation**: Type-safe data models
- **Error Handling**: Decorator-based trong `shared.py`
- **WebSocket**: Polling transport (không dùng native WebSocket)

---

## Product Cache Architecture

### Cache Strategy
- **TTL**: 1 giờ (`CACHE_TTL = 3600`) cho tất cả product cache
- **Background refresh**: Mỗi 55 phút tự động refresh cache trước khi TTL hết hạn (trong `app.py`)
- **Warmup on startup**: Cache được load sẵn khi server start để tránh cold start

### Smart Invalidation (`_smart_invalidate_product`)
Khi update/delete 1 product, KHÔNG invalidate toàn bộ cache (tránh full collection scan 15k docs).
Thay vào đó, patch cache in-place:

| Hành động | Cache xử lý |
|-----------|-------------|
| Update product | Patch product trong `all_products` lists, invalidate category liên quan |
| Delete product | Remove product khỏi `all_products` lists, invalidate featured + category |
| Add product | Add vào `all_products` lists, invalidate featured + category |
| Stock change | Invalidate `clone_stock_map` |

### Full Invalidation (`invalidate_all_product_caches`)
Chỉ dùng cho:
- KiotViet full sync (`sync_products_from_kiotviet`)
- Batch add products
- Cleanup deleted products
- Explicit refresh (`/products/fetch?all=true`)

### Cache Keys
| Key pattern | TTL | Mô tả |
|-------------|-----|-------|
| `all_products:inactive={bool}:deleted={bool}` | 1h | Toàn bộ products (filtered) |
| `{product_id}` | 1h | Single product by ID |
| `products_by_category:{id}:inactive={bool}` | 1h | Products theo category |
| `featured_products:{limit}` | 1h | Featured products (DatHang) |
| `clone_stock_map` | 1h | Map clone stock cho DatHang enrichment |

### Files liên quan
- `firebase/firebase_service/cache.py` - Cache class với `update_item_in_lists()`, `remove_item_from_lists()`, `add_item_to_lists()`
- `firebase/firebase_service/product_service.py` - `CACHE_TTL`, `_smart_invalidate_product()`, `invalidate_all_product_caches()`
- `app.py` - `_warmup_product_cache()` với background refresh thread

---

*Cập nhật lần cuối: 2026-03-17*
