from __future__ import annotations

import math
import re
import time

from flask import Blueprint, jsonify, request
from unidecode import unidecode

from routes.shared import handle_api_errors, notify_order_created
from routes.firebase_orders import _deduct_redeemed_points
from firebase.firebase_service.order_notification_service import notify_order_realtime
from firebase.firebase_service.promotion_service import (
    PUBLIC_ACTIVE_PROMOS_KEY,
    PUBLIC_ACTIVE_PROMOS_TTL,
    is_flash_banner,
)

# Danh muc an (vd: thuoc la) - khong hien thi cho khach hang
_HIDDEN_CATEGORY_IDS = {1440125, 1787413}

# Cau hinh tinh ship/diem server-side (khop FE ShippingService/RewardService)
_STORE_LAT = 16.019693
_STORE_LNG = 108.197694
_ROAD_FACTOR = 1.3
_SHIP_PRODUCT_ID = 43370064
_SHIP_PRODUCT_CODE = "SP170288"
_MIN_DELIVERY_SUBTOTAL = 200000
_SUSPICIOUS_UNDERPAY = 1000  # client tra thieu hon server qua muc nay -> gan co
_BULK_DISCOUNT_MIN_CASES = 10    # phai NHIEU HON muc nay moi duoc chiet khau si
_BULK_DISCOUNT_PER_CASE = 2000   # d/thung, chi khi khach tu den lay hang
_HEAVY_PATTERN = re.compile(
    r"\b(bia|nước suối|nước khoáng|sữa|nước ngọt|nước tăng lực|nước giải khát)\b",
    re.IGNORECASE,
)


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _public_product(p: dict, clone_map: dict | None = None) -> dict:
    """Chi giu field khach hang duoc phep thay.
    Cat Cost/OnHandNV/sync/kiotViet noi bo.

    OnHand = ton KiotViet, CloneOnHandNV = tong OnHandNV cac clone cua SP nay (user chot
    27/09/2026: original het/khong du thi ban tiep bang ton clone). FE DatHang cong 2 so.
    SP clone / hang noi bo van KHONG bao gio duoc public (xem _is_orderable).
    Description KHONG public: field nay dang chua ghi chu noi bo cua nhan vien
    (gia si, gia nhap, "k vat"...). Chi mo lai khi du lieu da duoc lam sach.
    Anh: uu tien `ImageVariant` (anh rieng tung bien the, do
    scripts/fix_variant_images_from_kiotviet.py ghi) roi moi den `Image` - `Image` tu sync
    KiotViet la anh cap MASTER nen moi bien the trong nhom deu trung nhau."""
    return {
        "Id": p.get("Id"),
        "Code": p.get("Code"),
        "Name": p.get("Name"),
        "FullName": p.get("FullName"),
        "Image": p.get("ImageVariant") or p.get("Image"),
        "BasePrice": p.get("BasePrice"),
        "Unit": p.get("Unit"),
        "CategoryId": p.get("CategoryId"),
        "CategoryName": p.get("CategoryName") or "",
        "ConversionValue": p.get("ConversionValue"),
        "MasterUnitId": p.get("MasterUnitId"),
        "NormalizedName": p.get("NormalizedName") or "",
        "OnHand": _to_float(p.get("OnHand")),
        "CloneOnHandNV": _to_float((clone_map or {}).get(str(p.get("Id")))),
    }


def _deduct_reserved(item: dict, reserved_map: dict | None) -> dict:
    """Tru phan don online dang giu: tru OnHand truoc, phan du tru tiep CloneOnHandNV."""
    if not reserved_map:
        return item
    held = _to_float(reserved_map.get(str(item.get("Id"))))
    if held <= 0:
        return item
    on_hand = _to_float(item.get("OnHand"))
    item["OnHand"] = max(0.0, on_hand - held)
    overflow = max(0.0, held - on_hand)
    if overflow > 0:
        item["CloneOnHandNV"] = max(0.0, _to_float(item.get("CloneOnHandNV")) - overflow)
    return item


def _is_km_product(p: dict) -> bool:
    name = (p.get("FullName") or p.get("Name") or "").lower()
    return "(km)" in name and _to_float(p.get("Cost")) == 0


def _is_clone(p: dict) -> bool:
    if p.get("isClone") is True or p.get("isClone") == "true":
        return True
    if p.get("KiotVietSync") is False:
        return True
    return _to_float(p.get("OnHandNV")) > 0 and _to_float(p.get("OnHand")) == 0


