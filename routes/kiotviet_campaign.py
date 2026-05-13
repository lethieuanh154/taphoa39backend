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
                campaign_data = result.get("Data", result)
                campaign_id = campaign_data.get("Id") or result.get("Id")

                # POST response returns SalePromotions:[] — GET to fetch actual SalePromotion IDs
                sale_promotion_id = None
                sale_promotion_id_map = {}
                if campaign_id:
                    get_resp = requests.get(
                        f"{KIOTVIET_PROMOTION_API}/{campaign_id}",
                        headers=headers,
                        timeout=30,
                    )
                    if get_resp.status_code in (200, 201):
                        get_data = get_resp.json().get("Data", get_resp.json())
                        sale_promotions = get_data.get("SalePromotions", [])
                        sale_promotion_id = sale_promotions[0].get("Id") if sale_promotions else None
                        sale_promotion_id_map = {
                            str(sp.get("ReceivedProductId")): sp.get("Id")
                            for sp in sale_promotions
                            if sp.get("ReceivedProductId") and sp.get("Id")
                        }

                campaign_code = campaign_data.get("Code")

                return jsonify({
                    "success": True,
                    "kiotVietCampaignId": campaign_id,
                    "kiotVietCampaignCode": campaign_code,
                    "kiotVietSalePromotionId": sale_promotion_id,
                    "kiotVietSalePromotionIds": sale_promotion_id_map,
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

    @bp.route("/campaigns/<int:campaign_id>", methods=["GET"])
    def get_campaign(campaign_id: int):
        """
        Lấy thông tin campaign từ KiotViet.
        GET /api/kiotviet/campaigns/{campaign_id}
        Dùng để backfill kiotVietSalePromotionId cho promotions cũ.
        """
        try:
            headers = {
                "Authorization": _auth,
                "branchid": str(LatestBranchId),
                "retailer": retailer,
                "Content-Type": "application/json",
            }

            resp = requests.get(
                f"{KIOTVIET_PROMOTION_API}/{campaign_id}",
                headers=headers,
                timeout=30,
            )

            if resp.status_code in (200, 201):
                result = resp.json()
                campaign_data = result.get("Data", result)

                # Extract SalePromotionId(s)
                sale_promotions = campaign_data.get("SalePromotions", [])
                sale_promotion_id = sale_promotions[0].get("Id") if sale_promotions else None
                sale_promotion_id_map = {
                    str(sp.get("ReceivedProductId")): sp.get("Id")
                    for sp in sale_promotions
                    if sp.get("ReceivedProductId") and sp.get("Id")
                }

                # Extract PromotionType and Code
                promotion_type = campaign_data.get("PromotionType")
                campaign_code = campaign_data.get("Code")

                return jsonify({
                    "success": True,
                    "kiotVietCampaignId": campaign_id,
                    "kiotVietCampaignCode": campaign_code,
                    "kiotVietSalePromotionId": sale_promotion_id,
                    "kiotVietSalePromotionIds": sale_promotion_id_map,
                    "kiotVietPromotionType": promotion_type,
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

    # Existing KiotViet IDs — nếu có → update, không có → create mới
    campaign_id = int(promo.get("kiotVietCampaignId") or 0)
    sale_promo_id_scalar = int(promo.get("kiotVietSalePromotionId") or 0)
    sale_promo_id_map = promo.get("kiotVietSalePromotionIds") or {}

    # Handle multi-gift entries (new) or fallback to scalar (old data)
    gift_entries = promo.get("giftItems", [])
    if not gift_entries and promo.get("giftProductId"):
        gift_entries = [{
            "productId": str(promo.get("giftProductId", "")),
            "code": promo.get("giftProductCode", ""),
            "quantity": promo.get("giftQuantity", 1),
        }]

    prereq_id = int(promo.get("targetProductId", 0))
    prereq_code = promo.get("targetProductCode", "")
    prereq_qty = promo.get("minQuantity", 1)
    prereq_ids_str = str(promo.get("targetProductId", ""))

    def _base_sale_promo(received_id, received_qty, received_code, sp_id=0):
        return {
            "Id": sp_id,
            "CampaignId": campaign_id,
            "Type": 1,
            "PromotionType": promotion_type,
            "InvoiceValue": 0,
            "PrereqProductId": prereq_id,
            "PrereqCategoryId": None,
            "PrereqCategoryIds": None,
            "PrereqQuantity": prereq_qty,
            "PrereqApplySameKind": False,
            "ReceivedProductId": received_id,
            "ReceivedCategoryId": None,
            "ReceivedQuantity": received_qty,
            "ReceivedApplySameKind": False,
            "ReceivedVoucherCampaignIds": None,
            "RetailerId": RETAILER_ID,
            "GiftIsBuyProduct": False,
            "PrereqProductCode": prereq_code,
            "PrereqProductIds": prereq_ids_str,
            "ReceivedProductCode": received_code,
            "ReceivedProductCodes": received_code,
            "ReceivedProductIds": str(received_id) if received_id else "",
            "ProductDiscount": None,
            "ProductDiscountRatio": None,
            "ProductDiscountType": "%",
            "Discount": None,
            "DiscountRatio": None,
            "DiscountType": "%",
        }

    if promotion_type == 6:
        # Type 6 (gift): single SalePromotion, ReceivedEntity carries all gift products
        all_pids = [int(e.get("productId", 0)) for e in gift_entries if e.get("productId")]
        all_codes = [e.get("code", "") for e in gift_entries]
        all_names = [e.get("name", "") for e in gift_entries]
        all_qtys = [e.get("quantity", 1) for e in gift_entries]

        last_pid = all_pids[-1] if all_pids else None
        last_code = all_codes[-1] if all_codes else ""
        last_name = all_names[-1] if all_names else ""
        first_qty = all_qtys[0] if all_qtys else 1

        received_ids_str = ",".join(str(p) for p in all_pids)
        received_codes_str = ",".join(all_codes)

        sp_id = int(sale_promo_id_map.get(str(last_pid)) or sale_promo_id_scalar or 0)
        sp = _base_sale_promo(last_pid, first_qty, last_code, sp_id=sp_id)
        sp["ReceivedProductIds"] = received_ids_str
        sp["ReceivedProductCodes"] = received_codes_str
        sp["ReceivedEntity"] = {
            "Id": last_pid,
            "Name": last_name,
            "Code": last_code,
            "Type": 3,
            "ProductIds": received_ids_str,
            "ProductCodes": received_codes_str,
            "MasterProductIds": all_pids,
            "CurrentProductSelected": last_pid,
            "ApplySameKind": False,
            "GiftIsBuyProduct": False,
            "HasVariants": len(all_pids) > 1,
            "HasRelated": len(all_pids) > 1,
        }
        sale_promotions = [sp]
    else:
        # Type 5 (buy A get B): single SalePromotion with discount
        last_gift = gift_entries[-1] if gift_entries else {}
        received_id = int(last_gift.get("productId", 0)) if last_gift.get("productId") else None
        sp_id = int(sale_promo_id_map.get(str(received_id)) or sale_promo_id_scalar or 0)
        sp = _base_sale_promo(received_id, last_gift.get("quantity", 1), last_gift.get("code", ""), sp_id=sp_id)
        if has_percent and promo.get("discountPercent"):
            sp["ProductDiscount"] = None
            sp["ProductDiscountRatio"] = promo["discountPercent"]
            sp["ProductDiscountType"] = "%"
        elif has_fixed and promo.get("discountAmount"):
            sp["ProductDiscount"] = promo["discountAmount"]
            sp["ProductDiscountRatio"] = None
            sp["ProductDiscountType"] = "VND"
        sale_promotions = [sp]

    return {
        "Campaign": {
            "Id": campaign_id,
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
            "SalePromotions": sale_promotions,
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
