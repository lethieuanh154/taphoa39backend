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
        """Validate summary - check values exist and math consistency"""
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

        # === Math validation ===
        math_errors = self._validate_math(invoice)
        errors.extend(math_errors)

        return errors

    def _validate_math(self, invoice: ProcessedInvoice) -> List[ValidationError]:
        """Validate arithmetic consistency of invoice data"""
        errors = []

        if not invoice.items:
            return errors

        # Check each item: amount ≈ quantity × unit_price
        for idx, item in enumerate(invoice.items):
            if item.quantity > 0 and item.unit_price > 0 and item.amount > 0:
                expected_amount = item.quantity * item.unit_price
                if not self._is_close(expected_amount, item.amount):
                    errors.append(ValidationError(
                        field=f"items[{idx}].amount",
                        message=f"Dòng {idx + 1}: Thành tiền ({item.amount:,.0f}) ≠ SL ({item.quantity}) × Đơn giá ({item.unit_price:,.0f}) = {expected_amount:,.0f}",
                        severity="warning",
                        expected_value=expected_amount,
                        actual_value=item.amount
                    ))

        # Check: total_amount_before_vat ≈ sum(items.amount)
        items_total = sum(item.amount for item in invoice.items)
        if items_total > 0 and invoice.summary.total_amount_before_vat > 0:
            if not self._is_close(items_total, invoice.summary.total_amount_before_vat):
                errors.append(ValidationError(
                    field="summary.total_amount_before_vat",
                    message=f"Tổng tiền hàng ({invoice.summary.total_amount_before_vat:,.0f}) ≠ Tổng các dòng ({items_total:,.0f})",
                    severity="warning",
                    expected_value=items_total,
                    actual_value=invoice.summary.total_amount_before_vat
                ))

        # Check: total_payment ≈ total_amount_before_vat + vat_amount
        if invoice.summary.total_amount_before_vat > 0 and invoice.summary.total_payment > 0:
            expected_total = invoice.summary.total_amount_before_vat + invoice.summary.vat_amount
            if not self._is_close(expected_total, invoice.summary.total_payment):
                errors.append(ValidationError(
                    field="summary.total_payment",
                    message=f"Tổng thanh toán ({invoice.summary.total_payment:,.0f}) ≠ Tiền hàng ({invoice.summary.total_amount_before_vat:,.0f}) + VAT ({invoice.summary.vat_amount:,.0f}) = {expected_total:,.0f}",
                    severity="warning",
                    expected_value=expected_total,
                    actual_value=invoice.summary.total_payment
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
