# Firebase Invoices - XML Parser

## Tổng quan

Module xử lý hóa đơn điện tử (e-invoice) từ nhiều nguồn phần mềm khác nhau. Parser chính nằm ở 2 file:

- `firebase/firebase_invoices/tax_invoice_xml_parser.py` - Parser cũ/backup (KHÔNG dùng cho route `/v1/parse-xml`)
- **`services/invoice_parsers.py`** - **Parser chính** (dùng cho route `/v1/parse-xml` qua `routes/invoice_processing.py`)

**QUAN TRỌNG**: Route `/v1/parse-xml` import từ `services/invoice_parsers.py`, KHÔNG phải `firebase/firebase_invoices/tax_invoice_xml_parser.py`. Khi fix bug parse XML, luôn sửa file `services/invoice_parsers.py` trước.

## Cấu trúc XML hóa đơn điện tử

```xml
<HDon>
  <DLHDon>
    <TTChung>          <!-- Thông tin chung: số HD, ngày lập, ký hiệu -->
    <NDHDon>           <!-- Nội dung hóa đơn -->
      <NBan>           <!-- Người bán: tên, MST, địa chỉ -->
      <NMua>           <!-- Người mua: tên, MST, địa chỉ -->
      <DSHHDVu>        <!-- Danh sách hàng hóa dịch vụ -->
        <HHDVu>        <!-- Từng item -->
          <THHDVu>     <!-- Tên hàng -->
          <DVTinh>     <!-- Đơn vị tính -->
          <SLuong>     <!-- Số lượng -->
          <DGia>       <!-- Đơn giá -->
          <ThTien>     <!-- Thành tiền (trước thuế) -->
          <TSuat>      <!-- Thuế suất -->
          <TThue>      <!-- Tiền thuế (có thể KHÔNG có) -->
          <TTKhac>     <!-- Thông tin khác (thuế, sau thuế - tên field khác nhau tùy vendor) -->
        </HHDVu>
      </DSHHDVu>
      <TToan>          <!-- Tổng thanh toán -->
    </NDHDon>
  </DLHDon>
</HDon>
```

## Các dạng hóa đơn đã hỗ trợ

### Dạng A1 - TThue trực tiếp (VD: TH Milk)

```xml
<HHDVu>
  <ThTien>6084000</ThTien>
  <TThue>486720</TThue>          <!-- ← Tiền thuế là direct child -->
</HHDVu>
```

- `ThTien` = thành tiền (trước thuế)
- `TThue` = tiền thuế (direct child tag)
- `amountAfterTax` = `ThTien + TThue`

### Dạng A2 - VATAmount trong TTKhac (VD: Vinamilk/SEAREE)

```xml
<HHDVu>
  <ThTien>391200</ThTien>
  <!-- KHÔNG có TThue direct child -->
  <TTKhac>
    <TTin><TTruong>VATAmount</TTruong><DLieu>31296</DLieu></TTin>
    <TTin><TTruong>Amount</TTruong><DLieu>422496</DLieu></TTin>    <!-- = sau thuế -->
  </TTKhac>
</HHDVu>
```

- `ThTien` = thành tiền (trước thuế)
- `TTKhac/VATAmount` = tiền thuế
- `TTKhac/Amount` = thành tiền sau thuế (**> ThTien**, chứng tỏ bao gồm thuế)

### Dạng B - MISA (VATAmount nhưng Amount = trước thuế)

```xml
<HHDVu>
  <ThTien>343000</ThTien>
  <TTKhac>
    <TTin><TTruong>VATAmount</TTruong><DLieu>27439.0</DLieu></TTin>
    <TTin><TTruong>Amount</TTruong><DLieu>343000.0</DLieu></TTin>  <!-- = ThTien, KHÔNG phải sau thuế -->
  </TTKhac>
</HHDVu>
```

- `TTKhac/Amount` = `ThTien` (bằng nhau → KHÔNG bao gồm thuế)
- `amountAfterTax` = `ThTien + VATAmount` (tự tính)

### Dạng C - Vinh An Nguyên (field names tiếng Việt có dấu gạch)

```xml
<HHDVu>
  <ThTien>106481</ThTien>
  <TTKhac>
    <TTin><TTruong>TongTien_Thue</TTruong><DLieu>8519</DLieu></TTin>
    <TTin><TTruong>TongTien_CoThue</TTruong><DLieu>115000</DLieu></TTin>  <!-- > ThTien -->
  </TTKhac>
</HHDVu>
```

### Dạng D - Nguyên Thịnh Kiên (field names tiếng Việt đầy đủ)

```xml
<HHDVu>
  <ThTien>3377778</ThTien>
  <TTKhac>
    <TTin><TTruong>Tiền thuế dòng (Tiền thuế GTGT)</TTruong><DLieu>270222</DLieu></TTin>
    <TTin><TTruong>Thành tiền thanh toán của hàng hóa</TTruong><DLieu>3648000</DLieu></TTin>
  </TTKhac>
</HHDVu>
```

### Dạng E - Chỉ có TSuat, không có TThue/TTKhac (VD: Minh Nguyệt - C26MMN)

```xml
<HHDVu>
  <ThTien>4100000</ThTien>
  <TSuat>10%</TSuat>
  <!-- KHÔNG có TThue, KHÔNG có TTKhac -->
</HHDVu>
```

- `ThTien` = thành tiền (trước thuế)
- `TSuat` = thuế suất (10%, 8%, 5%...)
- Không có per-item tax amount → **parser tự tính**: `taxAmount = round(ThTien * TSuat / 100)`
- `amountAfterTax` = `ThTien + taxAmount`

