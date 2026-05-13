"""
AI Extractor Module
Handles invoice data extraction using Gemini Flash and Pro models
Direct PDF reading with Gemini Vision (no OCR needed)
Updated to use new google.genai SDK (replacing deprecated google.generativeai)
"""
import json
import re
import time
import logging
import base64
from typing import Optional, Tuple, List

from google import genai
from google.genai import types

from .config import config
from models.invoice import ProcessedInvoice, ProcessingLogEntry

logger = logging.getLogger(__name__)


def normalize_model_name(model_name: str) -> str:
    """
    Normalize model name for Gemini API
    Removes 'models/' prefix if present as SDK adds it automatically
    """
    if model_name.startswith("models/"):
        return model_name[7:]  # Remove 'models/' prefix
    return model_name


# Prompt template for direct PDF extraction (no OCR)
INVOICE_PDF_EXTRACTION_PROMPT = """Bạn là một AI chuyên trích xuất thông tin từ hóa đơn VAT Việt Nam.

Hãy đọc file PDF hóa đơn đính kèm và trích xuất thông tin, trả về JSON với cấu trúc sau (chỉ trả về JSON, không có text khác):

{
  "invoice_metadata": {
    "invoice_date": "dd/mm/yyyy",
    "invoice_no": "số hóa đơn",
    "invoice_serial": "ký hiệu hóa đơn",
    "tax_authority_code": "mã cơ quan thuế"
  },
  "seller": {
    "company_name": "tên công ty bán hàng",
    "tax_code": "mã số thuế người bán",
    "address": "địa chỉ người bán"
  },
  "buyer": {
    "company_name": "tên công ty mua hàng",
    "tax_code": "mã số thuế người mua",
    "address": "địa chỉ người mua"
  },
  "items": [
    {
      "stt": 1,
      "description": "tên hàng hóa/dịch vụ",
      "unit": "đơn vị tính",
      "quantity": 0,
      "unit_price": 0,
      "amount": 0
    }
  ],
  "summary": {
    "total_amount_before_vat": 0,
    "vat_rate": "10%",
    "vat_amount": 0,
    "total_payment": 0,
    "total_payment_in_words": "bằng chữ"
  }
}

LƯU Ý QUAN TRỌNG:
1. ĐỌC CHÍNH XÁC các giá trị từ hóa đơn, KHÔNG tính toán lại
2. Tất cả giá trị số tiền phải là số nguyên (không có dấu phẩy, dấu chấm)
3. quantity có thể là số thập phân
4. unit_price và amount phải là số nguyên
5. Đọc đúng các giá trị: total_amount_before_vat, vat_amount, total_payment từ hóa đơn
6. Nếu không tìm thấy thông tin, để trống hoặc 0
7. vat_rate phải có dạng "X%" (ví dụ: "10%", "8%", "5%", "0%")
"""

