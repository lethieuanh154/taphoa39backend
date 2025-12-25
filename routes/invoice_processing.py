"""
Flask Blueprint for Invoice Processing API
Hybrid AI Flow: EasyOCR -> Gemini Flash -> Validate -> Gemini Pro (if needed)
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
from services.ocr_engine import ocr_engine
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
            "ocr_available": ocr_engine.is_available,
            "version": "1.0.0"
        })

    @bp.route("/process-invoice", methods=["POST"])
    def process_invoice():
        """
        Process invoice PDF and extract structured data

        Hybrid Flow:
        1. OCR: Extract text from PDF using EasyOCR
        2. Flash: Extract structured data using Gemini Flash
        3. Validate: Check mathematical correctness
        4. Pro (if needed): Use Gemini Pro to correct errors

        Returns:
            ProcessingResult as JSON
        """
        total_start_time = time.time()
        processing_log: List[ProcessingLogEntry] = []

        logger.info("=" * 60)
        logger.info("Starting invoice processing request")

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
        # STEP 1: OCR - Extract text from PDF
        # ============================================================
        ocr_log = ProcessingLogEntry(
            step="ocr",
            status="processing",
            message="Đang trích xuất text từ PDF..."
        )
        processing_log.append(ocr_log)

        ocr_start = time.time()

        if not ocr_engine.is_available:
            ocr_log.status = "error"
            ocr_log.message = "OCR Engine không khả dụng"
            logger.error("OCR Engine not available")
            return jsonify(ProcessingResult(
                success=False,
                error="OCR Engine không khả dụng. Vui lòng kiểm tra cài đặt.",
                processing_log=processing_log
            ).model_dump()), 500

        ocr_result = ocr_engine.extract_text_from_pdf(file_bytes)
        ocr_duration = int((time.time() - ocr_start) * 1000)

        ocr_log.duration_ms = ocr_duration

        if not ocr_result.text:
            ocr_log.status = "error"
            ocr_log.message = "Không trích xuất được text từ PDF"
            logger.error("OCR extraction returned empty text")
            return jsonify(ProcessingResult(
                success=False,
                error="Không thể đọc được nội dung PDF. Vui lòng kiểm tra file.",
                processing_log=processing_log
            ).model_dump()), 400

        ocr_log.status = "completed"
        ocr_log.message = f"Đã trích xuất {len(ocr_result.text)} ký tự từ {ocr_result.page_count} trang"
        ocr_log.details = f"Confidence: {ocr_result.confidence:.1%}"

        logger.info(
            f"OCR completed in {ocr_duration}ms: "
            f"{len(ocr_result.text)} chars, {ocr_result.page_count} pages"
        )

        # ============================================================
        # STEP 2: AI Flash - Extract structured data
        # ============================================================
        flash_invoice, flash_duration = ai_extractor.extract_with_flash(
            ocr_result.text,
            processing_log
        )

        if flash_invoice is None:
            logger.error("Flash extraction failed")
            return jsonify(ProcessingResult(
                success=False,
                error="Không thể trích xuất thông tin từ hóa đơn",
                processing_time_ms=int((time.time() - total_start_time) * 1000),
                processing_log=processing_log
            ).model_dump()), 500

        # ============================================================
        # STEP 3: Validate - Check mathematical correctness
        # ============================================================
        validate_log = ProcessingLogEntry(
            step="validate",
            status="processing",
            message="Đang kiểm tra tính toán..."
        )
        processing_log.append(validate_log)

        validate_start = time.time()
        is_valid, validation_errors = invoice_validator.validate(flash_invoice)
        validate_duration = int((time.time() - validate_start) * 1000)

        validate_log.duration_ms = validate_duration
        validate_log.status = "completed"
        validate_log.message = (
            "Kiểm tra hoàn tất - Không có lỗi" if is_valid
            else f"Phát hiện {len(validation_errors)} vấn đề"
        )

        logger.info(f"Validation completed in {validate_duration}ms: {'PASS' if is_valid else 'FAIL'}")

        # ============================================================
        # STEP 4: AI Pro (if needed) - Correct errors
        # ============================================================
        final_invoice = flash_invoice
        processing_method = "flash"

        if not is_valid:
            # Get error messages for Pro correction
            error_messages = invoice_validator.get_error_messages(validation_errors)

            if error_messages:
                logger.info(f"Validation errors found, invoking Gemini Pro for correction")

                pro_invoice, pro_duration = ai_extractor.correct_with_pro(
                    ocr_result.text,
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
                    logger.warning("Pro correction failed, keeping Flash result")

        # ============================================================
        # STEP 5: Return result
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
