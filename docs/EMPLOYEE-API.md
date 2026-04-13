# Employee Management API Documentation

## Overview
API để quản lý nhân viên, lịch làm việc, bảng chấm công và bảng lương sử dụng Firebase Firestore với service account `FIREBASE_SERVICE_ACCOUNT_NHANVIEN`.

## Collections
- **employeeList** - Danh sách nhân viên
- **workSchedule** - Lịch làm việc
- **timeSheet** - Bảng chấm công
- **payroll** - Bảng lương

---

## Employee List APIs

### 1. Get All Employees
**GET** `/api/firebase/get/employees`

**Response:**
```json
[
  {
    "id": "NV001",
    "maNhanVien": "NV001",
    "hoTen": "Nguyễn Văn A",
    "ngaySinh": "1990-01-01",
    "gioiTinh": "Nam",
    "soCCCD": "001234567890",
    "phongBan": "Bán hàng",
    "chucDanh": "Nhân viên",
    "ngayBatDau": "2024-01-01",
    "soDienThoai": "0123456789",
    "email": "email@example.com",
    "diaChi": "123 Street",
    "hinhAnh": "base64_or_url"
  }
]
```

### 2. Get Employee By ID
**GET** `/api/firebase/employees/<employee_id>`

**Example:** `/api/firebase/employees/NV001`

**Response:**
```json
{
  "id": "NV001",
  "maNhanVien": "NV001",
  "hoTen": "Nguyễn Văn A",
  ...
}
```

### 3. Add Employee
**POST** `/api/firebase/add_employee`

**Request Body:**
```json
{
  "maNhanVien": "NV001",
  "hoTen": "Nguyễn Văn A",
  "ngaySinh": "1990-01-01",
  "gioiTinh": "Nam",
  "soCCCD": "001234567890",
  "phongBan": "Bán hàng",
  "chucDanh": "Nhân viên",
  "ngayBatDau": "2024-01-01",
  "soDienThoai": "0123456789",
  "email": "email@example.com",
  "diaChi": "123 Street",
  "hinhAnh": "base64_or_url"
}
```

**Required Fields:**
- `maNhanVien` (string) - Mã nhân viên
- `hoTen` (string) - Họ tên

**Optional Fields:**
- `ngaySinh` (Date | string) - Ngày sinh
- `gioiTinh` (string) - Giới tính: "Nam", "Nữ", "Khác"
- `soCCCD` (string) - Số CCCD/CMND
- `phongBan` (string) - Phòng ban: "Bán hàng", "Kho", "Kế toán", "Quản lý"
- `chucDanh` (string) - Chức danh: "Nhân viên", "Trưởng phòng", "Phó phòng", "Giám đốc"
- `ngayBatDau` (Date | string) - Ngày bắt đầu làm việc
- `soDienThoai` (string) - Số điện thoại
- `email` (string) - Email
- `diaChi` (string) - Địa chỉ
- `hinhAnh` (string) - Hình ảnh (base64 hoặc URL)

**Response:**
```json
{
  "success": true,
  "message": "Employee added successfully",
  "id": "NV001",
  "data": { ... }
}
```

### 4. Update Employee
**PUT** `/api/firebase/update_employee/<employee_id>`

**Example:** `/api/firebase/update_employee/NV001`

**Request Body:**
```json
{
  "hoTen": "Nguyễn Văn A Updated",
  "soDienThoai": "0987654321",
  "chucDanh": "Trưởng phòng"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Employee updated successfully",
  "id": "NV001",
  "updates": { ... }
}
```

### 5. Delete Employee
**DELETE** `/api/firebase/delete_employee/<employee_id>`

**Example:** `/api/firebase/delete_employee/NV001`

**Response:**
```json
{
  "success": true,
  "message": "Employee deleted successfully",
  "id": "NV001"
}
```

---

## Work Schedule APIs

### 1. Get All Work Schedules
**GET** `/api/firebase/get/work_schedules`

**Response:**
```json
[
  {
    "id": "2024-01-01",
    "weekNumber": 1,
    "weekStartDate": "2024-01-01T00:00:00",
    "weekEndDate": "2024-01-07T00:00:00",
    "days": { ... },
    "dayInfos": [ ... ],
    "updatedAt": "2024-01-01T10:00:00"
  }
]
```

### 2. Get Work Schedules by Date Range
**GET** `/api/firebase/work_schedules/filter?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD`

**Query Parameters:**
- `from_date` (required) - Ngày bắt đầu (format: YYYY-MM-DD)
- `to_date` (required) - Ngày kết thúc (format: YYYY-MM-DD)

