from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from firebase.init_firebase import init_firestore
from firebase.firebase_service.cache import Cache

COLLECTION_NAME = "promotions"
CACHE_TTL = 1800       # 30 min for all promotions
CACHE_TTL_ACTIVE = 300  # 5 min for active promotions
# Response da dung san cua /api/public/promotions/active (gom ca targetProduct/giftProducts)
PUBLIC_ACTIVE_PROMOS_KEY = "public_active_promotions"
PUBLIC_ACTIVE_PROMOS_TTL = 300

# Init Firestore from FIREBASE_SERVICE_ACCOUNT_DATHANG project
db = init_firestore("FIREBASE_SERVICE_ACCOUNT_DATHANG", app_name="dathang_app")


class FirestorePromotionService:
    def __init__(self, cache: Cache):
        self.cache = cache
        self.promotions_ref = db.collection(COLLECTION_NAME)

    # ──────────────────────────────────────────────
    # READ
    # ──────────────────────────────────────────────

    def read_all_promotions(self, include_disabled: bool = False) -> List[Dict]:
        """Read all promotions, optionally including disabled ones."""
        cache_key = f"all_promotions:{include_disabled}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        query = self.promotions_ref
        if not include_disabled:
            query = query.where("isEnabled", "==", True)

        docs = query.stream()
        result = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            result.append(data)

        self.cache.set(cache_key, result, ttl=CACHE_TTL)
        return result

    def read_active_promotions(self) -> List[Dict]:
        """Read only currently active promotions (enabled + within date range)."""
        cache_key = "active_promotions"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        now = datetime.now(timezone.utc).isoformat()
        all_enabled = self.read_all_promotions(include_disabled=False)

        active = []
        for promo in all_enabled:
            from_date = promo.get("fromDate", "")
            to_date = promo.get("toDate", "")
            if from_date and from_date > now:
                continue  # Not started yet
            if to_date and to_date < now:
                continue  # Expired
            active.append(promo)

        self.cache.set(cache_key, active, ttl=CACHE_TTL_ACTIVE)
        return active

    def read_promotions_for_product(self, product_id: str) -> List[Dict]:
        """Get active promotions for a specific product."""
        active = self.read_active_promotions()
        return [p for p in active if str(p.get("targetProductId")) == str(product_id)]

    def read_promotion(self, promo_id: str) -> Optional[Dict]:
        """Read a single promotion by ID."""
        doc = self.promotions_ref.document(promo_id).get()
        if doc.exists:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    # ──────────────────────────────────────────────
    # WRITE
    # ──────────────────────────────────────────────

    def create_promotion(self, data: Dict) -> Dict:
        """Create a new promotion."""
        now = datetime.now(timezone.utc).isoformat()
        data["createdDate"] = now
        data["modifiedDate"] = now
        data.setdefault("isEnabled", True)
        data.setdefault("minQuantity", 1)

        # Set default priority: gift promotions get higher priority
        if data.get("hasGift") or data.get("type") == "gift":
            data.setdefault("priority", 1)
        else:
            data.setdefault("priority", 2)

        doc_ref = self.promotions_ref.document()
        data["id"] = doc_ref.id
        doc_ref.set(data)

        self._invalidate_cache()
        return {"status": "success", "id": doc_ref.id, "promotion": data}

    def update_promotion(self, promo_id: str, updates: Dict) -> Dict:
        """Update an existing promotion."""
        updates["modifiedDate"] = datetime.now(timezone.utc).isoformat()
        # Don't allow changing the id field
        updates.pop("id", None)
        self.promotions_ref.document(promo_id).update(updates)
        self._invalidate_cache()
        return {"status": "success", "id": promo_id}

    def delete_promotion(self, promo_id: str) -> Dict:
        """Delete a promotion."""
        self.promotions_ref.document(promo_id).delete()
        self._invalidate_cache()
        return {"status": "success", "id": promo_id}

    def toggle_promotion(self, promo_id: str, enabled: bool) -> Dict:
        """Enable or disable a promotion."""
        return self.update_promotion(promo_id, {"isEnabled": enabled})

    # ──────────────────────────────────────────────
    # APPLY PROMOTIONS (Core logic)
    # ──────────────────────────────────────────────

    def apply_promotions(self, cart_items: List[Dict]) -> Dict:
        """
        Apply active promotions to cart items.

        Input cart_items: [
            {"productId": "123", "code": "SP001", "quantity": 2, "basePrice": 50000},
            ...
        ]

        Returns: {
            "appliedPromotions": [...],
            "giftItems": [...],
            "totalDiscount": number
        }
        """
        active_promos = self.read_active_promotions()
        if not active_promos:
            return {"appliedPromotions": [], "giftItems": [], "totalDiscount": 0}

        # Group promotions by target product, sorted by priority
        promos_by_product: Dict[str, List[Dict]] = {}
        for promo in active_promos:
            pid = str(promo.get("targetProductId", ""))
            if pid not in promos_by_product:
                promos_by_product[pid] = []
            promos_by_product[pid].append(promo)

        for pid in promos_by_product:
            promos_by_product[pid].sort(key=lambda p: p.get("priority", 99))

        applied: List[Dict] = []
        gift_items: List[Dict] = []
        total_discount = 0
        discounted_products: set = set()  # Track products already discounted

        for item in cart_items:
            item_pid = str(item.get("productId", ""))
            item_qty = item.get("quantity", 0)
            item_price = item.get("basePrice", 0)

            matching_promos = promos_by_product.get(item_pid, [])

            for promo in matching_promos:
                min_qty = promo.get("minQuantity", 1)
                if item_qty < min_qty:
                    continue

                # Determine active types from boolean flags or legacy type
                has_gift = promo.get("hasGift", False) or promo.get("type") == "gift"
                has_pct = promo.get("hasPercentDiscount", False) or promo.get("type") == "percentage"
                has_fixed = promo.get("hasFixedDiscount", False) or promo.get("type") == "fixed_amount"

                # Gift
                if has_gift:
                    raw_gift_entries = promo.get("giftItems", [])
                    if not raw_gift_entries and promo.get("giftProductId"):
                        raw_gift_entries = [{
                            "productId": str(promo.get("giftProductId", "")),
                            "code": promo.get("giftProductCode", ""),
                            "name": promo.get("giftProductName", ""),
                            "basePrice": promo.get("giftProductBasePrice", 0),
                            "quantity": promo.get("giftQuantity", 1),
                        }]
                    if raw_gift_entries:
                        trigger_count = item_qty // min_qty
                        for entry in raw_gift_entries:
                            total_gift_qty = entry.get("quantity", 1) * trigger_count
                            gift_items.append({
                                "productId": str(entry.get("productId", "")),
                                "code": entry.get("code", ""),
                                "name": entry.get("name", ""),
                                "quantity": total_gift_qty,
                                "basePrice": entry.get("basePrice", 0),
                                "isGift": True,
                                "promotionId": promo.get("id")
                            })
                        applied.append({
                            "promotionId": promo.get("id"),
                            "promotionName": promo.get("name", ""),
                            "type": "gift",
                            "targetProductId": item_pid,
                            "giftItems": raw_gift_entries,
                            "discountAmount": 0
                        })

                # Discount handling — phân biệt Type 2 vs Type 3
                has_discount = has_pct or has_fixed
                has_gift_product = bool(promo.get("giftProductId"))

                if has_discount and has_gift_product:
                    # Type 3: Mua A được mua B giảm giá → tạo discounted item cho SP B
                    trigger_count = item_qty // min_qty
                    disc_qty = promo.get("giftQuantity", 1) * trigger_count
                    gift_base_price = promo.get("giftProductBasePrice", 0)

                    disc_per_unit = 0
                    if has_pct and promo.get("discountPercent"):
                        raw = gift_base_price * promo["discountPercent"] / 100
                        disc_per_unit = (int(raw) // 1000) * 1000  # Floor to nearest 1,000
                    elif has_fixed and promo.get("discountAmount"):
                        disc_per_unit = promo["discountAmount"]

                    disc_total = disc_per_unit * disc_qty
                    total_discount += disc_total

                    gift_items.append({
                        "productId": str(promo.get("giftProductId", "")),
                        "code": promo.get("giftProductCode", ""),
                        "name": promo.get("giftProductName", ""),
                        "quantity": disc_qty,
                        "basePrice": gift_base_price,
                        "isGift": False,
                        "isDiscounted": True,
                        "discountPercent": promo.get("discountPercent"),
                        "discountAmount": promo.get("discountAmount"),
                        "promotionId": promo.get("id"),
                        "promotionName": promo.get("name", ""),
                    })
                    applied.append({
                        "promotionId": promo.get("id"),
                        "promotionName": promo.get("name", ""),
                        "type": "percentage" if has_pct else "fixed_amount",
                        "targetProductId": item_pid,
                        "discountAmount": disc_total,
                        "discountPercent": promo.get("discountPercent"),
                    })

                elif has_discount and not has_gift_product:
                    # Type 2: Giảm giá trực tiếp cho chính SP trigger
                    if item_pid not in discounted_products:
                        if has_pct and promo.get("discountPercent"):
                            pct = promo.get("discountPercent", 0)
                            raw_per_unit = item_price * pct / 100
                            disc_per_unit_rounded = (int(raw_per_unit) // 1000) * 1000
                            disc = disc_per_unit_rounded * item_qty
                        elif has_fixed and promo.get("discountAmount"):
                            disc = promo.get("discountAmount", 0) * (item_qty // min_qty)
                        else:
                            disc = 0

                        total_discount += disc
                        discounted_products.add(item_pid)
                        applied.append({
                            "promotionId": promo.get("id"),
                            "promotionName": promo.get("name", ""),
                            "type": "percentage" if has_pct else "fixed_amount",
                            "targetProductId": item_pid,
                            "discountAmount": disc,
                            "discountPercent": promo.get("discountPercent"),
                        })

        # Deduplicate gift items (same product from different promotions)
        deduped_gifts: Dict[str, Dict] = {}
        for g in gift_items:
            key = g["productId"]
            if key in deduped_gifts:
                deduped_gifts[key]["quantity"] += g["quantity"]
            else:
                deduped_gifts[key] = dict(g)

        return {
            "appliedPromotions": applied,
            "giftItems": list(deduped_gifts.values()),
            "totalDiscount": total_discount
        }

    # ──────────────────────────────────────────────
    # CACHE
    # ──────────────────────────────────────────────

    def _invalidate_cache(self):
        """Invalidate all promotion caches."""
        self.cache.invalidate_prefix("all_promotions:")
        self.cache.invalidate("active_promotions")
        self.cache.invalidate(PUBLIC_ACTIVE_PROMOS_KEY)
