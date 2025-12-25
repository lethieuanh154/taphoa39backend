"""
Invoice Validator Module
Validates mathematical correctness of extracted invoice data
"""
import logging
from typing import List, Tuple

from .config import config
from models.invoice import ProcessedInvoice, ValidationError

logger = logging.getLogger(__name__)


class InvoiceValidator:
    """
    Validates invoice data for mathematical correctness
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
        Validate all aspects of an invoice

        Args:
            invoice: ProcessedInvoice to validate

        Returns:
            Tuple of (is_valid, list of ValidationError)
        """
        errors: List[ValidationError] = []

        # Validate each item
        item_errors = self._validate_items(invoice)
        errors.extend(item_errors)

        # Validate totals
        total_errors = self._validate_totals(invoice)
        errors.extend(total_errors)

        # Validate VAT
        vat_errors = self._validate_vat(invoice)
        errors.extend(vat_errors)

        # Validate final payment
        payment_errors = self._validate_payment(invoice)
        errors.extend(payment_errors)

        # Log validation result
        is_valid = len([e for e in errors if e.severity == "error"]) == 0
        logger.info(
            f"Validation complete: {'PASS' if is_valid else 'FAIL'} "
            f"({len(errors)} issues found)"
        )

        return is_valid, errors

    def _validate_items(self, invoice: ProcessedInvoice) -> List[ValidationError]:
        """Validate each line item: amount = quantity × unit_price"""
        errors = []

        for idx, item in enumerate(invoice.items):
            expected_amount = item.quantity * item.unit_price
            actual_amount = item.amount

            if not self._is_close(expected_amount, actual_amount):
                errors.append(ValidationError(
                    field=f"items[{idx}].amount",
                    message=f"Item {item.stt}: Thành tiền không đúng. "
                            f"Cần: {expected_amount:,.0f}, Thực tế: {actual_amount:,.0f}",
                    severity="error",
                    expected_value=expected_amount,
                    actual_value=actual_amount
                ))
                logger.warning(
                    f"Item {idx} amount mismatch: "
                    f"{item.quantity} × {item.unit_price} = {expected_amount}, "
                    f"got {actual_amount}"
                )

        return errors

    def _validate_totals(self, invoice: ProcessedInvoice) -> List[ValidationError]:
        """Validate: total_amount_before_vat = sum of all item amounts"""
        errors = []

        sum_amounts = sum(item.amount for item in invoice.items)
        declared_total = invoice.summary.total_amount_before_vat

        if not self._is_close(sum_amounts, declared_total):
            errors.append(ValidationError(
                field="summary.total_amount_before_vat",
                message=f"Tổng tiền hàng không khớp. "
                        f"Tổng các dòng: {sum_amounts:,.0f}, "
                        f"Khai báo: {declared_total:,.0f}",
                severity="error",
                expected_value=sum_amounts,
                actual_value=declared_total
            ))
            logger.warning(
                f"Total before VAT mismatch: sum={sum_amounts}, declared={declared_total}"
            )

        return errors

    def _validate_vat(self, invoice: ProcessedInvoice) -> List[ValidationError]:
        """Validate VAT calculation"""
        errors = []

        # Parse VAT rate
        vat_rate_str = invoice.summary.vat_rate
        try:
            vat_rate = float(vat_rate_str.replace("%", "").strip())
        except ValueError:
            errors.append(ValidationError(
                field="summary.vat_rate",
                message=f"Thuế suất không hợp lệ: {vat_rate_str}",
                severity="error"
            ))
            return errors

        # Validate VAT rate is in allowed list
        if vat_rate not in config.VAT_RATES:
            errors.append(ValidationError(
                field="summary.vat_rate",
                message=f"Thuế suất {vat_rate}% không phổ biến. "
                        f"Các mức thông dụng: {config.VAT_RATES}",
                severity="warning"
            ))

        # Calculate expected VAT
        base_amount = invoice.summary.total_amount_before_vat
        expected_vat = base_amount * vat_rate / 100
        actual_vat = invoice.summary.vat_amount

        # Allow for rounding (VAT can be rounded)
        if not self._is_close(expected_vat, actual_vat, tolerance=10):
            errors.append(ValidationError(
                field="summary.vat_amount",
                message=f"Tiền thuế VAT không đúng. "
                        f"Cần: {expected_vat:,.0f}, Thực tế: {actual_vat:,.0f}",
                severity="error",
                expected_value=expected_vat,
                actual_value=actual_vat
            ))
            logger.warning(
                f"VAT mismatch: {base_amount} × {vat_rate}% = {expected_vat}, "
                f"got {actual_vat}"
            )

        return errors

    def _validate_payment(self, invoice: ProcessedInvoice) -> List[ValidationError]:
        """Validate: total_payment = total_before_vat + vat_amount"""
        errors = []

        expected_payment = (
            invoice.summary.total_amount_before_vat +
            invoice.summary.vat_amount
        )
        actual_payment = invoice.summary.total_payment

        if not self._is_close(expected_payment, actual_payment):
            errors.append(ValidationError(
                field="summary.total_payment",
                message=f"Tổng thanh toán không đúng. "
                        f"Cần: {expected_payment:,.0f}, Thực tế: {actual_payment:,.0f}",
                severity="error",
                expected_value=expected_payment,
                actual_value=actual_payment
            ))
            logger.warning(
                f"Total payment mismatch: "
                f"{invoice.summary.total_amount_before_vat} + "
                f"{invoice.summary.vat_amount} = {expected_payment}, "
                f"got {actual_payment}"
            )

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
