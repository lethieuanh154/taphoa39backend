from __future__ import annotations

from flask import Blueprint, jsonify, request
from routes.shared import handle_api_errors


def create_firebase_employees_bp(employee_service, socketio=None) -> Blueprint:
    bp = Blueprint("firebase_employees", __name__, url_prefix="/api/firebase")

    # ===============================
    # EMPLOYEE LIST ENDPOINTS
    # ===============================

    @bp.route("/get/employees", methods=["GET"])
    @handle_api_errors
    def get_all_employees():
        """Get all employees from employeeList collection"""
        employees = employee_service.get_all_employees()
        return jsonify(employees)

    @bp.route("/employees/<employee_id>", methods=["GET"])
    @handle_api_errors
    def get_employee(employee_id: str):
        """Get a single employee by ID"""
        employee = employee_service.get_employee_by_id(employee_id)
        if not employee:
            return jsonify({"error": "Employee not found"}), 404
        return jsonify(employee)

    @bp.route("/add_employee", methods=["POST"])
    @handle_api_errors
    def add_employee():
        """
        Add a new employee
        Expected payload based on add-worker-dialog.component:
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
        """
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "JSON body is required"}), 400

        result = employee_service.add_employee(payload)

        if result.get("success"):
            # Broadcast update via SocketIO if available
            if socketio:
                try:
                    socketio.emit('employee_added', result.get("data"), namespace='/employees')
                except:
                    pass
            return jsonify(result), 201
        else:
            return jsonify(result), 400

    @bp.route("/update_employee/<employee_id>", methods=["PUT"])
    @handle_api_errors
    def update_employee(employee_id: str):
        """
        Update an existing employee
        """
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "JSON body is required"}), 400

        result = employee_service.update_employee(employee_id, payload)

        if result.get("success"):
            # Broadcast update via SocketIO if available
            if socketio:
                try:
                    socketio.emit('employee_updated', {
                        "id": employee_id,
                        "updates": result.get("updates")
                    }, namespace='/employees')
                except:
                    pass
            return jsonify(result), 200
        else:
            status_code = 404 if result.get("message") == "Employee not found" else 400
            return jsonify(result), status_code

    @bp.route("/delete_employee/<employee_id>", methods=["DELETE"])
    @handle_api_errors
    def delete_employee(employee_id: str):
        """Delete an employee"""
        result = employee_service.delete_employee(employee_id)

        if result.get("success"):
            # Broadcast update via SocketIO if available
            if socketio:
                try:
                    socketio.emit('employee_deleted', {"id": employee_id}, namespace='/employees')
                except:
                    pass
            return jsonify(result), 200
        else:
            status_code = 404 if result.get("message") == "Employee not found" else 400
            return jsonify(result), status_code

    # ===============================
    # WORK SCHEDULE ENDPOINTS
    # ===============================

    @bp.route("/get/work_schedules", methods=["GET"])
    @handle_api_errors
    def get_all_work_schedules():
        """Get all work schedules"""
        schedules = employee_service.get_all_work_schedules()
        return jsonify(schedules)

    @bp.route("/work_schedules/filter", methods=["GET"])
    @handle_api_errors
    def get_work_schedules_by_date():
        """
        Get work schedules filtered by date range
        Query params: from_date (YYYY-MM-DD), to_date (YYYY-MM-DD)
        Example: /api/firebase/work_schedules/filter?from_date=2024-01-01&to_date=2024-01-31
        """
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')

        if not from_date or not to_date:
            return jsonify({
                "success": False,
                "message": "Both from_date and to_date query parameters are required (format: YYYY-MM-DD)"
            }), 400

        result = employee_service.get_work_schedule_by_date_range(from_date, to_date)

        if result.get("success"):
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    @bp.route("/save_work_schedule", methods=["PUT"])
    @handle_api_errors
    def save_work_schedule():
        """
        Save or update work schedule for a week
        Expected payload based on work-schedule-page.component:
        {
            "weekNumber": 1,
            "weekStartDate": "2024-01-01",
            "days": {
                "T2": {
                    "morning": {
                        "workers": [
                            {"workerId": "NV001", "workerName": "Nguyễn Văn A"}
                        ],
                        "startTime": "07:00",
                        "endTime": "12:00"
                    },
                    "afternoon": {...},
                    "evening": {...}
                },
                "T3": {...},
                ...
            },
            "dayInfos": [
                {
                    "dayName": "T2",
                    "date": "2024-01-01",
                    "dateString": "1/1/2024"
                },
                ...
            ]
        }
        """
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "JSON body is required"}), 400

        result = employee_service.save_work_schedule(payload)

        if result.get("success"):
            # Broadcast update via SocketIO if available
            if socketio:
                try:
                    socketio.emit('work_schedule_updated', result.get("data"), namespace='/employees')
                except:
                    pass
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    # ===============================
    # TIME SHEET ENDPOINTS
    # ===============================

    @bp.route("/get/time_sheets", methods=["GET"])
    @handle_api_errors
    def get_all_time_sheets():
        """Get all time sheets from timeSheet collection"""
        time_sheets = employee_service.get_all_time_sheets()
        return jsonify(time_sheets)

    @bp.route("/add_time_sheet", methods=["POST"])
    @handle_api_errors
    def add_time_sheet():
        """Add a new time sheet entry"""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "JSON body is required"}), 400

        result = employee_service.add_time_sheet(payload)

        if result.get("success"):
            return jsonify(result), 201
        else:
            return jsonify(result), 400

    # ===============================
    # PAYROLL ENDPOINTS
    # ===============================

    @bp.route("/get/payrolls", methods=["GET"])
    @handle_api_errors
    def get_all_payrolls():
        """Get all payrolls from payroll collection"""
        payrolls = employee_service.get_all_payrolls()
        return jsonify(payrolls)

    @bp.route("/add_payroll", methods=["POST"])
    @handle_api_errors
    def add_payroll():
        """Add a new payroll entry"""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "JSON body is required"}), 400

        result = employee_service.add_payroll(payload)

        if result.get("success"):
            return jsonify(result), 201
        else:
            return jsonify(result), 400

    @bp.route("/save_payroll", methods=["PUT"])
    @handle_api_errors
    def save_payroll():
        """Save or update a payroll record"""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "JSON body is required"}), 400

        result = employee_service.save_payroll(payload)

        if result.get("success"):
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    @bp.route("/save_payrolls_batch", methods=["PUT"])
    @handle_api_errors
    def save_payrolls_batch():
        """Save multiple payroll records in batch"""
        payload = request.get_json(silent=True)
        # Accept both array directly or { payrolls: [...] } format
        if isinstance(payload, dict) and "payrolls" in payload:
            payrolls = payload["payrolls"]
        elif isinstance(payload, list):
            payrolls = payload
        else:
            return jsonify({"success": False, "message": "JSON body must be an array or object with 'payrolls' key"}), 400

        result = employee_service.save_payrolls_batch(payrolls)

        if result.get("success"):
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    @bp.route("/payrolls/filter", methods=["GET"])
    @handle_api_errors
    def get_payrolls_by_period():
        """Get payroll records by period (YYYY-MM)"""
        period = request.args.get('period')

        if not period:
            return jsonify({
                "success": False,
                "message": "period query parameter is required (format: YYYY-MM)"
            }), 400

        result = employee_service.get_payrolls_by_period(period)

        if result.get("success"):
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    @bp.route("/delete_payroll/<payroll_id>", methods=["DELETE"])
    @handle_api_errors
    def delete_payroll(payroll_id: str):
        """Delete a payroll record"""
        result = employee_service.delete_payroll(payroll_id)

        if result.get("success"):
            # Broadcast update via SocketIO if available
            if socketio:
                try:
                    socketio.emit('payroll_deleted', {"id": payroll_id}, namespace='/employees')
                except:
                    pass
            return jsonify(result), 200
        else:
            status_code = 404 if result.get("message") == "Payroll record not found" else 400
            return jsonify(result), status_code

    # ===============================
    # ATTENDANCE ENDPOINTS
    # ===============================

    @bp.route("/get/attendance", methods=["GET"])
    @handle_api_errors
    def get_all_attendance():
        """Get all attendance records from attendance collection"""
        attendance = employee_service.get_all_attendance()
        return jsonify(attendance)

    @bp.route("/attendance/filter", methods=["GET"])
    @handle_api_errors
    def get_attendance_by_date():
        """
        Get attendance records filtered by date range
        Query params: from_date (YYYY-MM-DD), to_date (YYYY-MM-DD)
        Example: /api/firebase/attendance/filter?from_date=2024-01-01&to_date=2024-01-31
        """
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')

        if not from_date or not to_date:
            return jsonify({
                "success": False,
                "message": "Both from_date and to_date query parameters are required (format: YYYY-MM-DD)"
            }), 400

        result = employee_service.get_attendance_by_date_range(from_date, to_date)

        if result.get("success"):
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    @bp.route("/add_attendance", methods=["POST"])
    @handle_api_errors
    def add_attendance():
        """
        Add a new attendance record
        Expected payload:
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
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "JSON body is required"}), 400

        result = employee_service.add_attendance(payload)

        if result.get("success"):
            # Broadcast update via SocketIO if available
            if socketio:
                try:
                    socketio.emit('attendance_added', result.get("data"), namespace='/employees')
                except:
                    pass
            return jsonify(result), 201
        else:
            return jsonify(result), 400

    @bp.route("/update_attendance/<attendance_id>", methods=["PUT"])
    @handle_api_errors
    def update_attendance(attendance_id: str):
        """Update an existing attendance record"""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "JSON body is required"}), 400

        result = employee_service.update_attendance(attendance_id, payload)

        if result.get("success"):
            # Broadcast update via SocketIO if available
            if socketio:
                try:
                    socketio.emit('attendance_updated', {
                        "id": attendance_id,
                        "updates": result.get("updates")
                    }, namespace='/employees')
                except:
                    pass
            return jsonify(result), 200
        else:
            status_code = 404 if result.get("message") == "Attendance record not found" else 400
            return jsonify(result), status_code

    @bp.route("/delete_attendance/<attendance_id>", methods=["DELETE"])
    @handle_api_errors
    def delete_attendance(attendance_id: str):
        """Delete an attendance record"""
        result = employee_service.delete_attendance(attendance_id)

        if result.get("success"):
            # Broadcast update via SocketIO if available
            if socketio:
                try:
                    socketio.emit('attendance_deleted', {"id": attendance_id}, namespace='/employees')
                except:
                    pass
            return jsonify(result), 200
        else:
            status_code = 404 if result.get("message") == "Attendance record not found" else 400
            return jsonify(result), status_code

    @bp.route("/save_attendance_batch", methods=["PUT"])
    @handle_api_errors
    def save_attendance_batch():
        """
        Save multiple attendance records in batch
        Expected payload: array of attendance records or { records: [...] }
        """
        payload = request.get_json(silent=True)
        # Accept both array directly or { records: [...] } format
        if isinstance(payload, dict) and "records" in payload:
            records = payload["records"]
        elif isinstance(payload, list):
            records = payload
        else:
            return jsonify({"success": False, "message": "JSON body must be an array or object with 'records' key"}), 400

        result = employee_service.save_attendance_batch(records)

        if result.get("success"):
            # Broadcast update via SocketIO if available
            if socketio:
                try:
                    socketio.emit('attendance_batch_saved', {
                        "savedCount": result.get("savedCount")
                    }, namespace='/employees')
                except:
                    pass
            return jsonify(result), 200
        else:
            return jsonify(result), 400

    return bp