def _category_path(name: str) -> str:
    """Slug danh muc dang KiotViet ("GIA VI - DO KHO" -> "GIA_VI_DO_KHO")."""
    slug = unidecode(name).upper()
    slug = re.sub(r"[^A-Z0-9]+", "_", slug).strip("_")
    return slug


def _is_orderable(p: dict) -> bool:
    """SP hop le de ban: active, chua xoa, khong clone, khong danh muc an, khong KM."""
    if not p or not p.get("Id"):
        return False
    if p.get("isDeleted") or p.get("isActive") is False:
        return False
    if _is_clone(p):
        return False
    if p.get("CategoryId") in _HIDDEN_CATEGORY_IDS:
        return False
    if _is_km_product(p):
        return False
    return True


def _valid_latlng(lat, lng) -> bool:
    """Toa do hop le trong pham vi Viet Nam (loai rac nhu 0,0)."""
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return False
    return 8.0 <= lat <= 24.0 and 102.0 <= lng <= 110.0


def _serialize_public_products(products: list, reserved_map: dict | None = None,
                               clone_map: dict | None = None) -> list:
    """Loc bo clone / KM / danh muc an / deleted-inactive roi whitelist field.
    `reserved_map` = so luong dang bi don online giu -> tru khoi OnHand hien thi,
    de khach khong dat trung phan hang khach khac da giu."""
    return [_deduct_reserved(_public_product(p, clone_map), reserved_map)
            for p in products if _is_orderable(p)]


def _paginate_public_products(products: list, reserved_map: dict | None = None,
                              clone_map: dict | None = None):
    """Loc -> cat trang -> CHI SAU DO moi serialize. Tra `(page, total, offset)`.

    Truoc day serialize ca ~15k SP roi moi cat lay 20 (`_serialize_public_products` o tren):
    14ms CPU moi request, ke ca khi khach chi cuon them mot trang. `_is_orderable()` khong
    dung dict nen loc rat re; chi trang thuc su tra ve moi can `_public_product()` -> 4ms.
    Ket qua tra ve giong het cach cu.

    `limit <= 0` (client khong truyen) van tra toan bo, giu nguyen hanh vi cu.
    """
    orderable = [p for p in products if _is_orderable(p)]
    total = len(orderable)
    limit, offset = _paginate()
    selected = orderable[offset:offset + limit] if limit > 0 else orderable
    page = [_deduct_reserved(_public_product(p, clone_map), reserved_map) for p in selected]
    return page, total, offset


def _public_order(o: dict) -> dict:
    """Chi tra field khach can xem lich su/trang thai don.
    CAT PII (SDT/dia chi/lat/lng), totalCost (gia von), discountAmount noi bo."""
    return {
        "id": o.get("id"),
        "status": o.get("status"),
        "createdDate": o.get("createdDate"),
        "customerPaid": o.get("customerPaid"),
        "wantDelivery": o.get("wantDelivery"),
        "desiredDeliveryDate": o.get("desiredDeliveryDate"),
        "desiredDeliveryTime": o.get("desiredDeliveryTime"),
        "cartItems": [
            {
                "product": {
                    "Name": (it.get("product") or {}).get("Name"),
                    "Image": (it.get("product") or {}).get("Image"),
                },
                "quantity": it.get("quantity"),
                "unitPrice": it.get("unitPrice"),
                "unitPriceSaleOff": it.get("unitPriceSaleOff"),
            }
            for it in (o.get("cartItems") or [])
        ],
    }


def _public_gift_entries(pr: dict) -> list:
    """Chuan hoa gift entries (multi-gift giftItems, fallback scalar field cu)."""
    items = pr.get("giftItems")
    if isinstance(items, list) and items:
        return [
            {
                "productId": str(g.get("productId")) if g.get("productId") is not None else None,
                "code": g.get("code"),
                "name": g.get("name"),
                "basePrice": g.get("basePrice"),
                "quantity": g.get("quantity") or 1,
            }
            for g in items
            if isinstance(g, dict) and g.get("productId")
        ]
    if pr.get("giftProductId"):
        return [{
            "productId": str(pr.get("giftProductId")),
            "code": pr.get("giftProductCode"),
            "name": pr.get("giftProductName"),
            "basePrice": pr.get("giftProductBasePrice"),
            "quantity": pr.get("giftQuantity") or 1,
        }]
    return []