# Prompt template for OCR text extraction (legacy, kept for fallback)
INVOICE_EXTRACTION_PROMPT = """Bạn là một AI chuyên trích xuất thông tin từ hóa đơn VAT Việt Nam.

Dữ liệu OCR từ hóa đơn:
---
{ocr_text}
---

Hãy trích xuất thông tin và trả về JSON với cấu trúc sau (chỉ trả về JSON, không có text khác):

{{
  "invoice_metadata": {{
    "invoice_date": "dd/mm/yyyy",
    "invoice_no": "số hóa đơn",
    "invoice_serial": "ký hiệu hóa đơn",
    "tax_authority_code": "mã cơ quan thuế"
  }},
  "seller": {{
    "company_name": "tên công ty bán hàng",
    "tax_code": "mã số thuế người bán",
    "address": "địa chỉ người bán"
  }},
  "buyer": {{
    "company_name": "tên công ty mua hàng",
    "tax_code": "mã số thuế người mua",
    "address": "địa chỉ người mua"
  }},
  "items": [
    {{
      "stt": 1,
      "description": "tên hàng hóa/dịch vụ",
      "unit": "đơn vị tính",
      "quantity": 0,
      "unit_price": 0,
      "amount": 0,
      "vat_rate": "8%",
      "vat_amount": 0,
      "amount_after_vat": 0
    }}
  ],
  "summary": {{
    "total_amount_before_vat": 0,
    "vat_rate": "10%",
    "vat_amount": 0,
    "total_payment": 0,
    "total_payment_in_words": "bằng chữ"
  }}
}}

LƯU Ý QUAN TRỌNG:
1. Tất cả giá trị số tiền phải là số nguyên (không có dấu phẩy, dấu chấm)
2. quantity có thể là số thập phân
3. unit_price và amount phải là số nguyên
4. Đảm bảo: amount = quantity × unit_price (cho mỗi item, thành tiền TRƯỚC thuế)
5. vat_rate của mỗi item phải có dạng "X%" (ví dụ: "10%", "8%", "5%", "0%")
6. vat_amount = amount × vat_rate (tiền thuế của mỗi item)
7. amount_after_vat = amount + vat_amount (thành tiền SAU thuế của mỗi item)
8. Đảm bảo: total_amount_before_vat = tổng các amount
9. Đảm bảo: total_payment = total_amount_before_vat + vat_amount
10. Nếu không tìm thấy thông tin, để trống hoặc 0
11. summary.vat_rate là thuế suất chung, nếu các item có thuế suất khác nhau thì để "mixed"
"""

INVOICE_IMAGE_EXTRACTION_PROMPT = """Bạn là một AI chuyên trích xuất thông tin từ hóa đơn/phiếu giao hàng Việt Nam.
Hãy đọc ảnh đính kèm và trích xuất thông tin, trả về JSON với cấu trúc sau (chỉ trả về JSON, không có text khác):

{
  "invoice_metadata": {
    "invoice_date": "dd/mm/yyyy",
    "invoice_no": "số hóa đơn hoặc số phiếu",
    "invoice_serial": "ký hiệu (nếu có)",
    "tax_authority_code": ""
  },
  "seller": {
    "company_name": "tên công ty bán hàng",
    "tax_code": "mã số thuế người bán (nếu có)",
    "address": "địa chỉ người bán (nếu có)"
  },
  "buyer": {
    "company_name": "tên công ty/người mua (nếu có)",
    "tax_code": "",
    "address": ""
  },
  "items": [
    {
      "stt": 1,
      "description": "tên hàng hóa/dịch vụ",
      "unit": "đơn vị tính",
      "quantity": 0,
      "unit_price": 0,
      "amount": 0,
      "vat_rate": "8%",
      "vat_amount": 0,
      "amount_after_vat": 0
    }
  ],
  "summary": {
    "total_amount_before_vat": 0,
    "vat_rate": "0%",
    "vat_amount": 0,
    "total_payment": 0,
    "total_payment_in_words": ""
  }
}

LƯU Ý QUAN TRỌNG:
1. BỎ QUA tất cả chữ viết tay, bút bi xanh, ghi chú bằng tay. CHỈ đọc phần văn bản được IN MÁY
2. ĐỌC CHÍNH XÁC các giá trị từ hình ảnh, KHÔNG tính toán lại
3. Tất cả giá trị số tiền phải là số nguyên (không có dấu phẩy, dấu chấm)
4. quantity có thể là số thập phân
5. unit_price và amount phải là số nguyên
6. amount = thành tiền TRƯỚC thuế, amount_after_vat = thành tiền SAU thuế
7. vat_rate của mỗi item phải có dạng "X%" (ví dụ: "10%", "8%", "5%", "0%")
8. Nếu không tìm thấy thông tin, để trống hoặc 0
9. Nếu không có VAT, để vat_rate = "0%", vat_amount = 0, amount_after_vat = amount
10. total_payment = tổng tiền thanh toán cuối cùng
"""

