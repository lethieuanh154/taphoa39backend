# FIRESTORE SCHEMA - INVOICE MANAGEMENT SYSTEM
# Thiết kế cho 100.000+ hóa đơn với query tối ưu

## 1. Collection: `invoices`

Thay thế `tax_invoices` và `internal_invoices` bằng 1 collection duy nhất.

```
/invoices/{invoiceId}
{
    // === KHÓA CHÍNH (để đối chiếu) ===
    invoiceKey: string          // "{invoiceNo}|{supplierTaxCode}" - unique key

    // === THÔNG TIN HÓA ĐƠN ===
    invoiceNo: string           // Số hóa đơn (e.g., "00000123")
    invoiceSymbol: string       // Ký hiệu (e.g., "1C24TAA")

    // === NHÀ CUNG CẤP ===
    supplierName: string        // Tên NCC
    supplierTaxCode: string     // MST NCC (indexed)
    supplierAddress: string     // Địa chỉ NCC

    // === NGƯỜI MUA ===
    buyerName: string           // Tên người mua
    buyerTaxCode: string        // MST người mua

    // === NGÀY THÁNG (QUAN TRỌNG CHO FILTER) ===
    issueDate: Timestamp        // Ngày lập hóa đơn (Firestore Timestamp)
    issueDateKey: string        // "YYYY-MM-DD" (indexed, để filter nhanh)
    monthKey: string            // "YYYY-MM" (indexed, để filter theo tháng)
    year: number                // 2024, 2025, 2026... (indexed)

    // === SỐ TIỀN ===
    totalBeforeVat: number      // Tiền hàng trước thuế
    vatRate: number             // % thuế (0, 5, 8, 10)
    vatAmount: number           // Tiền thuế
    totalAmount: number         // Tổng thanh toán

    // === NGUỒN DỮ LIỆU ===
    source: string              // "TAX_PORTAL" | "AI_PDF" (indexed)

    // === TRẠNG THÁI ĐỐI CHIẾU ===
    reconcileStatus: string     // "PENDING" | "MATCHED" | "UNMATCHED" | "MISMATCH"
    matchedInvoiceId: string    // ID của hóa đơn đối chiếu (nếu có)

    // === METADATA ===
    createdAt: Timestamp        // Thời điểm import
    updatedAt: Timestamp        // Thời điểm cập nhật

    // === CHI TIẾT HÀNG HÓA (chỉ lưu với source=AI_PDF) ===
    items: [
        {
            name: string,
            unit: string,
            quantity: number,
            unitPrice: number,
            amount: number
        }
    ]
}
```

### Giải thích các trường key:

| Trường | Mục đích |
|--------|----------|
| `invoiceKey` | Unique key để detect duplicate và đối chiếu |
| `issueDateKey` | Query theo range ngày: `>= "2024-01-01"` |
| `monthKey` | Query theo tháng: `== "2024-12"` |
| `year` | Query theo năm: `== 2024` |
| `source` | Phân biệt dữ liệu từ thuế vs AI |
| `reconcileStatus` | Tracking trạng thái đối chiếu |

---

## 2. Collection: `suppliers` (Optional - để tối ưu filter)

```
/suppliers/{supplierTaxCode}
{
    taxCode: string             // MST (document ID)
    name: string                // Tên NCC
    address: string             // Địa chỉ

    // Stats
    invoiceCount: number        // Số lượng hóa đơn
    totalAmount: number         // Tổng giá trị
    lastInvoiceDate: Timestamp  // Hóa đơn gần nhất

    // Metadata
    createdAt: Timestamp
    updatedAt: Timestamp
}
```

### Lợi ích:
- Dropdown NCC load nhanh (chỉ query collection nhỏ)
- Không cần aggregate từ `invoices`
- Auto-complete search

---

## 3. Collection: `sync_logs` (Audit trail)

```
/sync_logs/{logId}
{
    action: string              // "IMPORT" | "DELETE" | "RECONCILE"
    source: string              // "TAX_PORTAL" | "AI_PDF"

    // Stats
    totalProcessed: number
    successCount: number
    failCount: number
    duplicateCount: number

    // Metadata
    userId: string              // (optional) Người thực hiện
    createdAt: Timestamp
    details: string             // Thông tin chi tiết
}
```

---

## 4. COMPOSITE INDEXES CẦN TẠO

Tạo file `firestore.indexes.json`:

