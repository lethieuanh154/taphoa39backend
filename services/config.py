"""
Configuration module for Invoice Processing
"""
import os
from dotenv import load_dotenv

load_dotenv()


class InvoiceProcessingConfig:
    """Invoice Processing configuration"""

    # Gemini API
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL")
    GEMINI_PRO_MODEL = os.getenv("GEMINI_PRO_MODEL")

    # OCR
    OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "vi,en").split(",")
    OCR_GPU = os.getenv("OCR_GPU", "False").lower() == "true"

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

    # File limits
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}

    # Validation thresholds
    AMOUNT_TOLERANCE = 1.0  # Cho phép sai số 1 đồng
    VAT_RATES = [0, 5, 8, 10]  # Các mức VAT hợp lệ (%)


config = InvoiceProcessingConfig()