**Example:** `/api/firebase/work_schedules/filter?from_date=2024-01-01&to_date=2024-01-31`

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": "2024-01-01",
      "weekNumber": 1,
      "weekStartDate": "2024-01-01T00:00:00",
      "weekEndDate": "2024-01-07T00:00:00",
      "days": {
        "T2": {
          "morning": {
            "workers": [
              {
                "workerId": "NV001",
                "workerName": "Nguyễn Văn A"
              }
            ],
            "startTime": "07:00",
            "endTime": "12:00"
          },
          "afternoon": {
            "workers": [],
            "startTime": "12:00",
            "endTime": "17:00"
          },
          "evening": {
            "workers": [],
            "startTime": "17:00",
            "endTime": "22:00"
          }
        },
        "T3": { ... },
        "T4": { ... },
        "T5": { ... },
        "T6": { ... },
        "T7": { ... },
        "CN": { ... }
      },
      "dayInfos": [
        {
          "dayName": "T2",
          "date": "2024-01-01",
          "dateString": "1/1/2024"
        },
        ...
      ],
      "updatedAt": "2024-01-01T10:00:00"
    }
  ]
}
```

### 3. Save Work Schedule
**PUT** `/api/firebase/save_work_schedule`

**Request Body:**
```json
{
  "weekNumber": 1,
  "weekStartDate": "2024-01-01",
  "days": {
    "T2": {
      "morning": {
        "workers": [
          {
            "workerId": "NV001",
            "workerName": "Nguyễn Văn A"
          },
          {
            "workerId": "NV002",
            "workerName": "Trần Thị B"
          }
        ],
        "startTime": "07:00",
        "endTime": "12:00"
      },
      "afternoon": {
        "workers": [],
        "startTime": "12:00",
        "endTime": "17:00"
      },
      "evening": {
        "workers": [],
        "startTime": "17:00",
        "endTime": "22:00"
      }
    },
    "T3": { ... },
    "T4": { ... },
    "T5": { ... },
    "T6": { ... },
    "T7": { ... },
    "CN": { ... }
  },
  "dayInfos": [
    {
      "dayName": "T2",
      "date": "2024-01-01",
      "dateString": "1/1/2024"
    },
    {
      "dayName": "T3",
      "date": "2024-01-02",
      "dateString": "2/1/2024"
    },
    ...
  ]
}
```

**Required Fields:**
- `weekStartDate` (string) - Ngày bắt đầu tuần (format: YYYY-MM-DD)

**Optional Fields:**
- `weekNumber` (number) - Số tuần
- `days` (object) - Dữ liệu lịch làm việc theo ngày
- `dayInfos` (array) - Thông tin các ngày trong tuần

**Response:**
```json
{
  "success": true,
  "message": "Work schedule saved successfully",
  "id": "2024-01-01",
  "data": { ... }
}
```

**Notes:**
- Document ID sẽ được tự động tạo từ `weekStartDate` (format: YYYY-MM-DD)
- Nếu đã tồn tại lịch cho tuần đó, sẽ được cập nhật (merge)
- `weekEndDate` sẽ tự động tính = `weekStartDate + 6 days`

---

## Time Sheet APIs

### 1. Get All Time Sheets
**GET** `/api/firebase/get/time_sheets`

**Response:**
```json
[
  {
    "id": "auto_generated_id",
    "employeeId": "NV001",
    "date": "2024-01-01",
    "checkIn": "08:00",
    "checkOut": "17:00",
    "createdAt": "2024-01-01T08:00:00"
  }
]
```

### 2. Add Time Sheet
**POST** `/api/firebase/add_time_sheet`

**Request Body:**
```json
{
  "employeeId": "NV001",
  "date": "2024-01-01",
  "checkIn": "08:00",
  "checkOut": "17:00",
  "notes": "Optional notes"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Time sheet added successfully",
  "id": "auto_generated_id"
}
```

---

## Payroll APIs

### 1. Get All Payrolls
**GET** `/api/firebase/get/payrolls`

**Response:**
```json
[
  {
    "id": "auto_generated_id",
    "employeeId": "NV001",
    "month": "2024-01",
    "baseSalary": 10000000,
    "bonus": 1000000,
    "deduction": 500000,
    "totalSalary": 10500000,
    "createdAt": "2024-01-31T10:00:00"
  }
]
```

### 2. Add Payroll
**POST** `/api/firebase/add_payroll`

**Request Body:**
```json
{
  "employeeId": "NV001",
  "month": "2024-01",
  "baseSalary": 10000000,
  "bonus": 1000000,
  "deduction": 500000,
  "totalSalary": 10500000
}
```

**Response:**
```json
{
  "success": true,
  "message": "Payroll added successfully",
  "id": "auto_generated_id"
}
```

---

## Error Responses

### 400 Bad Request
```json
{
  "success": false,
  "message": "Error description"
}
```

### 404 Not Found
```json
{
  "error": "Employee not found"
}
```

---

## Firebase Collections Structure

### employeeList Collection
```
employeeList/
  └── {maNhanVien}/
      ├── maNhanVien: string
      ├── hoTen: string
      ├── ngaySinh: timestamp
      ├── gioiTinh: string
      ├── soCCCD: string
      ├── phongBan: string
      ├── chucDanh: string
      ├── ngayBatDau: timestamp
      ├── soDienThoai: string
      ├── email: string
      ├── diaChi: string
      └── hinhAnh: string
