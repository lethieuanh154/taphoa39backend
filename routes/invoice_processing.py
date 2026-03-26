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

    def _validate_file_request(processing_log):
        """Common file validation for invoice endpoints"""
        if "file" not in request.files:
            return None, None, None, (jsonify(ProcessingResult(
                success=False,
                error="Không có file trong request",
                processing_log=processing_log
            ).model_dump()), 400)

        file = request.files["file"]
        if file.filename == "":
            return None, None, None, (jsonify(ProcessingResult(
                success=False,
                error="Tên file trống",
                processing_log=processing_log
            ).model_dump()), 400)

        if not allowed_file(file.filename):
            return None, None, None, (jsonify(ProcessingResult(
                success=False,
                error="Chỉ chấp nhận file PDF, JPG, PNG",
                processing_log=processing_log
            ).model_dump()), 400)

        file_bytes = file.read()
        file_size = len(file_bytes)

        if file_size > config.MAX_FILE_SIZE:
            return None, None, None, (jsonify(ProcessingResult(
                success=False,
                error=f"File quá lớn ({file_size / 1024 / 1024:.1f}MB). Tối đa 10MB",
                processing_log=processing_log
            ).model_dump()), 400)

        return file, file_bytes, file_size, None

    @bp.route("/process-invoice", methods=["POST"])
    def process_invoice():
        """
        Process invoice PDF/image and extract structured data

        Flow:
        1. Flash: Read file with Gemini Flash Vision + confidence scoring
        2. Validate: Check for missing/invalid fields
        3. Pro recheck: If confidence < 0.8 or validation fails

        Returns:
            ProcessingResult as JSON (with confidence + low_confidence_fields)
        """
        total_start_time = time.time()
        processing_log: List[ProcessingLogEntry] = []

        logger.info("=" * 60)
        logger.info("Starting invoice processing request (Direct Gemini)")

        # STEP 0: Validate request
        file, file_bytes, file_size, error_response = _validate_file_request(processing_log)
        if error_response:
            return error_response

        logger.info(f"Processing file: {file.filename} ({file_size / 1024:.1f}KB)")

        # STEP 1: Gemini Flash - Read file with confidence scoring
        flash_invoice, flash_duration, confidence, low_fields = ai_extractor.extract_from_image_with_flash(
            file_bytes,
            file.filename,
            processing_log,
            use_image_prompt=False
        )

        if flash_invoice is None:
            logger.warning("Flash extraction failed, trying Pro...")
            pro_invoice, pro_duration, confidence, low_fields = ai_extractor.recheck_with_pro(
                file_bytes,
                file.filename,
                None,
                [],
                processing_log
            ) if False else (None, 0, 0.0, [])

            # Fallback to legacy PDF method if new method fails
            flash_invoice, flash_duration = ai_extractor.extract_from_pdf_with_flash(
                file_bytes, processing_log
            )
            confidence = 0.5
            low_fields = []

            if flash_invoice is None:
                return jsonify(ProcessingResult(
                    success=False,
                    error="Không thể trích xuất thông tin từ hóa đơn",
                    processing_time_ms=int((time.time() - total_start_time) * 1000),
                    processing_log=processing_log
                ).model_dump()), 500

        # STEP 2: Validate
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

        logger.info(f"Validation: {'PASS' if is_valid else 'FAIL'}, Confidence: {confidence}")

        # STEP 3: Gemini Pro recheck if confidence < 0.8 or validation fails
        final_invoice = flash_invoice
        processing_method = "flash"

        needs_recheck = confidence < 0.8 or not is_valid

        if needs_recheck:
            logger.info(f"Recheck needed: confidence={confidence}, valid={is_valid}")

            if not is_valid:
                error_messages = invoice_validator.get_error_messages(validation_errors)
                recheck_fields = low_fields + [e for e in error_messages]
            else:
                recheck_fields = low_fields

            pro_invoice, pro_duration, pro_confidence, pro_low_fields = ai_extractor.recheck_with_pro(
                file_bytes,
                file.filename,
                flash_invoice,
                recheck_fields,
                processing_log,
                use_image_prompt=False
            )

            if pro_invoice is not None:
                is_valid_pro, validation_errors_pro = invoice_validator.validate(pro_invoice)

                if pro_confidence > confidence or is_valid_pro or len(validation_errors_pro) < len(validation_errors):
                    final_invoice = pro_invoice
                    validation_errors = validation_errors_pro
                    processing_method = "pro"
                    confidence = pro_confidence
                    low_fields = pro_low_fields
                    logger.info(f"Using Pro result (confidence: {pro_confidence})")
                else:
                    logger.info("Pro result not better, keeping Flash result")
            else:
                logger.warning("Pro recheck failed, keeping Flash result")

        # STEP 4: Return result
        total_duration = int((time.time() - total_start_time) * 1000)

        logger.info(
            f"Processing complete in {total_duration}ms using {processing_method}. "
            f"Items: {len(final_invoice.items)}, Confidence: {confidence}"
        )
        logger.info("=" * 60)

        return jsonify(ProcessingResult(
            success=True,
            invoice=final_invoice,
            validation_errors=validation_errors,
            processing_method=processing_method,
            processing_time_ms=total_duration,
            processing_log=processing_log,
            confidence=confidence,
            low_confidence_fields=low_fields
        ).model_dump())

    @bp.route("/process-image", methods=["POST"])
    def process_image():
        """
        Process image (JPG/PNG/PDF) for Clone product invoice extraction.
        Uses IMAGE prompt that ignores handwritten/pen text.

        Flow: Flash (image prompt) → confidence check → Pro recheck if needed

        Returns:
            ProcessingResult as JSON
        """
        total_start_time = time.time()
        processing_log: List[ProcessingLogEntry] = []

        logger.info("=" * 60)
        logger.info("Starting image processing request (Clone invoice)")

        # Validate request
        file, file_bytes, file_size, error_response = _validate_file_request(processing_log)
        if error_response:
            return error_response

        logger.info(f"Processing image: {file.filename} ({file_size / 1024:.1f}KB)")

        # STEP 1: Flash with image prompt (ignore handwriting)
        flash_invoice, flash_duration, confidence, low_fields = ai_extractor.extract_from_image_with_flash(
            file_bytes,
            file.filename,
            processing_log,
            use_image_prompt=True
        )

        if flash_invoice is None:
            return jsonify(ProcessingResult(
                success=False,
                error="Không thể trích xuất thông tin từ ảnh",
                processing_time_ms=int((time.time() - total_start_time) * 1000),
                processing_log=processing_log
            ).model_dump()), 500

        # STEP 2: Pro recheck if confidence < 0.8
        final_invoice = flash_invoice
        processing_method = "flash"

        if confidence < 0.8 and low_fields:
            logger.info(f"Low confidence ({confidence}), rechecking with Pro...")

            pro_invoice, pro_duration, pro_confidence, pro_low_fields = ai_extractor.recheck_with_pro(
                file_bytes,
                file.filename,
                flash_invoice,
                low_fields,
                processing_log,
                use_image_prompt=True
            )

            if pro_invoice is not None and pro_confidence > confidence:
                final_invoice = pro_invoice
                processing_method = "pro"
                confidence = pro_confidence
                low_fields = pro_low_fields
                logger.info(f"Using Pro result (confidence: {pro_confidence})")

        total_duration = int((time.time() - total_start_time) * 1000)

        logger.info(
            f"Image processing complete in {total_duration}ms using {processing_method}. "
            f"Items: {len(final_invoice.items)}, Confidence: {confidence}"
        )
        logger.info("=" * 60)

        return jsonify(ProcessingResult(
            success=True,
            invoice=final_invoice,
            validation_errors=[],
            processing_method=processing_method,
            processing_time_ms=total_duration,
            processing_log=processing_log,
            confidence=confidence,
            low_confidence_fields=low_fields
        ).model_dump())

    @bp.route("/parse-xml", methods=["POST"])
    def parse_xml_invoice():
        """
        Parse XML invoice file directly (no AI needed).
        Accepts .xml file upload, returns parsed invoice data.
        """
        from services.invoice_parsers import TaxInvoiceXMLParser

        if "file" not in request.files:
            return jsonify({"success": False, "error": "Không có file trong request"}), 400

        file = request.files["file"]
        if not file.filename or not file.filename.lower().endswith('.xml'):
            return jsonify({"success": False, "error": "Chỉ chấp nhận file XML"}), 400

        try:
            xml_bytes = file.read()
            invoices, errors = TaxInvoiceXMLParser.parse(xml_bytes)

            if not invoices:
                return jsonify({
                    "success": False,
                    "error": "Không thể đọc dữ liệu từ file XML",
                    "parse_errors": errors
                }), 400

            return jsonify({
                "success": True,
                "invoices": invoices,
                "parse_errors": errors
            })
        except Exception as e:
            logger.exception(f"XML parse error: {e}")
            return jsonify({"success": False, "error": f"Lỗi parse XML: {str(e)}"}), 500

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