def _public_promotion(pr: dict, target_product: dict | None,
                      gift_products: list | None = None) -> dict:
    """Whitelist promotion cho hien thi; cat toan bo kiotViet*/internal."""
    return {
        "id": pr.get("id"),
        "type": pr.get("type"),
        "name": pr.get("name"),
        "hasGift": pr.get("hasGift"),
        "hasPercentDiscount": pr.get("hasPercentDiscount"),
        "hasFixedDiscount": pr.get("hasFixedDiscount"),
        "discountPercent": pr.get("discountPercent"),
        "discountAmount": pr.get("discountAmount"),
        "minQuantity": pr.get("minQuantity"),
        "giftQuantity": pr.get("giftQuantity"),
        "giftProductId": pr.get("giftProductId"),
        "giftProductName": pr.get("giftProductName"),
        "giftProductCode": pr.get("giftProductCode"),
        "giftProductBasePrice": pr.get("giftProductBasePrice"),
        "giftItems": _public_gift_entries(pr),
        "giftProducts": gift_products or [],
        "fromDate": pr.get("fromDate"),
        "toDate": pr.get("toDate"),
        "priority": pr.get("priority"),
        "isFlashBanner": is_flash_banner(pr),
        "targetProductId": pr.get("targetProductId"),
        "targetProductName": pr.get("targetProductName"),
        "targetProduct": target_product,
    }


def _haversine(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2)
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _recompute_distance_km(lat, lng, fallback_km) -> float:
    """Tinh lai khoang cach tu lat/lng (khong tin distanceKm client). Khop FE calculateDistance()."""
    if lat is None or lng is None:
        return _to_float(fallback_km)
    road = _haversine(_STORE_LAT, _STORE_LNG, _to_float(lat), _to_float(lng)) * _ROAD_FACTOR
    return math.ceil(road * 10) / 10


def _heavy_case_count(real_items) -> float:
    """Tong so thung hang nang trong don. Port countHeavyCases() cua FE."""
    total_cases = 0.0
    for r in real_items:
        p = r["product"]
        unit = (p.get("Unit") or "").lower()
        name = p.get("FullName") or p.get("Name") or ""
        if unit == "thùng" and _HEAVY_PATTERN.search(name):
            total_cases += r["quantity"]
    return total_cases


def _pickup_bulk_discount(real_items) -> float:
    """Chiet khau si khi khach TU DEN LAY hang: tren 10 thung hang nang -> 2.000d/thung.
    KHONG ap dung cho don giao hang (gia si la gia tai cua hang).
    Port calculatePickupBulkDiscount() cua FE."""
    cases = _heavy_case_count(real_items)
    if cases <= _BULK_DISCOUNT_MIN_CASES:
        return 0.0
    return cases * _BULK_DISCOUNT_PER_CASE


def _calc_ship_cost(subtotal, distance_km) -> float:
    """Port calculateShipCost() cua FE ShippingService. Khong con phu phi hang nang."""
    if subtotal < _MIN_DELIVERY_SUBTOTAL:
        return 0.0
    if subtotal < 500000:
        free_km, rate, min_km = 0, 13000, 1.0   # tinh toi thieu 1km
    elif subtotal < 1000000:
        free_km, rate, min_km = 1, 6000, 0.0
    elif subtotal < 2000000:
        free_km, rate, min_km = 2, 5000, 0.0
    elif subtotal < 5000000:
        free_km, rate, min_km = 3, 5000, 0.0
    elif subtotal < 10000000:
        free_km, rate, min_km = 5, 5000, 0.0
    else:
        free_km, rate, min_km = 8, 4000, 0.0
    chargeable = max(min_km, distance_km - free_km)
    raw = chargeable * rate
    return math.floor(raw / 1000 + 0.5) * 1000  # khop Math.round cua JS


def _customer_available_points(customer_service, customer) -> float:
    """Diem kha dung THUC TE tu Firestore (khong tin giftPoint client).
    Khop cong thuc _calc_gift_point() trong verify-identity."""
    if not customer_service or not isinstance(customer, dict):
        return 0.0
    phone = (customer.get("ContactNumber") or "").strip()
    if not phone:
        return 0.0
    try:
        for doc in customer_service.customers_ref.where("ContactNumber", "==", phone).limit(1).stream():
            c = doc.to_dict() or {}
            base = round(_to_float(c.get("TotalPoint")) * 0.02 / 100) * 100
            bonus = _to_float(c.get("RegistrationBonus")) + _to_float(c.get("BonusPoint"))
            redeemed = _to_float(c.get("RedeemedPoints"))
            return max(0.0, base + bonus - redeemed)
    except Exception as e:
        print(f"[public add_order] points lookup error: {type(e).__name__}: {e}")
    return 0.0