```

### workSchedule Collection
```
workSchedule/
  └── {YYYY-MM-DD}/
      ├── weekNumber: number
      ├── weekStartDate: timestamp
      ├── weekEndDate: timestamp
      ├── days: map
      ├── dayInfos: array
      └── updatedAt: timestamp
```

### timeSheet Collection
```
timeSheet/
  └── {auto_id}/
      ├── employeeId: string
      ├── date: string
      ├── checkIn: string
      ├── checkOut: string
      └── createdAt: timestamp
```

### payroll Collection
```
payroll/
  └── {auto_id}/
      ├── employeeId: string
      ├── month: string
      ├── baseSalary: number
      ├── bonus: number
      ├── deduction: number
      ├── totalSalary: number
      └── createdAt: timestamp
```

---

## Integration với Frontend

### Angular Service Example

```typescript
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Injectable({
  providedIn: 'root'
})
export class EmployeeService {
  private apiUrl = 'http://localhost:5000/api/firebase';

  constructor(private http: HttpClient) {}

  // Get all employees
  getAllEmployees() {
    return this.http.get(`${this.apiUrl}/get/employees`);
  }

  // Add employee
  addEmployee(employee: any) {
    return this.http.post(`${this.apiUrl}/add_employee`, employee);
  }

  // Update employee
  updateEmployee(employeeId: string, updates: any) {
    return this.http.put(`${this.apiUrl}/update_employee/${employeeId}`, updates);
  }

  // Get work schedules by date range
  getWorkSchedulesByDate(fromDate: string, toDate: string) {
    return this.http.get(`${this.apiUrl}/work_schedules/filter?from_date=${fromDate}&to_date=${toDate}`);
  }

  // Save work schedule
  saveWorkSchedule(schedule: any) {
    return this.http.put(`${this.apiUrl}/save_work_schedule`, schedule);
  }
}
```

### Usage in Component (work-schedule-page.component.ts)

```typescript
saveWeekSchedule(weekIndex: number) {
  const weekSchedule = this.weekSchedules[weekIndex];

  if (!weekSchedule) {
    alert('Không tìm thấy lịch làm việc cho tuần này');
    return;
  }

  const payload = {
    weekNumber: weekSchedule.weekNumber,
    weekStartDate: this.formatDateForStorage(weekSchedule.dayInfos[0].date),
    days: weekSchedule.days,
    dayInfos: weekSchedule.dayInfos
  };

  this.employeeService.saveWorkSchedule(payload).subscribe(
    (response: any) => {
      if (response.success) {
        alert(`Đã lưu lịch Tuần ${weekSchedule.weekNumber} thành công!`);
      }
    },
    (error) => {
      console.error('Error saving schedule:', error);
      alert('Có lỗi khi lưu lịch làm việc');
    }
  );
}

private formatDateForStorage(date: Date | null): string {
  if (!date) return '';
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}
```

---

## Testing APIs

### Using cURL

```bash
# Get all employees
curl http://localhost:5000/api/firebase/get/employees

# Add employee
curl -X POST http://localhost:5000/api/firebase/add_employee \
  -H "Content-Type: application/json" \
  -d '{
    "maNhanVien": "NV001",
    "hoTen": "Nguyễn Văn A",
    "gioiTinh": "Nam",
    "phongBan": "Bán hàng"
  }'

# Get work schedules by date
curl "http://localhost:5000/api/firebase/work_schedules/filter?from_date=2024-01-01&to_date=2024-01-31"

# Save work schedule
curl -X PUT http://localhost:5000/api/firebase/save_work_schedule \
  -H "Content-Type: application/json" \
  -d '{
    "weekNumber": 1,
    "weekStartDate": "2024-01-01",
    "days": {},
    "dayInfos": []
  }'
```