INVOICE_CORRECTION_PROMPT = """Bạn là một AI chuyên xử lý hóa đơn VAT Việt Nam.

Kết quả trích xuất trước đó có các lỗi tính toán:
{validation_errors}

Dữ liệu OCR gốc:
---
{ocr_text}
---

Dữ liệu đã trích xuất (có lỗi):
{previous_result}

Hãy sửa các lỗi tính toán và trả về JSON hoàn chỉnh với cấu trúc giống như trước.
Đảm bảo:
1. amount = quantity × unit_price (cho mỗi item)
2. total_amount_before_vat = tổng các amount của tất cả items
3. vat_amount = total_amount_before_vat × vat_rate / 100
4. total_payment = total_amount_before_vat + vat_amount

Chỉ trả về JSON, không có text khác.
"""


class AIExtractor:
    """
    AI-powered invoice data extractor
    Uses Gemini Flash for speed, Pro for accuracy when needed
    Updated to use new google.genai SDK
    """

    def __init__(self):
        self._client = None
        self._flash_model_name = None
        self._pro_model_name = None
        self._generation_config = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization of Gemini client"""
        if self._initialized:
            return

        if not config.GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY not configured")
            raise ValueError("GEMINI_API_KEY is required")

        logger.info("Initializing Gemini AI client (new SDK)...")

        # Initialize client with API key
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)

        # Normalize model names (remove 'models/' prefix if present)
        self._flash_model_name = normalize_model_name(config.GEMINI_FLASH_MODEL)
        self._pro_model_name = normalize_model_name(config.GEMINI_PRO_MODEL)

        # Generation config optimized for Gemini
        self._generation_config = types.GenerateContentConfig(
            temperature=0.1,
            top_p=0.95,
            max_output_tokens=8192,
        )

        logger.info(f"Flash model: {self._flash_model_name}")
        logger.info(f"Pro model: {self._pro_model_name}")

        self._initialized = True

    def _list_available_models(self) -> List[str]:
        """List available Gemini models for debugging"""
        try:
            self._ensure_initialized()
            models = self._client.models.list()
            available = [m.name for m in models]
            logger.info(f"Available models: {available}")
            return available
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []

    def extract_from_pdf_with_flash(
        self,
        pdf_bytes: bytes,
        processing_log: List[ProcessingLogEntry]
    ) -> Tuple[Optional[ProcessedInvoice], int]:
        """
        Extract invoice data directly from PDF using Gemini Flash Vision

        Args:
            pdf_bytes: PDF file content as bytes
            processing_log: List to append log entries

        Returns:
            Tuple of (ProcessedInvoice or None, duration_ms)
        """
        self._ensure_initialized()

        log_entry = ProcessingLogEntry(
            step="flash",
            status="processing",
            message="Đang đọc PDF với Gemini Flash..."
        )
        processing_log.append(log_entry)

        start_time = time.time()

        try:
            logger.debug(f"Processing PDF with Gemini Flash, size: {len(pdf_bytes)} bytes")

            # Create PDF part for multimodal input
            pdf_part = types.Part.from_bytes(
                data=pdf_bytes,
                mime_type="application/pdf"
            )

            # Send to Gemini Flash with PDF
            response = self._client.models.generate_content(
                model=self._flash_model_name,
                contents=[INVOICE_PDF_EXTRACTION_PROMPT, pdf_part],
                config=self._generation_config
            )
            response_text = response.text.strip()

            # Parse JSON response
            invoice = self._parse_response(response_text)

            elapsed = int((time.time() - start_time) * 1000)

            if invoice is None:
                log_entry.status = "error"
                log_entry.message = "Không thể parse JSON từ response"
                log_entry.duration_ms = elapsed
                log_entry.details = f"Response: {response_text[:200]}..."
                logger.error(f"Flash PDF parse failed, response: {response_text[:500]}")
                return None, elapsed

            log_entry.status = "completed"
            log_entry.message = "Đọc PDF Flash hoàn tất"
            log_entry.duration_ms = elapsed
            log_entry.details = f"Extracted {len(invoice.items)} items"

            logger.info(f"Flash PDF extraction completed in {elapsed}ms")
            return invoice, elapsed

        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            log_entry.status = "error"
            log_entry.message = f"Lỗi Flash: {str(e)}"
            log_entry.duration_ms = elapsed

            logger.exception(f"Flash PDF extraction failed: {e}")
            return None, elapsed

    def extract_from_pdf_with_pro(
        self,
        pdf_bytes: bytes,
        previous_result: Optional[ProcessedInvoice],
        validation_errors: List[str],
        processing_log: List[ProcessingLogEntry]
    ) -> Tuple[Optional[ProcessedInvoice], int]:
        """
        Extract/correct invoice data from PDF using Gemini Pro Vision

        Args:
            pdf_bytes: PDF file content as bytes
            previous_result: Previous extraction result (if any)
            validation_errors: List of validation error messages
            processing_log: List to append log entries

        Returns:
            Tuple of (ProcessedInvoice or None, duration_ms)
        """
        self._ensure_initialized()

        log_entry = ProcessingLogEntry(
            step="pro",
            status="processing",
            message="Đang đọc PDF với Gemini Pro..."
        )
        processing_log.append(log_entry)

        start_time = time.time()

        try:
            # Create PDF part for multimodal input
            pdf_part = types.Part.from_bytes(
                data=pdf_bytes,
                mime_type="application/pdf"
            )

            # Build prompt with error context if available
            if previous_result and validation_errors:
                previous_json = previous_result.model_dump_json(indent=2)
                errors_text = "\n".join(f"- {e}" for e in validation_errors)
                prompt = f"""{INVOICE_PDF_EXTRACTION_PROMPT}