def _order_line(prod, qty, unit_price, is_gift, is_promo, sale_off=0.0):
    """Dung 1 dong cartItems tu product SERVER, da whitelist (_public_product -> khong luu Cost/noi bo)."""
    return {
        "product": _public_product(prod),
        "quantity": qty,
        "unitPriceSaleOff": sale_off,
        "unitPrice": unit_price,
        "totalPrice": 0 if is_gift else unit_price * qty,
        "isGift": is_gift,
        "isPromotionItem": is_promo,
    }


def _recompute_order_economics(order, product_service, promotion_service, customer_service,
                               reserved_map=None) -> dict:
    """Dung lai TOAN BO don tu server: BO QUA gia/gift/promo/ship do client gui.
    Chi tin {productId, quantity} cua dong mua that; gift/Type3/ship deu tao lai tu server.
    Tra ve {ok, error?, customerPaid, suspicious}."""
    client_paid = _to_float(order.get("customerPaid"))
    client_items = order.get("cartItems") or []

    # 1. Danh sach MUA THAT: bo dong gift/promo/ship client, validate so luong
    purchased = []
    for it in client_items:
        prod = it.get("product") or {}
        pid = prod.get("Id") or it.get("productId")
        if pid == _SHIP_PRODUCT_ID or prod.get("Code") == _SHIP_PRODUCT_CODE:
            continue
        if it.get("isGift") or it.get("isPromotionItem"):
            continue  # KHONG tin -> gift/promo se dung lai tu server
        qty = _to_float(it.get("quantity"))
        if qty <= 0 or qty > 100000:
            return {"ok": False, "error": (
                f"Số lượng đặt không hợp lệ ({qty:g}). Số lượng phải lớn hơn 0 và không quá 100.000. "
                "Vui lòng mở lại giỏ hàng và nhập lại số lượng.")}
        if not pid:
            continue
        # Ton kho phai doc FRESH: read_product() co cache 3600s -> validate bang so cu
        # ca tieng, khach van dat duoc hang da het o quay. Chi vai SP trong gio nen re.
        server = product_service.read_product_fresh(str(pid))
        if not _is_orderable(server):
            name = (server or {}).get("Name") or (server or {}).get("FullName") or pid
            return {"ok": False, "error": (
                f"Sản phẩm \"{name}\" đã ngừng bán hoặc không còn nhận đặt online "
                "(cửa hàng vừa gỡ sản phẩm này). "
                "Vui lòng xoá sản phẩm đó khỏi giỏ hàng rồi bấm Đặt hàng lại.")}

        # Ton kha dung = ton KiotViet + ton clone - phan don online khac dang giu
        # (khop _public_product / _deduct_reserved). Ton clone doc FRESH nhu OnHand.
        # FE co the doc IndexedDB cu nen phai chan o server, khong tin so luong client thay.
        name = server.get("FullName") or server.get("Name") or pid
        available = _to_float(server.get("OnHand"))
        try:
            available += product_service.read_clone_stock_fresh(pid)
        except Exception as e:
            print(f"[public] clone stock error pid={pid}: {type(e).__name__}: {e}")
        if reserved_map:
            available -= _to_float(reserved_map.get(str(pid)))
        if qty > available:
            unit = (server.get("Unit") or "").strip()
            unit_txt = f" {unit}" if unit else ""
            if available <= 0:
                return {"ok": False, "error": (
                    f"Sản phẩm \"{name}\" đã hết hàng tại thời điểm bạn bấm đặt "
                    "(có thể vừa có khách khác đặt trước). "
                    "Vui lòng xoá sản phẩm đó khỏi giỏ hàng hoặc chọn sản phẩm khác rồi đặt lại.")}
            return {"ok": False, "error": (
                f"Sản phẩm \"{name}\" chỉ còn {available:g}{unit_txt}, không đủ {qty:g}{unit_txt} như bạn đặt "
                "(tồn kho đã thay đổi hoặc đang giữ cho đơn khác). "
                f"Vui lòng giảm số lượng xuống tối đa {available:g}{unit_txt} rồi đặt lại.")}

        purchased.append((server, str(pid), qty))

    if not purchased:
        return {"ok": False, "error": (
            "Giỏ hàng trống, hoặc tất cả sản phẩm trong giỏ đều đã ngừng bán nên không tạo được đơn. "
            "Vui lòng quay lại trang chủ chọn sản phẩm rồi đặt lại.")}

    # 2. Promotion engine (gia SERVER)
    promo_cart = [{"productId": pid, "code": s.get("Code"), "quantity": qty,
                   "basePrice": _to_float(s.get("BasePrice"))} for (s, pid, qty) in purchased]
    promo = promotion_service.apply_promotions(promo_cart)
    applied = promo.get("appliedPromotions") or []
    gift_entries = promo.get("giftItems") or []
    total_discount = _to_float(promo.get("totalDiscount"))

    # Tach Type2 (giam truc tiep tren trigger) khoi Type3 (co giftProduct)
    type3_ids = {g.get("promotionId") for g in gift_entries if g.get("isDiscounted")}
    type2_by_pid = {}
    for a in applied:
        if a.get("type") in ("percentage", "fixed_amount") and a.get("promotionId") not in type3_ids:
            tp = str(a.get("targetProductId") or "")
            type2_by_pid[tp] = type2_by_pid.get(tp, 0.0) + _to_float(a.get("discountAmount"))

    # 3. Dung lai cartItems tu server (gia dong da giam Type2/Type3, khop FE)
    new_items = []
    subtotal = 0.0
    total_cost = 0.0
    for (s, pid, qty) in purchased:
        base = _to_float(s.get("BasePrice"))
        sale_off = (type2_by_pid.get(pid, 0.0) / qty) if qty else 0.0
        unit_price = max(0.0, base - sale_off)
        subtotal += unit_price * qty
        total_cost += _to_float(s.get("Cost")) * qty
        new_items.append(_order_line(s, qty, unit_price, False, False, sale_off))

    for g in gift_entries:
        gid = str(g.get("productId") or "")
        gqty = _to_float(g.get("quantity"))
        gs = product_service.read_product(gid) or {
            "Id": g.get("productId"), "Code": g.get("code"), "Name": g.get("name"),
            "FullName": g.get("name"), "BasePrice": g.get("basePrice"),
        }
        if g.get("isDiscounted"):
            gbase = _to_float(g.get("basePrice"))
            if g.get("discountPercent"):
                disc = (int(gbase * _to_float(g["discountPercent"]) / 100) // 1000) * 1000
            else:
                disc = _to_float(g.get("discountAmount"))
            unit_price = max(0.0, gbase - disc)
            subtotal += unit_price * gqty
            total_cost += _to_float(gs.get("Cost")) * gqty
            new_items.append(_order_line(gs, gqty, unit_price, False, True, disc))
        else:
            total_cost += _to_float(gs.get("Cost")) * gqty
            new_items.append(_order_line(gs, gqty, 0.0, True, True))

    # 4. Ship / chiet khau si: dung lai tu server (khong tin shipCost/distanceKm client)
    real_lines = [{"product": s, "quantity": qty} for (s, _pid, qty) in purchased]
    ship_cost = 0.0
    bulk_discount = 0.0
    if order.get("wantDelivery"):
        lat, lng = order.get("lat"), order.get("lng")
        if not _valid_latlng(lat, lng):
            return {"ok": False, "error": (
                "Chưa xác định được vị trí địa chỉ giao hàng trên bản đồ nên không tính được phí ship. "
                "Vui lòng nhập lại địa chỉ (có dấu phẩy giữa số nhà, đường, phường, quận) "
                "và đợi hệ thống tính xong khoảng cách, hoặc chọn hình thức tự đến lấy hàng.")}
        if subtotal < _MIN_DELIVERY_SUBTOTAL:
            return {"ok": False, "error": (
                f"Đơn hàng {subtotal:,.0f}đ chưa đủ mức tối thiểu "
                f"{_MIN_DELIVERY_SUBTOTAL:,.0f}đ (chưa tính phí ship) để được giao hàng. "
                "Vui lòng mua thêm, hoặc bỏ chọn giao hàng và tự đến lấy tại cửa hàng.")}
        distance = _recompute_distance_km(lat, lng, None)  # KHONG fallback distanceKm client
        order["distanceKm"] = distance
        ship_cost = _calc_ship_cost(subtotal, distance)
        if ship_cost > 0:
            new_items.append(_order_line(
                {"Id": _SHIP_PRODUCT_ID, "Code": _SHIP_PRODUCT_CODE, "Name": "Phi Giao hang",
                 "FullName": "Phi Giao hang", "BasePrice": ship_cost, "Unit": "Dich vu"},
                1, ship_cost, False, False))
    else:
        # Tu den lay hang -> chiet khau si hang thung. KHONG cong gop voi don giao hang.
        bulk_discount = min(_pickup_bulk_discount(real_lines), subtotal)

    subtotal_payable = subtotal - bulk_discount

    # 5. Diem thuong: cap theo so du THAT (logic RewardService.calculateFinal)
    available = _customer_available_points(customer_service, order.get("customer"))
    req_ship = max(0.0, _to_float(order.get("pointsUsedForShip")))
    req_order = max(0.0, _to_float(order.get("pointsUsedForOrder")))
    pts_ship = min(available, ship_cost, req_ship) if req_ship > 0 else 0.0
    remaining = max(0.0, available - pts_ship)
    pts_order = min(remaining, subtotal_payable, req_order) if req_order > 0 else 0.0

    customer_paid = max(0.0, (subtotal_payable - pts_order) + (ship_cost - pts_ship))

    # 6. Ghi de order bang du lieu server (chan ly)
    order["cartItems"] = new_items
    order["shipCost"] = ship_cost
    order["pickupBulkDiscount"] = bulk_discount
    order["heavyCaseCount"] = _heavy_case_count(real_lines)
    order["pointsUsedForShip"] = pts_ship
    order["pointsUsedForOrder"] = pts_order
    order["discountAmount"] = total_discount + pts_order + bulk_discount
    order["totalCost"] = total_cost
    order["totalQuantity"] = sum(q for (_s, _p, q) in purchased)
    order["customerPaid"] = customer_paid
    order["totalPrice"] = customer_paid

    # 7. Flag khi client tra thieu hon server (ngoai sai so lam tron)
    suspicious = (customer_paid - client_paid) > _SUSPICIOUS_UNDERPAY
    if suspicious:
        order["suspiciousOrder"] = True
        order["priceAudit"] = {"clientPaid": client_paid, "serverPaid": customer_paid,
                               "underpay": customer_paid - client_paid}
        print(f"[public add_order] SUSPICIOUS underpay={customer_paid - client_paid:.0f} "
              f"client={client_paid:.0f} server={customer_paid:.0f} "
              f"phone={(order.get('customer') or {}).get('ContactNumber')}")

    return {"ok": True, "customerPaid": customer_paid, "suspicious": suspicious}


def _paginate():
    try:
        limit = int(request.args.get("limit", 0))
    except ValueError:
        limit = 0
    try:
        offset = int(request.args.get("offset", 0))
    except ValueError:
        offset = 0
    return limit, offset


def create_firebase_public_bp(
    product_service, promotion_service, order_service, customer_service, socketio,
    reservation_service=None
) -> Blueprint:
    """API public cho app DatHang - chi tra field an toan, khach khong thay du lieu noi bo."""
    bp = Blueprint("firebase_public", __name__, url_prefix="/api/public")

    def _reserved_map() -> dict:
        """So luong dang bi don online giu, theo productId. Loi -> coi nhu khong giu
        (tha hien thi du ton con hon chan ca trang san pham)."""
        if not reservation_service:
            return {}
        try:
            return reservation_service.get_reserved_map()
        except Exception as e:
            print(f"[public] reserved map error: {type(e).__name__}: {e}")
            return {}

    def _clone_map() -> dict:
        """Ton clone theo original Id. Loi -> coi nhu khong co clone (chi hien ton KiotViet)."""
        try:
            return product_service.get_public_clone_stock_map()
        except Exception as e:
            print(f"[public] clone stock map error: {type(e).__name__}: {e}")
            return {}

    def _reserve_stock_for_order(order: dict) -> None:
        """Giu hang cho don vua tao. Loi giu hang KHONG duoc lam hong don da luu:
        don van hop le, chi la khong giu duoc cho -> log de xu ly tay."""
        oid = str(order.get("id") or "?")

        if not reservation_service:
            print(f"[reserve] don {oid}: BO QUA - reservation_service = None "
                  f"(app.py chua truyen service vao create_firebase_public_bp?)")
            return

        cart = order.get("cartItems") or []
        items = []
        skipped = 0
        for it in cart:
            prod = it.get("product") or {}
            pid = prod.get("Id")
            if not pid or pid == _SHIP_PRODUCT_ID or prod.get("Code") == _SHIP_PRODUCT_CODE:
                skipped += 1
                continue
            items.append({
                "productId": str(pid),
                "code": prod.get("Code") or "",
                "name": prod.get("FullName") or prod.get("Name") or "",
                "quantity": _to_float(it.get("quantity")),
            })

        print(f"[reserve] don {oid}: {len(cart)} dong gio hang -> {len(items)} dong giu hang "
              f"({skipped} dong bo qua: ship/thieu Id)")

        if not items:
            print(f"[reserve] don {oid}: KHONG giu hang - khong co dong nao hop le")
            return

        try:
            result = reservation_service.create_for_order(
                oid, order.get("customer"), items
            )
            if result.get("success"):
                resv = result.get("reservation") or {}
                print(f"[reserve] don {oid}: DA GIU {len(items)} mat hang, "
                      f"het han {resv.get('expiresAt')}")
            else:
                print(f"[reserve] don {oid}: GIU HANG THAT BAI - {result.get('error')}")
        except Exception as e:
            print(f"[reserve] don {oid}: LOI NGOAI Y - {type(e).__name__}: {e}")

    @bp.route("/products/featured", methods=["GET"])
    @handle_api_errors
    def public_featured():
        products = product_service.get_featured_products()
        page, total, offset = _paginate_public_products(products, _reserved_map(), _clone_map())
        return jsonify({
            "products": page,
            "count": len(page),
            "total": total,
            "hasMore": (offset + len(page)) < total,
        })

    @bp.route("/categories", methods=["GET"])
    @handle_api_errors
    def public_categories():
        """Danh muc cho DatHang.

        KHONG goi KiotViet va KHONG stream collection products o day: ca hai deu tung lam
        request treo -> nginx 504 (KiotViet la HTTP ra ngoai; `read_all_products()` da 503
        "Query timed out" tren prod). Ten danh muc lay tu snapshot Firestore; phan loc
        "con hang" chi ap dung khi cache products SAN CO, khong bao gio keo them full scan.
        """
        categories = []
        for cat in product_service.read_categories():
            try:
                cid = int(cat.get("Id"))
            except (TypeError, ValueError):
                continue
            name = (cat.get("Name") or "").strip()
            if not name or cid in _HIDDEN_CATEGORY_IDS:
                continue
            categories.append({
                "Id": cid,
                "Name": name,
                "Path": cat.get("Path") or _category_path(name),
            })

        # Loc danh muc khong con hang - CHI khi cache products dang am, tranh full scan
        cached_products = product_service.get_cached_all_products()
        if cached_products:
            active_ids = set()
            for prod in cached_products:
                if not _is_orderable(prod):
                    continue
                try:
                    active_ids.add(int(prod.get("CategoryId")))
                except (TypeError, ValueError):
                    continue
            filtered = [c for c in categories if c["Id"] in active_ids]
            if filtered:
                categories = filtered

        categories.sort(key=lambda c: c["Name"])
        return jsonify(categories)

    @bp.route("/products/by-category/<int:category_id>", methods=["GET"])
    @handle_api_errors
    def public_by_category(category_id: int):
        products = product_service.read_products_by_category(category_id)
        page, total, offset = _paginate_public_products(products, _reserved_map(), _clone_map())
        return jsonify({
            "products": page,
            "count": len(page),
            "total": total,
            "categoryId": category_id,
            "hasMore": (offset + len(page)) < total,
        })

    @bp.route("/products/search", methods=["GET"])
    @handle_api_errors
    def public_search():
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"products": [], "count": 0, "query": ""})
        try:
            limit = int(request.args.get("limit", 80))
        except ValueError:
            limit = 80
        limit = min(max(limit, 1), 200)
        products = product_service.search_products(query, limit=limit)
        cleaned = _serialize_public_products(products, _reserved_map(), _clone_map())
        return jsonify({"products": cleaned, "count": len(cleaned), "query": query})

    @bp.route("/promotions/active", methods=["GET"])
    @handle_api_errors
    def public_active_promotions():
        # Cache ca response da dung san: dung N+1 read_product() (157 round-trip Firestore
        # -> >60s -> nginx 504) moi lan cache active_promotions het han.
        cached = promotion_service.cache.get(PUBLIC_ACTIVE_PROMOS_KEY)
        if cached is not None:
            return jsonify(cached)

        promos = promotion_service.read_active_promotions()

        # Gom toan bo productId (target + gift) roi doc 1 lan bang Firestore get_all
        needed = []
        gift_entries_by_promo = []
        for pr in promos:
            entries = _public_gift_entries(pr)
            gift_entries_by_promo.append(entries)
            if pr.get("targetProductId"):
                needed.append(str(pr.get("targetProductId")))
            for entry in entries:
                if entry.get("productId"):
                    needed.append(str(entry["productId"]))

        raw_products = product_service.read_products_bulk(needed)
        reserved = _reserved_map()
        clone_map = _clone_map()
        product_cache = {}
        for k, v in raw_products.items():
            product_cache[k] = _deduct_reserved(_public_product(v, clone_map), reserved)

        result = []
        for pr, entries in zip(promos, gift_entries_by_promo):
            pid = pr.get("targetProductId")
            target_product = product_cache.get(str(pid)) if pid else None

            gift_products = []
            for entry in entries:
                gp = product_cache.get(str(entry["productId"]))
                if gp:
                    gift_products.append({**gp, "GiftQuantity": entry.get("quantity") or 1})

            result.append(_public_promotion(pr, target_product, gift_products))

        promotion_service.cache.set(PUBLIC_ACTIVE_PROMOS_KEY, result, ttl=PUBLIC_ACTIVE_PROMOS_TTL)
        return jsonify(result)

    @bp.route("/orders/<order_id>", methods=["GET"])
    @handle_api_errors
    def public_get_order(order_id: str):
        """Tra chi tiet 1 don da lam gon (cho trang lich su/confirm DatHang) - khong PII/gia von."""
        o = order_service.read_order(str(order_id))
        if not o:
            return jsonify({"error": "Order not found"}), 404
        o = dict(o)
        o.setdefault("id", order_id)
        return jsonify(_public_order(o))

    @bp.route("/add_order", methods=["POST"])
    def public_add_order():
        """Nhan don tu DatHang. Tinh lai TOAN BO tien server-side (gia/ship/diem/gia von) + flag."""
        order = request.get_json(force=True) or {}

        # Validate SDT khach hang
        phone = ((order.get("customer") or {}).get("ContactNumber") or "").strip()
        if len(phone) < 9 or not phone.lstrip("+").isdigit():
            return jsonify({"error": (
                "Số điện thoại không hợp lệ nên cửa hàng không thể liên hệ giao hàng. "
                "Vui lòng nhập số từ 9 chữ số trở lên, chỉ gồm chữ số (không khoảng trắng, không dấu chấm).")
            }), 400

        # Tinh lai toan bo tu server; reject neu don khong hop le.
        # Ton kha dung da tru phan don online khac dang giu -> chan oversell.
        econ = _recompute_order_economics(
            order, product_service, promotion_service, customer_service,
            reserved_map=_reserved_map()
        )
        if not econ.get("ok"):
            return jsonify({"error": econ.get("error", (
                "Đơn hàng không hợp lệ nên chưa được ghi nhận. "
                "Vui lòng kiểm tra lại giỏ hàng và thông tin nhận hàng rồi đặt lại."))}), 400

        # Luu ATOMIC: create() fail neu id da ton tai -> chan overwrite (khong race nhu read+set)
        oid = str(order.get("id") or ("DH" + str(int(time.time() * 1000))))
        order["id"] = oid
        try:
            order_service.orders_ref.document(oid).create(order)
            order_service.cache.invalidate("all_orders")
        except Exception as e:
            if type(e).__name__ in ("AlreadyExists", "Conflict") or "already exist" in str(e).lower():
                return jsonify({"error": (
                    f"Đơn hàng {oid} đã được gửi trước đó rồi, hệ thống không tạo đơn trùng. "
                    "Vui lòng kiểm tra mục \"Đơn hàng của tôi\" — nếu đã thấy đơn thì không cần đặt lại.")
                }), 409
            print(f"[public add_order] SAVE FAILED oid={oid} {type(e).__name__}: {e}")
            return jsonify({"error": (
                "Hệ thống cửa hàng đang bận nên chưa lưu được đơn của bạn (lỗi máy chủ). "
                "Đơn CHƯA được ghi nhận. Vui lòng thử lại sau ít phút, "
                "hoặc gọi trực tiếp cho cửa hàng để đặt hàng.")}), 503
        result = {"message": "order added"}
        # Giu hang TRUOC khi tru diem: neu tru diem loi thi don da luu van duoc giu cho,
        # con thieu ban giu hang thi ton kho sai cho moi khach khac.
        _reserve_stock_for_order(order)
        _deduct_redeemed_points(order, customer_service)

        order_id = None
        if isinstance(result, dict):
            order_id = result.get("id") or result.get("Id")
        if not order_id and isinstance(order, dict):
            order_id = order.get("id") or order.get("Id")

        if order_id:
            try:
                persisted = order_service.read_order(str(order_id))
                if persisted:
                    notify_order_created(socketio, persisted)
                    notify_order_realtime("created", persisted)
                else:
                    notify_order_created(socketio, order_id)
                    notify_order_realtime("created", order)
            except Exception:
                notify_order_created(socketio, order_id or order)
                notify_order_realtime("created", order)

        # Tra ve so da tinh lai server-side (de FE/monitor verify + minh bach)
        summary = {
            "id": order.get("id"),
            "customerPaid": order.get("customerPaid"),
            "totalCost": order.get("totalCost"),
            "shipCost": order.get("shipCost"),
            "discountAmount": order.get("discountAmount"),
            "suspiciousOrder": order.get("suspiciousOrder", False),
        }
        if isinstance(result, dict):
            summary.update(result)
        return jsonify(summary)

    return bp
