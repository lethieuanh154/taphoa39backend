# from firebase_admin import firestore
from datetime import datetime
from firebase.init_firebase import init_firestore
from google.cloud.firestore import FieldFilter
from datetime import datetime, time

COLLECTION_NAME = "invoices"

# Đặt tên app duy nhất cho mỗi service account
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_HOADON")
invoices_ref = db.collection(COLLECTION_NAME)

def get_all_invoices():
    """
    Get all invoices from Firestore
    """
    try:
        invoices = invoices_ref.stream()
        return [invoice.to_dict() for invoice in invoices]
    except Exception as e:
        raise Exception(f"Error getting all invoices: {str(e)}")

def get_invoice_by_id(invoice_id):
    """
    Get a specific invoice by ID
    """
    try:
        invoice_doc = invoices_ref.document(invoice_id).get()
        if invoice_doc.exists:
            return invoice_doc.to_dict()
        return None
    except Exception as e:
        raise Exception(f"Error getting invoice by ID: {str(e)}")

def get_invoices_by_date(start_date, end_date):
    """
    Get invoices within a date range, comparing only the date part (year, month, day)
    Expected date format: YYYY-MM-DD (e.g., "2025-06-17")
    """
    try:
        # Tạo chuỗi so sánh dạng ISO cho ngày bắt đầu và kết thúc
        start_str = f"{start_date}T00:00:00.000Z"
        end_str = f"{end_date}T23:59:59.999Z"

        # Query Firestore với string
        query = invoices_ref \
            .where('createdDate', '>=', start_str) \
            .where('createdDate', '<=', end_str)
        invoices = query.stream()
        return [invoice.to_dict() for invoice in invoices]
    except Exception as e:
        raise Exception(f"Error getting invoices by date: {str(e)}")

def get_invoices_by_status(status):
    """
    Get invoices by status
    """
    try:
        query = invoices_ref.where('status', '==', status)
        invoices = query.stream()
        return [invoice.to_dict() for invoice in invoices]
    except Exception as e:
        raise Exception(f"Error getting invoices by status: {str(e)}")

def get_invoices_by_customer(customer_id):
    """
    Get invoices by customer ID
    """
    try:
        query = invoices_ref.where('customerId', '==', customer_id)
        invoices = query.stream()
        return [invoice.to_dict() for invoice in invoices]
    except Exception as e:
        raise Exception(f"Error getting invoices by customer: {str(e)}")
