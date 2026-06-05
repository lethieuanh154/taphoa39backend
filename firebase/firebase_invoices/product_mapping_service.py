"""
Product Mapping Service
Maps invoice item descriptions to system product codes.
Collection: productsFromInputInvoice
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict

from google.cloud.firestore_v1.base_query import FieldFilter
from firebase_admin import firestore

from firebase.init_firebase import init_firestore

logger = logging.getLogger(__name__)

FIREBASE_ENV_KEY = "FIREBASE_SERVICE_ACCOUNT_SUPPLIES_INVOICES"
COLLECTION_NAME = "productsFromInputInvoice"


class ProductMappingService:

    def __init__(self):
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = init_firestore(FIREBASE_ENV_KEY)
            logger.info("ProductMappingService Firestore initialized")
        return self._db

    def get_mappings_by_supplier(self, supplier_tax_code: str) -> List[Dict]:
        """
        Get all mappings for a supplier.
        Returns list of mapping dicts.
        """
        try:
            docs = (
                self.db.collection(COLLECTION_NAME)
                .where(filter=FieldFilter("supplierTaxCode", "==", supplier_tax_code))
                .stream()
            )
            results = []
            for doc in docs:
                data = doc.to_dict()
                data["firestoreId"] = doc.id
                # Convert timestamps to ISO strings
                for field in ("lastSeen", "createdAt"):
                    if field in data and hasattr(data[field], "isoformat"):
                        data[field] = data[field].isoformat()
                results.append(data)
            return results
        except Exception as e:
            logger.error(f"get_mappings_by_supplier error: {e}")
            return []

    def save_mapping(self, mapping_data: Dict) -> bool:
        """
        Upsert a mapping by its `id` field (`supplierTaxCode|normalizedDescription`).
        Updates lastSeen and invoiceDescription if exists.
        """
        try:
            mapping_id = mapping_data.get("id")
            if not mapping_id:
                logger.error("save_mapping: missing id field")
                return False

            doc_ref = self.db.collection(COLLECTION_NAME).document(mapping_id)
            doc = doc_ref.get()

            now = datetime.utcnow()

            if doc.exists:
                doc_ref.update({
                    "invoiceDescription": mapping_data.get("invoiceDescription", ""),
                    "productCode": mapping_data.get("productCode", ""),
                    "productName": mapping_data.get("productName", ""),
                    "unit": mapping_data.get("unit", ""),
                    "lastSeen": now,
                })
            else:
                doc_ref.set({
                    "id": mapping_id,
                    "supplierTaxCode": mapping_data.get("supplierTaxCode", ""),
                    "invoiceDescription": mapping_data.get("invoiceDescription", ""),
                    "normalizedDescription": mapping_data.get("normalizedDescription", ""),
                    "productCode": mapping_data.get("productCode", ""),
                    "productName": mapping_data.get("productName", ""),
                    "unit": mapping_data.get("unit", ""),
                    "lastSeen": now,
                    "createdAt": now,
                    "previousDescriptions": [],
                })

            return True
        except Exception as e:
            logger.error(f"save_mapping error: {e}")
            return False

    def save_mappings_batch(self, mappings: List[Dict]) -> int:
        """
        Save multiple mappings. Returns count of successfully saved.
        Uses batched writes for efficiency.
        """
        if not mappings:
            return 0

        saved = 0
        batch = self.db.batch()
        batch_count = 0

        now = datetime.utcnow()

        for mapping_data in mappings:
            mapping_id = mapping_data.get("id")
            if not mapping_id:
                continue

            doc_ref = self.db.collection(COLLECTION_NAME).document(mapping_id)

            # Check existence to decide set vs update
            doc = doc_ref.get()
            if doc.exists:
                batch.update(doc_ref, {
                    "invoiceDescription": mapping_data.get("invoiceDescription", ""),
                    "productCode": mapping_data.get("productCode", ""),
                    "productName": mapping_data.get("productName", ""),
                    "unit": mapping_data.get("unit", ""),
                    "lastSeen": now,
                })
            else:
                batch.set(doc_ref, {
                    "id": mapping_id,
                    "supplierTaxCode": mapping_data.get("supplierTaxCode", ""),
                    "invoiceDescription": mapping_data.get("invoiceDescription", ""),
                    "normalizedDescription": mapping_data.get("normalizedDescription", ""),
                    "productCode": mapping_data.get("productCode", ""),
                    "productName": mapping_data.get("productName", ""),
                    "unit": mapping_data.get("unit", ""),
                    "lastSeen": now,
                    "createdAt": now,
                    "previousDescriptions": [],
                })

            batch_count += 1
            saved += 1

            # Firestore batch limit: 500 operations
            if batch_count >= 490:
                batch.commit()
                batch = self.db.batch()
                batch_count = 0

        if batch_count > 0:
            batch.commit()

        logger.info(f"save_mappings_batch: saved {saved}/{len(mappings)}")
        return saved

    def rename_mapping(self, mapping_id: str, new_description: str, normalized_new: str) -> bool:
        """
        Update mapping's invoiceDescription (rename detected).
        Pushes old description into previousDescriptions and updates normalizedDescription.
        """
        try:
            doc_ref = self.db.collection(COLLECTION_NAME).document(mapping_id)
            doc = doc_ref.get()

            if not doc.exists:
                logger.warning(f"rename_mapping: doc {mapping_id} not found")
                return False

            data = doc.to_dict()
            old_desc = data.get("invoiceDescription", "")
            prev_descs = data.get("previousDescriptions", [])

            if old_desc and old_desc not in prev_descs:
                prev_descs.append(old_desc)

            doc_ref.update({
                "invoiceDescription": new_description,
                "normalizedDescription": normalized_new,
                "id": normalized_new and f"{data.get('supplierTaxCode', '')}|{normalized_new}" or mapping_id,
                "previousDescriptions": prev_descs,
                "lastSeen": datetime.utcnow(),
            })

            return True
        except Exception as e:
            logger.error(f"rename_mapping error: {e}")
            return False


    def update_unit(self, mapping_id: str, new_unit: str) -> bool:
        """
        Update mapping's unit field.
        """
        try:
            doc_ref = self.db.collection(COLLECTION_NAME).document(mapping_id)
            doc = doc_ref.get()

            if not doc.exists:
                logger.warning(f"update_unit: doc {mapping_id} not found")
                return False

            doc_ref.update({
                "unit": new_unit,
                "lastSeen": datetime.utcnow(),
            })

            return True
        except Exception as e:
            logger.error(f"update_unit error: {e}")
            return False


product_mapping_service = ProductMappingService()
