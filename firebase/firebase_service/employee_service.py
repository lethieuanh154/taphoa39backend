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

# Initialize Firestore with NHANVIEN service account
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_NHANVIEN")
employee_list_ref = db.collection(EMPLOYEE_LIST_COLLECTION)
work_schedule_ref = db.collection(WORK_SCHEDULE_COLLECTION)
time_sheet_ref = db.collection(TIME_SHEET_COLLECTION)
payroll_ref = db.collection(PAYROLL_COLLECTION)


class FirestoreEmployeeService:
    def __init__(self, cache):
        self.cache = cache
        self.employee_list_ref = employee_list_ref
        self.work_schedule_ref = work_schedule_ref
        self.time_sheet_ref = time_sheet_ref
        self.payroll_ref = payroll_ref

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
            if key in ["ngaySinh", "ngayBatDau"]:
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