Kết quả trước đó có vấn đề:
{errors_text}

Hãy đọc lại PDF và trích xuất chính xác."""
            else:
                prompt = INVOICE_PDF_EXTRACTION_PROMPT

            # Send to Gemini Pro with PDF
            response = self._client.models.generate_content(
                model=self._pro_model_name,
                contents=[prompt, pdf_part],
                config=self._generation_config
            )
            response_text = response.text.strip()

            # Parse JSON response
            invoice = self._parse_response(response_text)

            elapsed = int((time.time() - start_time) * 1000)

            if invoice is None:
                log_entry.status = "error"
                log_entry.message = "Không thể parse JSON từ response"
                log_entry.duration_ms = elapsed
                log_entry.details = f"Response: {response_text[:200]}..."
                logger.error(f"Pro PDF parse failed, response: {response_text[:500]}")
                return None, elapsed

            log_entry.status = "completed"
            log_entry.message = "Đọc PDF Pro hoàn tất"
            log_entry.duration_ms = elapsed
            log_entry.details = f"Extracted {len(invoice.items)} items"

            logger.info(f"Pro PDF extraction completed in {elapsed}ms")
            return invoice, elapsed

        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            log_entry.status = "error"
            log_entry.message = f"Lỗi Pro: {str(e)}"
            log_entry.duration_ms = elapsed

            logger.exception(f"Pro PDF extraction failed: {e}")
            return None, elapsed

    def extract_from_pdf_with_markitdown(
        self,
        pdf_bytes: bytes,
        filename: str,
        processing_log: List[ProcessingLogEntry]
    ) -> Tuple[Optional[ProcessedInvoice], int, float, List[str]]:
        """
        Extract invoice data from PDF using MarkItDown (PDF → Markdown text) + Gemini Flash (text).
        Returns (None, ...) if MarkItDown fails — caller should fallback to Gemini Vision.
        """
        self._ensure_initialized()

        log_entry = ProcessingLogEntry(
            step="markitdown",
            status="processing",
            message="Đang đọc PDF với MarkItDown..."
        )
        processing_log.append(log_entry)

        start_time = time.time()

        try:
            from markitdown import MarkItDown
            import io

            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".pdf"
            md_converter = MarkItDown()
            result = md_converter.convert_stream(io.BytesIO(pdf_bytes), file_extension=ext)
            markdown_text = result.text_content

            if not markdown_text or len(markdown_text.strip()) < 50:
                elapsed = int((time.time() - start_time) * 1000)
                log_entry.status = "error"
                log_entry.message = "MarkItDown: không trích xuất được text (có thể là PDF scan)"
                log_entry.duration_ms = elapsed
                logger.warning("MarkItDown returned empty/short text, caller should fallback to Vision")
                return None, elapsed, 0.0, []

            logger.info(f"MarkItDown extracted {len(markdown_text)} chars from {filename}")
            log_entry.message = f"MarkItDown OK ({len(markdown_text)} ký tự), đang gọi Gemini Flash..."

            prompt = INVOICE_EXTRACTION_PROMPT.format(ocr_text=markdown_text)
            response = self._client.models.generate_content(
                model=self._flash_model_name,
                contents=prompt,
                config=self._generation_config
            )
            response_text = response.text.strip()

            invoice = self._parse_response(response_text)
            confidence, low_fields = self._calculate_confidence(invoice)

            elapsed = int((time.time() - start_time) * 1000)

            if invoice is None:
                log_entry.status = "error"
                log_entry.message = "Không thể parse JSON từ Gemini response"
                log_entry.duration_ms = elapsed
                log_entry.details = f"Response: {response_text[:200]}..."
                return None, elapsed, 0.0, []

            log_entry.status = "completed"
            log_entry.message = f"MarkItDown + Flash hoàn tất (confidence: {confidence:.0%})"
            log_entry.duration_ms = elapsed
            log_entry.details = f"Extracted {len(invoice.items)} items, confidence={confidence}"

            logger.info(f"MarkItDown + Flash completed in {elapsed}ms, confidence={confidence}")
            return invoice, elapsed, confidence, low_fields

        except ImportError:
            elapsed = int((time.time() - start_time) * 1000)
            log_entry.status = "error"
            log_entry.message = "MarkItDown chưa được cài đặt (pip install markitdown[pdf])"
            log_entry.duration_ms = elapsed
            logger.warning("MarkItDown not installed, falling back to Gemini Vision")
            return None, elapsed, 0.0, []

        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            log_entry.status = "error"
            log_entry.message = f"Lỗi MarkItDown: {str(e)}"
            log_entry.duration_ms = elapsed
            logger.exception(f"MarkItDown extraction failed: {e}")
            return None, elapsed, 0.0, []

    def _get_mime_type(self, file_bytes: bytes, filename: str = "") -> str:
        """Detect MIME type from file extension or magic bytes"""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime_map = {
            "pdf": "application/pdf",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
        }
        if ext in mime_map:
            return mime_map[ext]
        # Fallback: check magic bytes
        if file_bytes[:4] == b'%PDF':
            return "application/pdf"
        if file_bytes[:3] == b'\xff\xd8\xff':
            return "image/jpeg"
        if file_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        return "application/octet-stream"

    def _calculate_confidence(self, invoice) -> tuple:
        """
        Calculate confidence score for extracted invoice data.
        Returns (confidence: float, low_confidence_fields: list[str])
        """
        if invoice is None:
            return 0.0, []

        low_fields = []
        checks = 0
        passed = 0

        # Check metadata
        checks += 2
        if invoice.invoice_metadata.invoice_no:
            passed += 1
        else:
            low_fields.append("invoice_metadata.invoice_no")
        if invoice.invoice_metadata.invoice_date:
            passed += 1
        else:
            low_fields.append("invoice_metadata.invoice_date")

        # Check seller
        checks += 1
        if invoice.seller.company_name:
            passed += 1
        else:
            low_fields.append("seller.company_name")

        # Check items
        checks += 1
        if len(invoice.items) > 0:
            passed += 1
        else:
            low_fields.append("items")

        # Check each item quality
        for i, item in enumerate(invoice.items):
            checks += 3
            if item.description:
                passed += 1
            else:
                low_fields.append(f"items[{i}].description")
            if item.quantity > 0:
                passed += 1
            else:
                low_fields.append(f"items[{i}].quantity")
            if item.unit_price > 0 or item.amount > 0:
                passed += 1
            else:
                low_fields.append(f"items[{i}].unit_price")

        # Check summary
        checks += 1
        if invoice.summary.total_payment > 0:
            passed += 1
        else:
            low_fields.append("summary.total_payment")

        # Math checks: amount = quantity × unit_price per item
        tolerance = 1.0
        for i, item in enumerate(invoice.items):
            if item.quantity > 0 and item.unit_price > 0 and item.amount > 0:
                checks += 1
                expected = item.quantity * item.unit_price
                if abs(expected - item.amount) <= tolerance:
                    passed += 1
                else:
                    low_fields.append(f"items[{i}].amount_math")

        # Math check: total_amount_before_vat = sum(items.amount)
        items_total = sum(item.amount for item in invoice.items)
        if items_total > 0 and invoice.summary.total_amount_before_vat > 0:
            checks += 1
            if abs(items_total - invoice.summary.total_amount_before_vat) <= tolerance:
                passed += 1
            else:
                low_fields.append("summary.total_amount_before_vat_math")

        # Math check: total_payment = total_amount_before_vat + vat_amount
        if invoice.summary.total_amount_before_vat > 0 and invoice.summary.total_payment > 0:
            checks += 1
            expected_total = invoice.summary.total_amount_before_vat + invoice.summary.vat_amount
            if abs(expected_total - invoice.summary.total_payment) <= tolerance:
                passed += 1
            else:
                low_fields.append("summary.total_payment_math")

        confidence = passed / checks if checks > 0 else 0.0
        return round(confidence, 3), low_fields

    def extract_from_image_with_flash(
        self,
        file_bytes: bytes,
        filename: str,
        processing_log: List[ProcessingLogEntry],
        use_image_prompt: bool = False
    ) -> Tuple[Optional[ProcessedInvoice], int, float, List[str]]:
        """
        Extract invoice data from image/PDF using Gemini Flash Vision.

        Args:
            file_bytes: File content as bytes (PDF, JPG, PNG)
            filename: Original filename for MIME detection
            processing_log: List to append log entries
            use_image_prompt: If True, use IMAGE prompt (ignore handwriting)

        Returns:
            Tuple of (ProcessedInvoice or None, duration_ms, confidence, low_confidence_fields)
        """
        self._ensure_initialized()

        log_entry = ProcessingLogEntry(
            step="flash",
            status="processing",
            message="Đang đọc file với Gemini Flash..."
        )
        processing_log.append(log_entry)

        start_time = time.time()

        try:
            mime_type = self._get_mime_type(file_bytes, filename)
            logger.debug(f"Processing file with Gemini Flash, size: {len(file_bytes)} bytes, mime: {mime_type}")

            file_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

            prompt = INVOICE_IMAGE_EXTRACTION_PROMPT if use_image_prompt else INVOICE_PDF_EXTRACTION_PROMPT

            response = self._client.models.generate_content(
                model=self._flash_model_name,
                contents=[prompt, file_part],
                config=self._generation_config
            )
            response_text = response.text.strip()

            invoice = self._parse_response(response_text)
            confidence, low_fields = self._calculate_confidence(invoice)

            elapsed = int((time.time() - start_time) * 1000)

            if invoice is None:
                log_entry.status = "error"
                log_entry.message = "Không thể parse JSON từ response"
                log_entry.duration_ms = elapsed
                log_entry.details = f"Response: {response_text[:200]}..."
                logger.error(f"Flash parse failed, response: {response_text[:500]}")
                return None, elapsed, 0.0, []

            log_entry.status = "completed"
            log_entry.message = f"Đọc Flash hoàn tất (confidence: {confidence:.0%})"
            log_entry.duration_ms = elapsed
            log_entry.details = f"Extracted {len(invoice.items)} items, confidence={confidence}"

            logger.info(f"Flash extraction completed in {elapsed}ms, confidence={confidence}")
            return invoice, elapsed, confidence, low_fields

        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            log_entry.status = "error"
            log_entry.message = f"Lỗi Flash: {str(e)}"
            log_entry.duration_ms = elapsed

            logger.exception(f"Flash extraction failed: {e}")
            return None, elapsed, 0.0, []

    def recheck_with_pro(
        self,
        file_bytes: bytes,
        filename: str,
        previous_result: ProcessedInvoice,
        low_confidence_fields: List[str],
        processing_log: List[ProcessingLogEntry],
        use_image_prompt: bool = False
    ) -> Tuple[Optional[ProcessedInvoice], int, float, List[str]]:
        """
        Recheck extraction using Gemini Pro when confidence is low.

        Args:
            file_bytes: File content as bytes
            filename: Original filename for MIME detection
            previous_result: Previous extraction result
            low_confidence_fields: Fields with low confidence
            processing_log: List to append log entries
            use_image_prompt: If True, use IMAGE prompt (ignore handwriting)

        Returns:
            Tuple of (ProcessedInvoice or None, duration_ms, confidence, low_confidence_fields)
        """
        self._ensure_initialized()

        log_entry = ProcessingLogEntry(
            step="pro",
            status="processing",
            message="Đang recheck với Gemini Pro..."
        )
        processing_log.append(log_entry)

        start_time = time.time()

        try:
            mime_type = self._get_mime_type(file_bytes, filename)
            file_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

            base_prompt = INVOICE_IMAGE_EXTRACTION_PROMPT if use_image_prompt else INVOICE_PDF_EXTRACTION_PROMPT

            previous_json = previous_result.model_dump_json(indent=2)
            fields_text = "\n".join(f"- {f}" for f in low_confidence_fields)
            prompt = f"""{base_prompt}