```json
{
  "indexes": [
    {
      "collectionGroup": "invoices",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "year", "order": "ASCENDING" },
        { "fieldPath": "issueDate", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "invoices",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "monthKey", "order": "ASCENDING" },
        { "fieldPath": "issueDate", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "invoices",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "source", "order": "ASCENDING" },
        { "fieldPath": "issueDate", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "invoices",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "source", "order": "ASCENDING" },
        { "fieldPath": "monthKey", "order": "ASCENDING" },
        { "fieldPath": "issueDate", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "invoices",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "supplierTaxCode", "order": "ASCENDING" },
        { "fieldPath": "issueDate", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "invoices",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "reconcileStatus", "order": "ASCENDING" },
        { "fieldPath": "issueDate", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "invoices",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "source", "order": "ASCENDING" },
        { "fieldPath": "year", "order": "ASCENDING" },
        { "fieldPath": "issueDate", "order": "DESCENDING" }
      ]
    }
  ],
  "fieldOverrides": [
    {
      "collectionGroup": "invoices",
      "fieldPath": "issueDate",
      "indexes": [
        { "order": "ASCENDING", "queryScope": "COLLECTION" },
        { "order": "DESCENDING", "queryScope": "COLLECTION" }
      ]
    },
    {
      "collectionGroup": "invoices",
      "fieldPath": "supplierTaxCode",
      "indexes": [
        { "order": "ASCENDING", "queryScope": "COLLECTION" }
      ]
    }
  ]
}
```

---

## 5. VÍ DỤ QUERY CHO TỪNG FILTER

### 5.1 Default: 30 ngày gần nhất (limit 50)
```python
from datetime import datetime, timedelta

start_date = datetime.now() - timedelta(days=30)

query = db.collection('invoices') \
    .where('issueDate', '>=', start_date) \
    .order_by('issueDate', direction='DESCENDING') \
    .limit(50)
```

### 5.2 Filter theo tháng
```python
# Lấy hóa đơn tháng 12/2024
query = db.collection('invoices') \
    .where('monthKey', '==', '2024-12') \
    .order_by('issueDate', direction='DESCENDING') \
    .limit(50)
```

### 5.3 Filter theo năm
```python
# Lấy hóa đơn năm 2024
query = db.collection('invoices') \
    .where('year', '==', 2024) \
    .order_by('issueDate', direction='DESCENDING') \
    .limit(50)
```

### 5.4 Filter theo nguồn (TAX_PORTAL hoặc AI_PDF)
```python
# Lấy hóa đơn từ trang thuế, tháng 12/2024
query = db.collection('invoices') \
    .where('source', '==', 'TAX_PORTAL') \
    .where('monthKey', '==', '2024-12') \
    .order_by('issueDate', direction='DESCENDING') \
    .limit(50)
```

### 5.5 Filter theo nhà cung cấp
```python
# Lấy hóa đơn từ NCC có MST cụ thể
query = db.collection('invoices') \
    .where('supplierTaxCode', '==', '0123456789') \
    .order_by('issueDate', direction='DESCENDING') \
    .limit(50)
```

### 5.6 Pagination với cursor
```python
# Trang đầu
first_page = db.collection('invoices') \
    .where('monthKey', '==', '2024-12') \
    .order_by('issueDate', direction='DESCENDING') \
    .limit(50) \
    .get()

# Lấy document cuối cùng làm cursor
last_doc = first_page[-1] if first_page else None

# Trang tiếp theo
if last_doc:
    next_page = db.collection('invoices') \
        .where('monthKey', '==', '2024-12') \
        .order_by('issueDate', direction='DESCENDING') \
        .start_after(last_doc) \
        .limit(50) \
        .get()
```

---

## 6. TẠI SAO THIẾT KẾ NÀY SCALE ĐƯỢC?

### 6.1 Không full scan
- Mọi query đều dùng indexed fields
- Firestore chỉ đọc đúng documents cần thiết

### 6.2 Chi phí thấp
- Chỉ trả tiền cho documents thực sự đọc
- Limit 50 = tối đa 50 reads/request

### 6.3 Latency thấp
- Index sẵn có → query <100ms
- Không cần aggregate on-the-fly

### 6.4 Sẵn sàng đối chiếu
- `invoiceKey` giúp match nhanh
- `reconcileStatus` track trạng thái
- Query theo source để so sánh

### 6.5 Ước tính chi phí (100.000 hóa đơn)
- Storage: ~100MB (cheap)
- Reads: 50 docs/page × 1000 pages/ngày = 50.000 reads/ngày
- Firestore free tier: 50.000 reads/ngày
- → Gần như FREE với cách dùng này

---

## 7. MIGRATION STRATEGY

### Bước 1: Tạo collection mới `invoices`
### Bước 2: Migrate data từ `tax_invoices` → `invoices` (source='TAX_PORTAL')
### Bước 3: Migrate data từ `internal_invoices` → `invoices` (source='AI_PDF')
### Bước 4: Cập nhật API để dùng collection mới
### Bước 5: (Optional) Xóa collections cũ sau khi verify
