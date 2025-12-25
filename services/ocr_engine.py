"""
OCR Engine Module - Singleton Pattern
Handles PDF to text extraction using EasyOCR
"""
import io
import time
import logging
from typing import List, Tuple, Optional
from threading import Lock

import numpy as np
from PIL import Image

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    easyocr = None

try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    convert_from_bytes = None

from .config import config
from models.invoice import OCRResult

logger = logging.getLogger(__name__)


class OCREngine:
    """
    Singleton OCR Engine using EasyOCR
    Thread-safe lazy initialization
    """
    _instance: Optional["OCREngine"] = None
    _lock = Lock()
    _initialized = False

    def __new__(cls) -> "OCREngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if OCREngine._initialized:
            return

        with OCREngine._lock:
            if OCREngine._initialized:
                return

            logger.info("Initializing OCR Engine...")
            self._reader: Optional[easyocr.Reader] = None

            if EASYOCR_AVAILABLE:
                try:
                    start_time = time.time()
                    self._reader = easyocr.Reader(
                        config.OCR_LANGUAGES,
                        gpu=config.OCR_GPU,
                        verbose=False
                    )
                    elapsed = int((time.time() - start_time) * 1000)
                    logger.info(f"EasyOCR initialized in {elapsed}ms (GPU: {config.OCR_GPU})")
                except Exception as e:
                    logger.error(f"Failed to initialize EasyOCR: {e}")
                    self._reader = None
            else:
                logger.warning("EasyOCR not available. OCR functionality disabled.")

            OCREngine._initialized = True

    @property
    def is_available(self) -> bool:
        """Check if OCR engine is available"""
        return self._reader is not None

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> OCRResult:
        """
        Extract text from PDF file bytes

        Args:
            pdf_bytes: Raw PDF file content

        Returns:
            OCRResult with extracted text and metadata
        """
        start_time = time.time()
        logger.info("Starting PDF text extraction...")

        if not PDF2IMAGE_AVAILABLE:
            logger.error("pdf2image not available")
            return OCRResult(
                text="",
                confidence=0.0,
                page_count=0,
                raw_blocks=[]
            )

        if not self.is_available:
            logger.error("OCR Engine not available")
            return OCRResult(
                text="",
                confidence=0.0,
                page_count=0,
                raw_blocks=[]
            )

        try:
            # Convert PDF to images
            logger.debug("Converting PDF to images...")
            images = convert_from_bytes(pdf_bytes, dpi=200)
            page_count = len(images)
            logger.info(f"PDF converted: {page_count} page(s)")

            all_text_blocks: List[str] = []
            all_raw_blocks: List[dict] = []
            total_confidence = 0.0
            total_blocks = 0

            # Process each page
            for page_idx, image in enumerate(images):
                logger.debug(f"Processing page {page_idx + 1}/{page_count}...")

                # Convert PIL Image to numpy array
                img_array = np.array(image)

                # Run OCR
                results = self._reader.readtext(img_array)

                page_blocks: List[str] = []
                for bbox, text, confidence in results:
                    page_blocks.append(text)
                    all_raw_blocks.append({
                        "page": page_idx + 1,
                        "bbox": bbox,
                        "text": text,
                        "confidence": confidence
                    })
                    total_confidence += confidence
                    total_blocks += 1

                # Join text blocks for this page
                page_text = "\n".join(page_blocks)
                all_text_blocks.append(f"--- Page {page_idx + 1} ---\n{page_text}")

                logger.debug(f"Page {page_idx + 1}: {len(results)} text blocks extracted")

            # Combine all pages
            full_text = "\n\n".join(all_text_blocks)
            avg_confidence = total_confidence / total_blocks if total_blocks > 0 else 0.0

            elapsed = int((time.time() - start_time) * 1000)
            logger.info(
                f"OCR completed in {elapsed}ms: "
                f"{total_blocks} blocks, avg confidence: {avg_confidence:.2%}"
            )

            return OCRResult(
                text=full_text,
                confidence=avg_confidence,
                page_count=page_count,
                raw_blocks=all_raw_blocks
            )

        except Exception as e:
            logger.exception(f"OCR extraction failed: {e}")
            return OCRResult(
                text="",
                confidence=0.0,
                page_count=0,
                raw_blocks=[]
            )

    def extract_text_from_image(self, image_bytes: bytes) -> Tuple[str, float]:
        """
        Extract text from a single image

        Args:
            image_bytes: Raw image content

        Returns:
            Tuple of (extracted_text, confidence)
        """
        if not self.is_available:
            return "", 0.0

        try:
            image = Image.open(io.BytesIO(image_bytes))
            img_array = np.array(image)

            results = self._reader.readtext(img_array)

            texts = [text for _, text, _ in results]
            confidences = [conf for _, _, conf in results]

            full_text = "\n".join(texts)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            return full_text, avg_confidence

        except Exception as e:
            logger.exception(f"Image OCR failed: {e}")
            return "", 0.0


# Global singleton instance
ocr_engine = OCREngine()