### Dạng F - Có chiết khấu STCKhau + TTKhac (VD: Nguyên Minh Hoàng - C26TCT)

```xml
<HHDVu>
  <ThTien>261810</ThTien>              <!-- Thành tiền GỐC (trước CK) -->
  <STCKhau>39423</STCKhau>            <!-- Chiết khấu giảm trừ -->
  <TSuat>8%</TSuat>
  <TTKhac>
    <TTin><TTruong>Amount</TTruong><DLieu>240178</DLieu></TTin>      <!-- Thành tiền sau thuế -->
    <TTin><TTruong>VATAmount</TTruong><DLieu>17791</DLieu></TTin>    <!-- Tiền thuế -->
  </TTKhac>
</HHDVu>
```

- `ThTien` = SL × ĐG = thành tiền GỐC (**chưa trừ chiết khấu**)
- `STCKhau` = chiết khấu giảm trừ
- **`amount` = `ThTien - STCKhau`** = thành tiền thực tế (sau CK, trước thuế)
- `VATAmount` = VAT trên amount thực tế = `(ThTien - STCKhau) * TSuat / 100`
- `TTKhac/Amount` = `(ThTien - STCKhau) + VATAmount` = thành tiền thanh toán
- **Detect**: `ThTien ≈ SL × ĐG` → CK chưa trừ → parser trừ STCKhau

### Dạng G - CK đã trừ sẵn trong ThTien + TThue trực tiếp (VD: Tuấn Việt - C26TAA)

```xml
<HHDVu>
  <SLuong>3</SLuong>
  <DGia>236574</DGia>
  <STCKhau>163236</STCKhau>          <!-- Chiết khấu -->
  <ThTien>546486</ThTien>             <!-- = SL×ĐG - STCKhau = 709722 - 163236 (ĐÃ TRỪ CK) -->
  <TSuat>8%</TSuat>
  <TThue>43719</TThue>                <!-- = ThTien × 8% -->
  <TTKhac>
    <TTin><TTruong>Thành tiền thanh toán của hàng hóa</TTruong><DLieu>590205</DLieu></TTin>
    <TTin><TTruong>Tiền thuế dòng (Tiền thuế GTGT)</TTruong><DLieu>43719</DLieu></TTin>
  </TTKhac>
</HHDVu>
```

- `ThTien` = SL × ĐG - STCKhau (**đã trừ CK sẵn**)
- `TThue` = direct child = `ThTien × TSuat / 100`
- `amountAfterTax` = `ThTien + TThue`
- **Detect**: `ThTien ≈ SL × ĐG - STCKhau` (≠ SL × ĐG) → CK đã trừ → **không trừ lại**

## Logic parse thuế per-item (CRITICAL)

```
1. Lấy ThTien (thành tiền gốc)
2. Lấy thuế per-item:
   a. Ưu tiên TThue direct child tag
   b. Nếu TThue = 0, tìm trong TTKhac: 'VATAmount', 'VATAmountOC', 'TongTien_Thue', ...
   c. Nếu vẫn = 0, fallback tính từ TSuat: tax = round(ThTien * TSuat / 100)
3. Trừ chiết khấu (nếu CK chưa trừ sẵn):
   - STCKhau > 0 VÀ ThTien ≈ SL × ĐG → CK chưa trừ → amount = ThTien - STCKhau
   - STCKhau > 0 VÀ ThTien ≈ SL × ĐG - STCKhau → CK đã trừ sẵn → không trừ
4. Tìm thành tiền sau thuế trong TTKhac:
   → 'Amount', 'AmountOC', 'TongTien_CoThue', 'Thành tiền thanh toán của hàng hóa'
5. So sánh TTKhac amount với amount:
   - Nếu TTKhac amount > amount → dùng TTKhac amount (đã bao gồm thuế)
   - Nếu không → tự tính: amount + taxAmount
```

**Lý do so sánh**: Một số vendor (MISA - dạng B) lưu `Amount` trong TTKhac = giá trước thuế (= ThTien), trong khi vendor khác (Vinamilk - dạng A2) lưu = giá sau thuế. Chỉ dùng TTKhac amount khi nó lớn hơn ThTien.

## Thêm vendor mới

Khi gặp hóa đơn từ vendor mới mà "Thành tiền" = "Thành tiền sau thuế":

1. Đọc XML, tìm `TTKhac` trong `HHDVu` để xem field names
2. Thêm field name cho **thuế** vào danh sách lookup (cả 2 parser files)
3. Thêm field name cho **sau thuế** vào danh sách lookup (cả 2 parser files)
4. Test: `amountAfterTax` phải > `amount` (ThTien)

## Các file liên quan

| File | Mô tả |
|------|--------|
| `tax_invoice_xml_parser.py` | Parser XML cơ bản (`_get_ttkhac_float`) |
| `../../services/invoice_parsers.py` | Parser XML chính (`find_in_ttkhac`) |
| `invoice_service_v2.py` | Service lưu/đọc hóa đơn từ Firestore |
| `output_invoice_service_v2.py` | Service cho hóa đơn bán ra |

## Frontend mapping

Parser trả về item với fields:
```
amount (ThTien - STCKhau)  →  InvoiceItem.amount     (thành tiền sau CK, trước thuế)
discount (STCKhau)         →  InvoiceItem.discount    (chiết khấu, 0 nếu không có)
taxAmount                  →  InvoiceItem.tax_amount
amountAfterTax             →  InvoiceItem.amount_after_tax
```

Frontend (`invoice-processing-page.component.ts`) hiển thị:
- Cột "Thành tiền" = `amount`
- Cột "Thành tiền sau thuế" = `amount_after_tax`
- Cập nhật giá: dùng `amount_after_tax || amount`
