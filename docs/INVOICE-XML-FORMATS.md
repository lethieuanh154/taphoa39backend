# Firebase Invoices - XML Parser

## Tổng quan

Module xử lý hóa đơn điện tử (e-invoice) từ nhiều nguồn phần mềm khác nhau. Parser chính nằm ở 2 file:

- `tax_invoice_xml_parser.py` - Parser cơ bản (dùng cho `firebase_invoices`)
- `../../services/invoice_parsers.py` - Parser chính của app (dùng cho route `invoice_processing`)

Cả 2 parser đều phải sync logic giống nhau khi cập nhật.

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

## Logic parse thuế per-item (CRITICAL)

```
1. Ưu tiên TThue direct child tag
2. Nếu TThue = 0, tìm trong TTKhac với field names:
   → 'VATAmount', 'VATAmountOC', 'TongTien_Thue', 'Tiền thuế dòng (Tiền thuế GTGT)'

3. Tìm thành tiền sau thuế trong TTKhac:
   → 'Amount', 'AmountOC', 'TongTien_CoThue', 'Thành tiền thanh toán của hàng hóa'

4. So sánh TTKhac amount với ThTien:
   - Nếu TTKhac amount > ThTien → dùng TTKhac amount (đã bao gồm thuế)
   - Nếu TTKhac amount <= ThTien → tự tính: ThTien + taxAmount
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
amount (ThTien)  →  InvoiceItem.amount
taxAmount        →  InvoiceItem.tax_amount
amountAfterTax   →  InvoiceItem.amount_after_tax
```

Frontend (`invoice-processing-page.component.ts`) hiển thị:
- Cột "Thành tiền" = `amount`
- Cột "Thành tiền sau thuế" = `amount_after_tax`
- Cập nhật giá: dùng `amount_after_tax || amount`
