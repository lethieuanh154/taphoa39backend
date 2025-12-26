"""
AI Extractor Module
Handles invoice data extraction using Gemini Flash and Pro models
Direct PDF reading with Gemini Vision (no OCR needed)
Supports Gemini 3 Preview models
"""
import json
import re
import time
import logging
import base64
from typing import Optional, Tuple, List

import google.generativeai as genai

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
      "amount": 0
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
4. Đảm bảo: amount = quantity × unit_price (cho mỗi item)
5. Đảm bảo: total_amount_before_vat = tổng các amount
6. Đảm bảo: total_payment = total_amount_before_vat + vat_amount
7. Nếu không tìm thấy thông tin, để trống hoặc 0
8. vat_rate phải có dạng "X%" (ví dụ: "10%", "8%", "5%", "0%")
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
    """

    def __init__(self):
        self._flash_model = None
        self._pro_model = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization of Gemini models"""
        if self._initialized:
            return

        if not config.GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY not configured")
            raise ValueError("GEMINI_API_KEY is required")

        logger.info("Initializing Gemini AI models...")
        genai.configure(api_key=config.GEMINI_API_KEY)

        # Normalize model names (remove 'models/' prefix if present)
        flash_model_name = normalize_model_name(config.GEMINI_FLASH_MODEL)
        pro_model_name = normalize_model_name(config.GEMINI_PRO_MODEL)

        # Generation config optimized for Gemini 3
        generation_config = {
            "temperature": 0.1,
            "top_p": 0.95,
            "max_output_tokens": 8192,
        }

        # Initialize Flash model (fast, for first pass)
        self._flash_model = genai.GenerativeModel(
            model_name=flash_model_name,
            generation_config=generation_config
        )
        logger.info(f"Flash model initialized: {flash_model_name}")

        # Initialize Pro model (accurate, for corrections)
        self._pro_model = genai.GenerativeModel(
            model_name=pro_model_name,
            generation_config=generation_config
        )
        logger.info(f"Pro model initialized: {pro_model_name}")

        self._initialized = True

    def _list_available_models(self) -> List[str]:
        """List available Gemini models for debugging"""
        try:
            models = genai.list_models()
            available = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
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
            # Upload PDF to Gemini
            logger.debug(f"Uploading PDF to Gemini, size: {len(pdf_bytes)} bytes")

            # Create file part for multimodal input
            pdf_part = {
                "mime_type": "application/pdf",
                "data": base64.b64encode(pdf_bytes).decode('utf-8')
            }

            # Send to Gemini Flash with PDF
            response = self._flash_model.generate_content([
                INVOICE_PDF_EXTRACTION_PROMPT,
                pdf_part
            ])
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
            # Create file part for multimodal input
            pdf_part = {
                "mime_type": "application/pdf",
                "data": base64.b64encode(pdf_bytes).decode('utf-8')
            }

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
            response = self._pro_model.generate_content([
                prompt,
                pdf_part
            ])
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

    def extract_with_flash(
        self,
        ocr_text: str,
        processing_log: List[ProcessingLogEntry]
    ) -> Tuple[Optional[ProcessedInvoice], int]:
        """
        Extract invoice data using Gemini Flash model

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

            response = self._flash_model.generate_content(prompt)
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

            response = self._pro_model.generate_content(prompt)
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
