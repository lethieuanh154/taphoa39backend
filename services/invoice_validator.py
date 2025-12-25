"""
Invoice Validator Module
Validates extracted invoice data - reads values from PDF, no recalculation
"""
import logging
from typing import List, Tuple

from .config import config
from models.invoice import ProcessedInvoice, ValidationError

logger = logging.getLogger(__name__)


class InvoiceValidator:
    """
    Validates invoice data extracted from PDF
    Only checks for missing/invalid data, does NOT recalculate values
    """

    def __init__(self, tolerance: float = None):
        """
        Initialize validator

        Args:
            tolerance: Allowed difference for amount comparisons (default from config)
        """
        self.tolerance = tolerance if tolerance is not None else config.AMOUNT_TOLERANCE

    def validate(self, invoice: ProcessedInvoice) -> Tuple[bool, List[ValidationError]]:
        """
        Validate invoice data - check for missing/invalid fields only

        Args:
            invoice: ProcessedInvoice to validate

        Returns:
            Tuple of (is_valid, list of ValidationError)
        """
        errors: List[ValidationError] = []

        # Validate required metadata
        metadata_errors = self._validate_metadata(invoice)
        errors.extend(metadata_errors)

        # Validate seller info
        seller_errors = self._validate_seller(invoice)
        errors.extend(seller_errors)

        # Validate items exist
        items_errors = self._validate_items(invoice)
        errors.extend(items_errors)

        # Validate summary has values
        summary_errors = self._validate_summary(invoice)
        errors.extend(summary_errors)

        # Log validation result
        is_valid = len([e for e in errors if e.severity == "error"]) == 0
        logger.info(
            f"Validation complete: {'PASS' if is_valid else 'FAIL'} "
            f"({len(errors)} issues found)"
        )

        return is_valid, errors

    def _validate_metadata(self, invoice: ProcessedInvoice) -> List[ValidationError]:
        """Validate required metadata fields"""
        errors = []

        if not invoice.invoice_metadata.invoice_no:
            errors.append(ValidationError(
                field="invoice_metadata.invoice_no",
                message="Số hóa đơn không được để trống",
                severity="error"
            ))

        if not invoice.invoice_metadata.invoice_date:
            errors.append(ValidationError(
                field="invoice_metadata.invoice_date",
                message="Ngày hóa đơn không được để trống",
                severity="error"
            ))

        return errors

    def _validate_seller(self, invoice: ProcessedInvoice) -> List[ValidationError]:
        """Validate seller information"""
        errors = []

        if not invoice.seller.company_name:
            errors.append(ValidationError(
                field="seller.company_name",
                message="Tên công ty bán không được để trống",
                severity="error"
            ))

        if not invoice.seller.tax_code:
            errors.append(ValidationError(
                field="seller.tax_code",
                message="Mã số thuế bên bán không được để trống",
                severity="error"
            ))

        return errors

    def _validate_items(self, invoice: ProcessedInvoice) -> List[ValidationError]:
        """Validate items list"""
        errors = []

        if not invoice.items or len(invoice.items) == 0:
            errors.append(ValidationError(
                field="items",
                message="Hóa đơn phải có ít nhất một mặt hàng",
                severity="error"
            ))
            return errors

        # Check each item has required fields
        for idx, item in enumerate(invoice.items):
            if not item.description:
                errors.append(ValidationError(
                    field=f"items[{idx}].description",
                    message=f"Dòng {idx + 1}: Tên hàng hóa không được để trống",
                    severity="warning"
                ))

            if item.quantity <= 0:
                errors.append(ValidationError(
                    field=f"items[{idx}].quantity",
                    message=f"Dòng {idx + 1}: Số lượng phải lớn hơn 0",
                    severity="warning"
                ))

        return errors

    def _validate_summary(self, invoice: ProcessedInvoice) -> List[ValidationError]:
        """Validate summary - check values exist, do NOT recalculate"""
        errors = []

        # Check total_amount_before_vat exists
        if invoice.summary.total_amount_before_vat <= 0:
            errors.append(ValidationError(
                field="summary.total_amount_before_vat",
                message="Tổng tiền hàng chưa được trích xuất",
                severity="warning"
            ))

        # Check total_payment exists
        if invoice.summary.total_payment <= 0:
            errors.append(ValidationError(
                field="summary.total_payment",
                message="Tổng tiền thanh toán chưa được trích xuất",
                severity="warning"
            ))

        # Check VAT rate format
        vat_rate_str = invoice.summary.vat_rate
        if not vat_rate_str or vat_rate_str == "":
            errors.append(ValidationError(
                field="summary.vat_rate",
                message="Thuế suất chưa được trích xuất",
                severity="warning"
            ))

        return errors

    def _is_close(self, expected: float, actual: float, tolerance: float = None) -> bool:
        """
        Check if two values are close within tolerance

        Args:
            expected: Expected value
            actual: Actual value
            tolerance: Max allowed difference (default: self.tolerance)

        Returns:
            True if values are close enough
        """
        tol = tolerance if tolerance is not None else self.tolerance
        return abs(expected - actual) <= tol

    def get_error_messages(self, errors: List[ValidationError]) -> List[str]:
        """
        Get list of error messages for AI correction prompt

        Args:
            errors: List of ValidationError

        Returns:
            List of error message strings
        """
        return [e.message for e in errors if e.severity == "error"]


# Global instance
invoice_validator = InvoiceValidator()
