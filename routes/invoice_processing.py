"""
Flask Blueprint for Invoice Processing API
Direct PDF reading with Gemini Flash/Pro (OCR disabled)
Flow: Gemini Flash -> Validate -> Gemini Pro (if needed)
"""
import time
import logging
from typing import List

from flask import Blueprint, request, jsonify

from models.invoice import (
    ProcessingResult,
    ProcessingLogEntry,
    ValidationError
)
from services.ai_extractor import ai_extractor
from services.invoice_validator import invoice_validator
from services.config import config

logger = logging.getLogger(__name__)


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


def create_invoice_processing_bp() -> Blueprint:
    """Create and configure the invoice processing blueprint"""

    bp = Blueprint('invoice_processing', __name__, url_prefix='/v1')

    @bp.route("/health", methods=["GET"])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            "status": "healthy",
            "ocr_available": False,  # OCR disabled, using Gemini Vision
            "gemini_direct": True,
            "version": "2.0.0"
        })

    @bp.route("/process-invoice", methods=["POST"])
    def process_invoice():
        """
        Process invoice PDF and extract structured data

        Direct Gemini Flow (no OCR):
        1. Flash: Read PDF directly with Gemini Flash Vision
        2. Validate: Check for missing/invalid fields
        3. Pro (if needed): Use Gemini Pro Vision for better accuracy

        Returns:
            ProcessingResult as JSON
        """
        total_start_time = time.time()
        processing_log: List[ProcessingLogEntry] = []

        logger.info("=" * 60)
        logger.info("Starting invoice processing request (Direct Gemini)")

        # ============================================================
        # STEP 0: Validate request
        # ============================================================
        if "file" not in request.files:
            logger.warning("No file in request")
            return jsonify(ProcessingResult(
                success=False,
                error="Không có file trong request",
                processing_log=processing_log
            ).model_dump()), 400

        file = request.files["file"]

        if file.filename == "":
            logger.warning("Empty filename")
            return jsonify(ProcessingResult(
                success=False,
                error="Tên file trống",
                processing_log=processing_log
            ).model_dump()), 400

        if not allowed_file(file.filename):
            logger.warning(f"Invalid file type: {file.filename}")
            return jsonify(ProcessingResult(
                success=False,
                error="Chỉ chấp nhận file PDF",
                processing_log=processing_log
            ).model_dump()), 400

        # Read file content
        file_bytes = file.read()
        file_size = len(file_bytes)

        if file_size > config.MAX_FILE_SIZE:
            logger.warning(f"File too large: {file_size} bytes")
            return jsonify(ProcessingResult(
                success=False,
                error=f"File quá lớn ({file_size / 1024 / 1024:.1f}MB). Tối đa 10MB",
                processing_log=processing_log
            ).model_dump()), 400

        logger.info(f"Processing file: {file.filename} ({file_size / 1024:.1f}KB)")

        # ============================================================
        # STEP 1: Gemini Flash - Read PDF directly
        # ============================================================
        flash_invoice, flash_duration = ai_extractor.extract_from_pdf_with_flash(
            file_bytes,
            processing_log
        )

        if flash_invoice is None:
            logger.warning("Flash extraction failed, trying Pro...")

            # Try with Pro if Flash fails
            pro_invoice, pro_duration = ai_extractor.extract_from_pdf_with_pro(
                file_bytes,
                None,
                [],
                processing_log
            )

            if pro_invoice is None:
                logger.error("Both Flash and Pro extraction failed")
                return jsonify(ProcessingResult(
                    success=False,
                    error="Không thể trích xuất thông tin từ hóa đơn",
                    processing_time_ms=int((time.time() - total_start_time) * 1000),
                    processing_log=processing_log
                ).model_dump()), 500

            # Use Pro result
            flash_invoice = pro_invoice

        # ============================================================
        # STEP 2: Validate - Check for missing/invalid fields
        # ============================================================
        validate_log = ProcessingLogEntry(
            step="validate",
            status="processing",
            message="Đang kiểm tra dữ liệu..."
        )
        processing_log.append(validate_log)

        validate_start = time.time()
        is_valid, validation_errors = invoice_validator.validate(flash_invoice)
        validate_duration = int((time.time() - validate_start) * 1000)

        validate_log.duration_ms = validate_duration
        validate_log.status = "completed"
        validate_log.message = (
            "Kiểm tra hoàn tất - Dữ liệu hợp lệ" if is_valid
            else f"Phát hiện {len(validation_errors)} vấn đề"
        )

        logger.info(f"Validation completed in {validate_duration}ms: {'PASS' if is_valid else 'FAIL'}")

        # ============================================================
        # STEP 3: Gemini Pro (if needed) - Re-read for better accuracy
        # ============================================================
        final_invoice = flash_invoice
        processing_method = "flash"

        if not is_valid:
            # Get error messages for Pro
            error_messages = invoice_validator.get_error_messages(validation_errors)

            if error_messages:
                logger.info(f"Validation errors found, invoking Gemini Pro")

                pro_invoice, pro_duration = ai_extractor.extract_from_pdf_with_pro(
                    file_bytes,
                    flash_invoice,
                    error_messages,
                    processing_log
                )

                if pro_invoice is not None:
                    # Re-validate Pro result
                    is_valid_pro, validation_errors_pro = invoice_validator.validate(pro_invoice)

                    if is_valid_pro or len(validation_errors_pro) < len(validation_errors):
                        final_invoice = pro_invoice
                        validation_errors = validation_errors_pro
                        processing_method = "pro"
                        logger.info("Using Pro result (improved)")
                    else:
                        logger.info("Pro result not better, keeping Flash result")
                else:
                    logger.warning("Pro extraction failed, keeping Flash result")

        # ============================================================
        # STEP 4: Return result
        # ============================================================
        total_duration = int((time.time() - total_start_time) * 1000)

        logger.info(
            f"Processing complete in {total_duration}ms using {processing_method}. "
            f"Items: {len(final_invoice.items)}, Errors: {len(validation_errors)}"
        )
        logger.info("=" * 60)

        return jsonify(ProcessingResult(
            success=True,
            invoice=final_invoice,
            validation_errors=validation_errors,
            processing_method=processing_method,
            processing_time_ms=total_duration,
            processing_log=processing_log
        ).model_dump())

    @bp.route("/extract", methods=["POST"])
    def extract_invoice():
        """
        Alias endpoint for process_invoice
        Maintains compatibility with frontend expecting /v1/extract
        """
        return process_invoice()

    @bp.errorhandler(Exception)
    def handle_error(error):
        """Error handler for this blueprint"""
        logger.exception(f"Unhandled error: {error}")
        return jsonify(ProcessingResult(
            success=False,
            error=f"Lỗi server: {str(error)}",
            processing_log=[]
        ).model_dump()), 500

    return bp
