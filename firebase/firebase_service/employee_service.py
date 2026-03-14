from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()
try:
    from google.cloud.firestore_v1 import FieldFilter
except ImportError:
    from google.cloud.firestore_v1.base_query import FieldFilter

from firebase.init_firebase import init_firestore

# Collection names
EMPLOYEE_LIST_COLLECTION = "employeeList"
WORK_SCHEDULE_COLLECTION = "workSchedule"
TIME_SHEET_COLLECTION = "timeSheet"
PAYROLL_COLLECTION = "payroll"
ATTENDANCE_COLLECTION = "attendance"

# Initialize Firestore with NHANVIEN service account
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_NHANVIEN")
employee_list_ref = db.collection(EMPLOYEE_LIST_COLLECTION)
work_schedule_ref = db.collection(WORK_SCHEDULE_COLLECTION)
time_sheet_ref = db.collection(TIME_SHEET_COLLECTION)
payroll_ref = db.collection(PAYROLL_COLLECTION)
attendance_ref = db.collection(ATTENDANCE_COLLECTION)


class FirestoreEmployeeService:
    def __init__(self, cache):
        self.cache = cache
        self.employee_list_ref = employee_list_ref
        self.work_schedule_ref = work_schedule_ref
        self.time_sheet_ref = time_sheet_ref
        self.payroll_ref = payroll_ref
        self.attendance_ref = attendance_ref

    # ===============================
    # EMPLOYEE LIST METHODS
    # ===============================

    def get_all_employees(self):
        """Get all employees from employeeList collection"""
        cache_key = "all_employees"
        if self.cache and self.cache.has(cache_key):
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        docs = self.employee_list_ref.stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            result.append(data)

        if self.cache:
            self.cache.set(cache_key, result, ttl=300)
        return result

    def get_employee_by_id(self, employee_id: str):
        """Get a single employee by ID"""
        if not employee_id:
            return None

        doc_id = str(employee_id).strip()
        cache_key = f"employee:{doc_id}"

        if self.cache and self.cache.has(cache_key):
            return self.cache.get(cache_key)

        doc = self.employee_list_ref.document(doc_id).get()
        if not doc.exists:
            return None

        data = doc.to_dict()
        data["id"] = doc.id

        if self.cache:
            self.cache.set(cache_key, data, ttl=300)
        return data

    def add_employee(self, employee_data: dict):
        """Add a new employee to employeeList collection"""
        if not employee_data:
            return {"success": False, "message": "employee_data is required"}

        # Validate required fields
        if "maNhanVien" not in employee_data or not employee_data["maNhanVien"]:
            return {"success": False, "message": "maNhanVien is required"}

        if "hoTen" not in employee_data or not employee_data["hoTen"]:
            return {"success": False, "message": "hoTen is required"}

        ma_nhan_vien = str(employee_data["maNhanVien"]).strip()

        # Check if employee already exists
        existing = self.employee_list_ref.document(ma_nhan_vien).get()
        if existing.exists:
            return {"success": False, "message": "Employee with this maNhanVien already exists"}

        try:
            # Convert date strings to timestamps if needed
            processed_data = self._process_employee_data(employee_data)

            doc_ref = self.employee_list_ref.document(ma_nhan_vien)
            doc_ref.set(processed_data)

            self.cache.invalidate("all_employees")
            self.cache.invalidate(f"employee:{ma_nhan_vien}")

            return {
                "success": True,
                "message": "Employee added successfully",
                "id": ma_nhan_vien,
                "data": processed_data
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def update_employee(self, employee_id: str, updates: dict):
        """Update an existing employee"""
        if not employee_id:
            return {"success": False, "message": "employee_id is required"}

        if not isinstance(updates, dict) or len(updates) == 0:
            return {"success": False, "message": "updates must be a non-empty object"}

        doc_id = str(employee_id).strip()
        doc_ref = self.employee_list_ref.document(doc_id)
        snapshot = doc_ref.get()

        if not snapshot.exists:
            return {"success": False, "message": "Employee not found"}

        try:
            # Process updates (convert dates, etc.)
            processed_updates = self._process_employee_data(updates)

            doc_ref.update(processed_updates)

            self.cache.invalidate("all_employees")
            self.cache.invalidate(f"employee:{doc_id}")

            return {
                "success": True,
                "message": "Employee updated successfully",
                "id": doc_id,
                "updates": processed_updates
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def delete_employee(self, employee_id: str):
        """Delete an employee"""
        if not employee_id:
            return {"success": False, "message": "employee_id is required"}

        doc_id = str(employee_id).strip()
        doc_ref = self.employee_list_ref.document(doc_id)
        snapshot = doc_ref.get()

        if not snapshot.exists:
            return {"success": False, "message": "Employee not found"}

        try:
            doc_ref.delete()
            self.cache.invalidate("all_employees")
            self.cache.invalidate(f"employee:{doc_id}")

            return {
                "success": True,
                "message": "Employee deleted successfully",
                "id": doc_id
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def _process_employee_data(self, data: dict) -> dict:
        """Process employee data, converting dates and cleaning fields"""
        processed = {}

        for key, value in data.items():
            if value is None or value == "":
                continue

            # Handle date fields
            if key in ["ngaySinh", "ngayBatDau", "ngayKetThuc"]:
                if isinstance(value, str):
                    try:
                        # Try parsing ISO format
                        date_obj = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        processed[key] = date_obj
                    except:
                        processed[key] = value
                else:
                    processed[key] = value
            else:
                processed[key] = value

        return processed

    # ===============================
    # WORK SCHEDULE METHODS
    # ===============================

    def get_all_work_schedules(self):
        """Get all work schedules"""
        cache_key = "all_work_schedules"
        if self.cache and self.cache.has(cache_key):
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        docs = self.work_schedule_ref.stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            result.append(data)

        if self.cache:
            self.cache.set(cache_key, result, ttl=300)
        return result

    def get_work_schedule_by_date_range(self, from_date: str, to_date: str):
        """
        Get work schedules within a date range
        from_date and to_date should be in format: YYYY-MM-DD
        """
        if not from_date or not to_date:
            return {"success": False, "message": "from_date and to_date are required"}

        try:
            # Parse dates
            from_date_obj = datetime.strptime(from_date, "%Y-%m-%d")
            to_date_obj = datetime.strptime(to_date, "%Y-%m-%d")

            # Query schedules where weekStartDate >= from_date and weekStartDate <= to_date
            query = self.work_schedule_ref.where(
                filter=FieldFilter("weekStartDate", ">=", from_date_obj)
            ).where(
                filter=FieldFilter("weekStartDate", "<=", to_date_obj)
            )

            docs = query.stream()
            result = []
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                result.append(data)

            return {"success": True, "data": result}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def save_work_schedule(self, schedule_data: dict):
        """
        Save or update a work schedule for a week
        Expected structure:
        {
            "weekNumber": 1,
            "weekStartDate": "2024-01-01",
            "days": {
                "T2": {
                    "date": "2024-01-01",
                    "morning": {"workers": [...], "startTime": "07:00", "endTime": "12:00"},
                    "afternoon": {...},
                    "evening": {...}
                },
                "T3": {
                    "date": "2024-01-02",
                    ...
                },
                ...
            }
        }
        Note: "date" field is embedded in each day, no separate "dayInfos" needed.
        """
        if not schedule_data:
            return {"success": False, "message": "schedule_data is required"}

        if "weekStartDate" not in schedule_data:
            return {"success": False, "message": "weekStartDate is required"}

        try:
            # Parse week start date
            week_start = schedule_data["weekStartDate"]
            if isinstance(week_start, str):
                week_start_obj = datetime.strptime(week_start, "%Y-%m-%d")
            else:
                week_start_obj = week_start

            # Create document ID from week start date
            doc_id = week_start_obj.strftime("%Y-%m-%d")

            # Process schedule data - no dayInfos needed
            processed_data = {
                "weekNumber": schedule_data.get("weekNumber", 1),
                "weekStartDate": week_start_obj,
                "weekEndDate": week_start_obj + timedelta(days=6),
                "days": schedule_data.get("days", {}),
                "updatedAt": datetime.now()
            }

            # Save or update the schedule
            doc_ref = self.work_schedule_ref.document(doc_id)
            doc_ref.set(processed_data, merge=True)

            self.cache.invalidate("all_work_schedules")

            return {
                "success": True,
                "message": "Work schedule saved successfully",
                "id": doc_id,
                "data": processed_data
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    # ===============================
    # TIME SHEET METHODS
    # ===============================

    def get_all_time_sheets(self):
        """Get all time sheets"""
        cache_key = "all_time_sheets"
        if self.cache and self.cache.has(cache_key):
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        docs = self.time_sheet_ref.stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            result.append(data)

        if self.cache:
            self.cache.set(cache_key, result, ttl=300)
        return result

    def add_time_sheet(self, time_sheet_data: dict):
        """Add a new time sheet entry"""
        try:
            doc_ref = self.time_sheet_ref.document()
            time_sheet_data["createdAt"] = datetime.now()
            doc_ref.set(time_sheet_data)

            self.cache.invalidate("all_time_sheets")

            return {
                "success": True,
                "message": "Time sheet added successfully",
                "id": doc_ref.id
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    # ===============================
    # PAYROLL METHODS
    # ===============================

    def get_all_payrolls(self):
        """Get all payrolls"""
        cache_key = "all_payrolls"
        if self.cache and self.cache.has(cache_key):
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        docs = self.payroll_ref.stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            result.append(data)

        if self.cache:
            self.cache.set(cache_key, result, ttl=300)
        return result

    def add_payroll(self, payroll_data: dict):
        """Add a new payroll entry"""
        try:
            doc_ref = self.payroll_ref.document()
            payroll_data["createdAt"] = datetime.now()
            doc_ref.set(payroll_data)

            self.cache.invalidate("all_payrolls")

            return {
                "success": True,
                "message": "Payroll added successfully",
                "id": doc_ref.id
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def save_payroll(self, payroll_data: dict):
        """
        Save or update a payroll record
        Uses maNhanVien + period as document ID for upsert behavior
        """
        if not payroll_data:
            return {"success": False, "message": "payroll_data is required"}

        if "maNhanVien" not in payroll_data or not payroll_data["maNhanVien"]:
            return {"success": False, "message": "maNhanVien is required"}

        try:
            # Create document ID from maNhanVien and period
            ma_nv = payroll_data["maNhanVien"]
            period = payroll_data.get("period", datetime.now().strftime("%Y-%m"))
            doc_id = f"{ma_nv}_{period}"

            payroll_data["updatedAt"] = datetime.now()
            if "createdAt" not in payroll_data:
                payroll_data["createdAt"] = datetime.now()

            doc_ref = self.payroll_ref.document(doc_id)
            doc_ref.set(payroll_data, merge=True)

            self.cache.invalidate("all_payrolls")

            return {
                "success": True,
                "message": "Payroll saved successfully",
                "id": doc_id,
                "data": payroll_data
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def save_payrolls_batch(self, payrolls: list):
        """
        Save multiple payroll records in batch
        """
        if not payrolls or not isinstance(payrolls, list):
            return {"success": False, "message": "payrolls must be a non-empty list"}

        try:
            saved_count = 0
            errors = []

            for payroll_data in payrolls:
                result = self.save_payroll(payroll_data)
                if result.get("success"):
                    saved_count += 1
                else:
                    errors.append(result.get("message"))

            self.cache.invalidate("all_payrolls")

            return {
                "success": True,
                "message": f"Saved {saved_count}/{len(payrolls)} payroll records",
                "savedCount": saved_count,
                "errors": errors if errors else None
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def get_payrolls_by_period(self, period: str):
        """
        Get payroll records for a specific period (YYYY-MM)
        """
        if not period:
            return {"success": False, "message": "period is required"}

        try:
            query = self.payroll_ref.where(
                filter=FieldFilter("period", "==", period)
            )

            docs = query.stream()
            result = []
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                # Convert datetime to string
                if "createdAt" in data and hasattr(data["createdAt"], "isoformat"):
                    data["createdAt"] = data["createdAt"].isoformat()
                if "updatedAt" in data and hasattr(data["updatedAt"], "isoformat"):
                    data["updatedAt"] = data["updatedAt"].isoformat()
                result.append(data)

            return {"success": True, "data": result}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def delete_payroll(self, payroll_id: str):
        """
        Delete a payroll record by ID
        """
        if not payroll_id:
            return {"success": False, "message": "payroll_id is required"}

        try:
            doc_ref = self.payroll_ref.document(payroll_id)
            doc = doc_ref.get()

            if not doc.exists:
                return {"success": False, "message": "Payroll record not found"}

            doc_ref.delete()

            # Invalidate cache
            self.cache.invalidate("all_payrolls")

            return {"success": True, "message": "Payroll record deleted successfully", "id": payroll_id}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    # ===============================
    # ATTENDANCE METHODS
    # ===============================

    def get_all_attendance(self):
        """Get all attendance records"""
        cache_key = "all_attendance"
        if self.cache and self.cache.has(cache_key):
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        docs = self.attendance_ref.stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            # Convert datetime to string for JSON serialization
            if "date" in data and hasattr(data["date"], "isoformat"):
                data["date"] = data["date"].isoformat()
            if "createdAt" in data and hasattr(data["createdAt"], "isoformat"):
                data["createdAt"] = data["createdAt"].isoformat()
            if "updatedAt" in data and hasattr(data["updatedAt"], "isoformat"):
                data["updatedAt"] = data["updatedAt"].isoformat()
            result.append(data)

        if self.cache:
            self.cache.set(cache_key, result, ttl=300)
        return result

    def get_attendance_by_date_range(self, from_date: str, to_date: str):
        """
        Get attendance records within a date range
        from_date and to_date should be in format: YYYY-MM-DD
        """
        if not from_date or not to_date:
            return {"success": False, "message": "from_date and to_date are required"}

        try:
            # Parse dates
            from_date_obj = datetime.strptime(from_date, "%Y-%m-%d")
            to_date_obj = datetime.strptime(to_date, "%Y-%m-%d")
            # Set to end of day for to_date
            to_date_obj = to_date_obj.replace(hour=23, minute=59, second=59)

            # Query attendance where date >= from_date and date <= to_date
            query = self.attendance_ref.where(
                filter=FieldFilter("date", ">=", from_date_obj)
            ).where(
                filter=FieldFilter("date", "<=", to_date_obj)
            )

            docs = query.stream()
            result = []
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                # Convert datetime to string for JSON serialization
                if "date" in data and hasattr(data["date"], "isoformat"):
                    data["date"] = data["date"].isoformat()
                if "createdAt" in data and hasattr(data["createdAt"], "isoformat"):
                    data["createdAt"] = data["createdAt"].isoformat()
                if "updatedAt" in data and hasattr(data["updatedAt"], "isoformat"):
                    data["updatedAt"] = data["updatedAt"].isoformat()
                result.append(data)

            return {"success": True, "data": result}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def add_attendance(self, attendance_data: dict):
        """
        Add a new attendance record
        Expected structure:
        {
            "date": "2024-01-01",
            "workerId": "NV001",
            "workerName": "Nguyễn Văn A",
            "startTime": "07:00",
            "endTime": "17:00",
            "totalHours": 10,
            "notes": "..."
        }
        """
        if not attendance_data:
            return {"success": False, "message": "attendance_data is required"}

        # Validate required fields
        if "workerId" not in attendance_data or not attendance_data["workerId"]:
            return {"success": False, "message": "workerId is required"}

        if "date" not in attendance_data or not attendance_data["date"]:
            return {"success": False, "message": "date is required"}

        try:
            # Process the data
            processed_data = self._process_attendance_data(attendance_data)
            processed_data["createdAt"] = datetime.now()

            # Create a unique document ID based on workerId and date
            date_str = attendance_data["date"]
            if isinstance(date_str, datetime):
                date_str = date_str.strftime("%Y-%m-%d")
            doc_id = f"{attendance_data['workerId']}_{date_str}"

            doc_ref = self.attendance_ref.document(doc_id)
            doc_ref.set(processed_data)

            self.cache.invalidate("all_attendance")

            # Convert datetime for response
            response_data = processed_data.copy()
            if "date" in response_data and hasattr(response_data["date"], "isoformat"):
                response_data["date"] = response_data["date"].isoformat()
            if "createdAt" in response_data and hasattr(response_data["createdAt"], "isoformat"):
                response_data["createdAt"] = response_data["createdAt"].isoformat()

            return {
                "success": True,
                "message": "Attendance record added successfully",
                "id": doc_id,
                "data": response_data
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def update_attendance(self, attendance_id: str, updates: dict):
        """Update an existing attendance record"""
        if not attendance_id:
            return {"success": False, "message": "attendance_id is required"}

        if not isinstance(updates, dict) or len(updates) == 0:
            return {"success": False, "message": "updates must be a non-empty object"}

        doc_id = str(attendance_id).strip()
        doc_ref = self.attendance_ref.document(doc_id)
        snapshot = doc_ref.get()

        if not snapshot.exists:
            return {"success": False, "message": "Attendance record not found"}

        try:
            # Process updates
            processed_updates = self._process_attendance_data(updates)
            processed_updates["updatedAt"] = datetime.now()

            doc_ref.update(processed_updates)

            self.cache.invalidate("all_attendance")

            return {
                "success": True,
                "message": "Attendance record updated successfully",
                "id": doc_id,
                "updates": updates
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def delete_attendance(self, attendance_id: str):
        """Delete an attendance record"""
        if not attendance_id:
            return {"success": False, "message": "attendance_id is required"}

        doc_id = str(attendance_id).strip()
        doc_ref = self.attendance_ref.document(doc_id)
        snapshot = doc_ref.get()

        if not snapshot.exists:
            return {"success": False, "message": "Attendance record not found"}

        try:
            doc_ref.delete()
            self.cache.invalidate("all_attendance")

            return {
                "success": True,
                "message": "Attendance record deleted successfully",
                "id": doc_id
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def save_attendance_batch(self, records: list):
        """
        Save multiple attendance records in batch
        Each record uses workerId + date as document ID for upsert behavior
        """
        if not records or not isinstance(records, list):
            return {"success": False, "message": "records must be a non-empty list"}

        try:
            saved_count = 0
            errors = []

            for attendance_data in records:
                # Validate required fields
                if "workerId" not in attendance_data or not attendance_data["workerId"]:
                    errors.append("Missing workerId in record")
                    continue
                if "date" not in attendance_data or not attendance_data["date"]:
                    errors.append("Missing date in record")
                    continue

                try:
                    # Process the data
                    processed_data = self._process_attendance_data(attendance_data)
                    processed_data["updatedAt"] = datetime.now()
                    if "createdAt" not in processed_data:
                        processed_data["createdAt"] = datetime.now()

                    # Create a unique document ID based on workerId and date
                    date_str = attendance_data["date"]
                    if isinstance(date_str, datetime):
                        date_str = date_str.strftime("%Y-%m-%d")
                    doc_id = f"{attendance_data['workerId']}_{date_str}"

                    doc_ref = self.attendance_ref.document(doc_id)
                    doc_ref.set(processed_data, merge=True)
                    saved_count += 1
                except Exception as e:
                    errors.append(str(e))

            self.cache.invalidate("all_attendance")

            return {
                "success": True,
                "message": f"Saved {saved_count}/{len(records)} attendance records",
                "savedCount": saved_count,
                "errors": errors if errors else None
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def _process_attendance_data(self, data: dict) -> dict:
        """Process attendance data, converting dates and cleaning fields"""
        processed = {}

        for key, value in data.items():
            if value is None or value == "":
                continue

            # Handle date field
            if key == "date":
                if isinstance(value, str):
                    try:
                        # Try parsing ISO format or YYYY-MM-DD
                        if "T" in value:
                            date_obj = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        else:
                            date_obj = datetime.strptime(value, "%Y-%m-%d")
                        processed[key] = date_obj
                    except:
                        processed[key] = value
                else:
                    processed[key] = value
            else:
                processed[key] = value

        return processed