Kết quả lần đọc trước (có thể chưa chính xác):
{previous_json}

Các trường cần kiểm tra lại (độ chính xác thấp):
{fields_text}

Hãy đọc lại file và trả về kết quả chính xác hơn. Đặc biệt chú ý các trường được đánh dấu ở trên."""

            response = self._client.models.generate_content(
                model=self._pro_model_name,
                contents=[prompt, file_part],
                config=self._generation_config
            )
            response_text = response.text.strip()

            invoice = self._parse_response(response_text)
            confidence, low_fields = self._calculate_confidence(invoice)

            elapsed = int((time.time() - start_time) * 1000)

            if invoice is None:
                log_entry.status = "error"
                log_entry.message = "Không thể parse JSON từ Pro response"
                log_entry.duration_ms = elapsed
                log_entry.details = f"Response: {response_text[:200]}..."
                return None, elapsed, 0.0, []

            log_entry.status = "completed"
            log_entry.message = f"Recheck Pro hoàn tất (confidence: {confidence:.0%})"
            log_entry.duration_ms = elapsed
            log_entry.details = f"Rechecked {len(invoice.items)} items, confidence={confidence}"

            logger.info(f"Pro recheck completed in {elapsed}ms, confidence={confidence}")
            return invoice, elapsed, confidence, low_fields

        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            log_entry.status = "error"
            log_entry.message = f"Lỗi Pro recheck: {str(e)}"
            log_entry.duration_ms = elapsed

            logger.exception(f"Pro recheck failed: {e}")
            return None, elapsed, 0.0, []

    def extract_with_flash(
        self,
        ocr_text: str,
        processing_log: List[ProcessingLogEntry]
    ) -> Tuple[Optional[ProcessedInvoice], int]:
        """
        Extract invoice data using Gemini Flash model (from OCR text)

        Args:
            ocr_text: Text extracted from PDF via OCR
            processing_log: List to append log entries

        Returns:
            Tuple of (ProcessedInvoice or None, duration_ms)
        """
        self._ensure_initialized()

        log_entry = ProcessingLogEntry(
            step="ai_flash",
            status="processing",
            message="Đang trích xuất với Gemini Flash..."
        )
        processing_log.append(log_entry)

        start_time = time.time()

        try:
            prompt = INVOICE_EXTRACTION_PROMPT.format(ocr_text=ocr_text)
            logger.debug(f"Sending to Gemini Flash, prompt length: {len(prompt)}")

            response = self._client.models.generate_content(
                model=self._flash_model_name,
                contents=prompt,
                config=self._generation_config
            )
            response_text = response.text.strip()

            # Parse JSON response
            invoice = self._parse_response(response_text)

            elapsed = int((time.time() - start_time) * 1000)

            log_entry.status = "completed"
            log_entry.message = "Trích xuất Flash hoàn tất"
            log_entry.duration_ms = elapsed
            log_entry.details = f"Extracted {len(invoice.items) if invoice else 0} items"

            logger.info(f"Flash extraction completed in {elapsed}ms")
            return invoice, elapsed

        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            log_entry.status = "error"
            log_entry.message = f"Lỗi Flash: {str(e)}"
            log_entry.duration_ms = elapsed

            logger.exception(f"Flash extraction failed: {e}")
            return None, elapsed

    def correct_with_pro(
        self,
        ocr_text: str,
        previous_result: ProcessedInvoice,
        validation_errors: List[str],
        processing_log: List[ProcessingLogEntry]
    ) -> Tuple[Optional[ProcessedInvoice], int]:
        """
        Correct invoice data using Gemini Pro model

        Args:
            ocr_text: Original OCR text
            previous_result: Invoice data from Flash extraction
            validation_errors: List of validation error messages
            processing_log: List to append log entries

        Returns:
            Tuple of (ProcessedInvoice or None, duration_ms)
        """
        self._ensure_initialized()

        log_entry = ProcessingLogEntry(
            step="ai_pro",
            status="processing",
            message="Đang sửa lỗi với Gemini Pro..."
        )
        processing_log.append(log_entry)

        start_time = time.time()

        try:
            # Format previous result as JSON
            previous_json = previous_result.model_dump_json(indent=2)
            errors_text = "\n".join(f"- {e}" for e in validation_errors)

            prompt = INVOICE_CORRECTION_PROMPT.format(
                validation_errors=errors_text,
                ocr_text=ocr_text,
                previous_result=previous_json
            )
            logger.debug(f"Sending to Gemini Pro, prompt length: {len(prompt)}")

            response = self._client.models.generate_content(
                model=self._pro_model_name,
                contents=prompt,
                config=self._generation_config
            )
            response_text = response.text.strip()

            # Parse JSON response
            invoice = self._parse_response(response_text)

            elapsed = int((time.time() - start_time) * 1000)

            log_entry.status = "completed"
            log_entry.message = "Sửa lỗi Pro hoàn tất"
            log_entry.duration_ms = elapsed
            log_entry.details = f"Corrected {len(validation_errors)} errors"

            logger.info(f"Pro correction completed in {elapsed}ms")
            return invoice, elapsed

        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            log_entry.status = "error"
            log_entry.message = f"Lỗi Pro: {str(e)}"
            log_entry.duration_ms = elapsed

            logger.exception(f"Pro correction failed: {e}")
            return None, elapsed

    def _parse_response(self, response_text: str) -> Optional[ProcessedInvoice]:
        """
        Parse Gemini response text to ProcessedInvoice

        Args:
            response_text: Raw response from Gemini

        Returns:
            ProcessedInvoice or None
        """
        try:
            # Remove markdown code blocks if present
            text = response_text.strip()

            # Handle various markdown formats
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]

            if text.endswith("```"):
                text = text[:-3]

            text = text.strip()

            # Try to extract JSON if there's extra text around it
            if not text.startswith("{"):
                json_match = re.search(r'\{[\s\S]*\}', text)
                if json_match:
                    text = json_match.group(0)

            # Parse JSON
            data = json.loads(text)

            # Convert to Pydantic model
            invoice = ProcessedInvoice(**data)

            logger.debug(f"Parsed invoice: {len(invoice.items)} items")
            return invoice

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            logger.debug(f"Raw response: {response_text[:500]}...")
            return None
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return None


# Global instance
ai_extractor = AIExtractor()
