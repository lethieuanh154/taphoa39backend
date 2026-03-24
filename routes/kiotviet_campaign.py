"""
KiotViet Campaign Sync Routes
Tạo/cập nhật campaign khuyến mại trên KiotViet
"""
from __future__ import annotations

import requests
from flask import Blueprint, jsonify, request
from FromKiotViet.get_authorization import auth_token as _auth
from Utility.get_env import LatestBranchId, retailer


KIOTVIET_PROMOTION_API = "https://api-promotion1.kiotviet.vn/api/campaigns"
RETAILER_ID = 500111210


def create_kiotviet_campaign_bp() -> Blueprint:
    bp = Blueprint("kiotviet_campaign", __name__, url_prefix="/api/kiotviet")

    @bp.route("/campaigns", methods=["POST"])
    def create_campaign():
        """
        Tạo campaign khuyến mại trên KiotViet.

        Body: promotion data từ frontend (Firestore format)
        Chuyển đổi sang KiotViet Campaign format rồi gửi.
        """
        data = request.get_json(silent=True) or {}
        promo = data.get("promotion", {})

        if not promo:
            return jsonify({"error": "Missing promotion data"}), 400

        try:
            campaign_payload = _build_campaign_payload(promo)

            headers = {
                "Authorization": _auth,
                "branchid": str(LatestBranchId),
                "retailer": retailer,
                "Content-Type": "application/json",
            }

            resp = requests.post(
                KIOTVIET_PROMOTION_API,
                json=campaign_payload,
                headers=headers,
                timeout=30,
            )

            if resp.status_code in (200, 201):
                result = resp.json()
                campaign_id = result.get("Id") or result.get("Data", {}).get("Id")
                return jsonify({
                    "success": True,
                    "kiotVietCampaignId": campaign_id,
                    "kiotVietResponse": result,
                }), 200
            else:
                return jsonify({
                    "success": False,
                    "error": f"KiotViet returned {resp.status_code}",
                    "detail": resp.text[:500],
                }), resp.status_code

        except requests.RequestException as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/campaigns/<int:campaign_id>", methods=["DELETE"])
    def delete_campaign(campaign_id: int):
        """
        Xóa campaign khuyến mại trên KiotViet.
        DELETE /api/kiotviet/campaigns/{campaign_id}
        """
        try:
            headers = {
                "Authorization": _auth,
                "branchid": str(LatestBranchId),
                "retailer": retailer,
                "Content-Type": "application/json",
            }

            resp = requests.delete(
                f"{KIOTVIET_PROMOTION_API}/{campaign_id}",
                headers=headers,
                timeout=30,
            )

            if resp.status_code in (200, 201):
                return jsonify({"success": True, "message": "Campaign deleted"}), 200
            else:
                return jsonify({
                    "success": False,
                    "error": f"KiotViet returned {resp.status_code}",
                    "detail": resp.text[:500],
                }), resp.status_code

        except requests.RequestException as e:
            return jsonify({"success": False, "error": str(e)}), 500

    return bp


def _build_campaign_payload(promo: dict) -> dict:
    """
    Chuyển đổi Promotion (Firestore format) sang KiotViet Campaign format.

    Mapping:
    - hasGift=true → PromotionType: 6 (mua hàng tặng hàng)
    - hasPercentDiscount/hasFixedDiscount=true → PromotionType: 5 (mua hàng giảm giá hàng)
    """
    has_gift = promo.get("hasGift", False)
    has_percent = promo.get("hasPercentDiscount", False)
    has_fixed = promo.get("hasFixedDiscount", False)

    # Xác định PromotionType
    if has_gift:
        promotion_type = 6  # Mua hàng tặng hàng
    elif has_percent or has_fixed:
        promotion_type = 5  # Mua hàng giảm giá hàng
    else:
        promotion_type = 6  # Default: tặng hàng

    # Build SalePromotion entry
    sale_promo = {
        "Type": 1,
        "PromotionType": promotion_type,
        "InvoiceValue": 0,
        "PrereqProductId": int(promo.get("targetProductId", 0)),
        "PrereqCategoryId": None,
        "PrereqCategoryIds": None,
        "PrereqQuantity": promo.get("minQuantity", 1),
        "PrereqApplySameKind": False,
        "ReceivedProductId": int(promo.get("giftProductId", 0)) if promo.get("giftProductId") else None,
        "ReceivedCategoryId": None,
        "ReceivedQuantity": promo.get("giftQuantity", 1),
        "ReceivedApplySameKind": False,
        "ReceivedVoucherCampaignIds": None,
        "RetailerId": RETAILER_ID,
        "GiftIsBuyProduct": False,
        "PrereqProductCode": promo.get("targetProductCode", ""),
        "PrereqProductIds": str(promo.get("targetProductId", "")),
        "ReceivedProductCode": promo.get("giftProductCode", ""),
        "ReceivedProductIds": str(promo.get("giftProductId", "")) if promo.get("giftProductId") else "",
    }

    # Discount fields (chỉ cho PromotionType 5)
    if promotion_type == 5:
        if has_percent and promo.get("discountPercent"):
            sale_promo["ProductDiscount"] = None
            sale_promo["ProductDiscountRatio"] = promo["discountPercent"]
            sale_promo["ProductDiscountType"] = "%"
        elif has_fixed and promo.get("discountAmount"):
            sale_promo["ProductDiscount"] = promo["discountAmount"]
            sale_promo["ProductDiscountRatio"] = None
            sale_promo["ProductDiscountType"] = "VND"
        else:
            sale_promo["ProductDiscount"] = None
            sale_promo["ProductDiscountRatio"] = None
            sale_promo["ProductDiscountType"] = "%"
        sale_promo["Discount"] = None
        sale_promo["DiscountRatio"] = None
        sale_promo["DiscountType"] = "%"
    else:
        # Gift type: không có discount
        sale_promo["ProductDiscount"] = None
        sale_promo["ProductDiscountRatio"] = None
        sale_promo["ProductDiscountType"] = "%"
        sale_promo["Discount"] = None
        sale_promo["DiscountRatio"] = None
        sale_promo["DiscountType"] = "%"

    return {
        "Campaign": {
            "Id": 0,
            "Name": promo.get("name", "Khuyến mại"),
            "IsActive": promo.get("isEnabled", True),
            "ApplyMonths": "",
            "ApplyDates": "",
            "Weekday": "",
            "Hour": "",
            "IsGlobal": True,
            "ForAllUser": True,
            "ForAllCusGroup": True,
            "Type": 1,
            "PromotionType": promotion_type,
            "SalePromotions": [sale_promo],
            "IsFixedQuantity": False,
            "StartDate": promo.get("fromDate", ""),
            "EndDate": promo.get("toDate", ""),
            "BirthdayTimeType": 1,
            "LimitPromotionUsageType": 2,
            "RetailerId": RETAILER_ID,
            "InvoiceValueType": 1,
            "LimitPromotionUsageTemp": True,
            "LimitPromotionWarning": False,
            "HasTransactions": False,
            "Description": promo.get("description", ""),
            "CampaignBranches": [],
            "CampaignUsers": [],
            "CampainCustomerGroups": [],
            "LimitPromotionUsage": True,
        }
    }
