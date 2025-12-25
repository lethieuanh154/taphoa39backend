"""
Pydantic models for Invoice Processing
Matches Angular Frontend interfaces
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class InvoiceMetadata(BaseModel):
    """Invoice metadata information"""
    invoice_date: str = ""
    invoice_no: str = ""
    invoice_serial: str = ""
    tax_authority_code: str = ""


class Party(BaseModel):
    """Seller or Buyer information"""
    company_name: str = ""
    tax_code: str = ""
    address: str = ""


class InvoiceItem(BaseModel):
    """Single invoice line item"""
    stt: int = 0
    description: str = ""
    unit: str = ""
    quantity: float = 0
    unit_price: float = 0
    amount: float = 0


class InvoiceSummary(BaseModel):
    """Invoice totals and summary"""
    total_amount_before_vat: float = 0
    vat_rate: str = "10%"
    vat_amount: float = 0
    total_payment: float = 0
    total_payment_in_words: str = ""


class ProcessedInvoice(BaseModel):
    """Complete processed invoice data"""
    invoice_metadata: InvoiceMetadata = Field(default_factory=InvoiceMetadata)
    seller: Party = Field(default_factory=Party)
    buyer: Party = Field(default_factory=Party)
    items: List[InvoiceItem] = Field(default_factory=list)
    summary: InvoiceSummary = Field(default_factory=InvoiceSummary)


class ValidationError(BaseModel):
    """Validation error entry"""
    field: str
    message: str
    severity: Literal["error", "warning"] = "error"
    expected_value: Optional[float] = None
    actual_value: Optional[float] = None


class ProcessingLogEntry(BaseModel):
    """Single log entry for processing steps"""
    step: str
    status: Literal["pending", "processing", "completed", "error"]
    message: str
    duration_ms: Optional[int] = None
    details: Optional[str] = None


class ProcessingResult(BaseModel):
    """Final processing result returned to Frontend"""
    success: bool
    invoice: Optional[ProcessedInvoice] = None
    validation_errors: List[ValidationError] = Field(default_factory=list)
    processing_method: Literal["flash", "pro"] = "flash"
    processing_time_ms: int = 0
    error: Optional[str] = None
    processing_log: List[ProcessingLogEntry] = Field(default_factory=list)


class OCRResult(BaseModel):
    """OCR extraction result"""
    text: str
    confidence: float
    page_count: int
    raw_blocks: List[dict] = Field(default_factory=list)
