from __future__ import annotations

import math
import re
import time

from flask import Blueprint, jsonify, request
from unidecode import unidecode

from routes.shared import handle_api_errors, notify_order_created
from routes.firebase_orders import _deduct_redeemed_points
from firebase.firebase_service.order_notification_service import notify_order_realtime

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
_HEAVY_PATTERN = re.compile(
    r"\b(bia|nước suối|nước khoáng|sữa|nước ngọt|nước tăng lực|nước giải khát)\b",
    re.IGNORECASE,
)


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _public_product(p: dict) -> dict:
    """Chi giu field khach hang duoc phep thay.
    Gop ton kho clone vao OnHand; cat Cost/OnHandNV/sync/kiotViet noi bo."""
    on_hand = _to_float(p.get("OnHand")) + _to_float(p.get("CloneOnHandNV"))
    return {
        "Id": p.get("Id"),
        "Code": p.get("Code"),
        "Name": p.get("Name"),
        "FullName": p.get("FullName"),
        "Image": p.get("Image"),
        "BasePrice": p.get("BasePrice"),
        "Unit": p.get("Unit"),
        "Description": p.get("Description") or "",
        "CategoryId": p.get("CategoryId"),
        "CategoryName": p.get("CategoryName") or "",
        "ConversionValue": p.get("ConversionValue"),
        "MasterUnitId": p.get("MasterUnitId"),
        "NormalizedName": p.get("NormalizedName") or "",
        "OnHand": on_hand,
    }


def _is_km_product(p: dict) -> bool:
    name = (p.get("FullName") or p.get("Name") or "").lower()
    return "(km)" in name and _to_float(p.get("Cost")) == 0


def _is_clone(p: dict) -> bool:
    if p.get("isClone") is True:
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


def _serialize_public_products(products: list) -> list:
    """Loc bo clone / KM / danh muc an / deleted-inactive roi whitelist field."""
    return [_public_product(p) for p in products if _is_orderable(p)]


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


def _heavy_surcharge(real_items) -> int:
    """Port calculateHeavySurcharge() cua FE."""
    total_cases = 0.0
    for r in real_items:
        p = r["product"]
        unit = (p.get("Unit") or "").lower()
        name = p.get("FullName") or p.get("Name") or ""
        if unit == "thùng" and _HEAVY_PATTERN.search(name):
            total_cases += r["quantity"]
    if total_cases > 20:
        return 100000
    if total_cases > 10:
        return 50000
    if total_cases > 5:
        return 20000
    return 0


def _calc_ship_cost(subtotal, distance_km, real_items) -> float:
    """Port calculateShipCost() cua FE ShippingService."""
    if subtotal < _MIN_DELIVERY_SUBTOTAL:
        return 0.0
    if subtotal < 500000:
        free_km, rate = 0, 12000
    elif subtotal < 1000000:
        free_km, rate = 2, 6000
    elif subtotal < 2000000:
        free_km, rate = 3, 5000
    elif subtotal < 10000000:
        free_km, rate = 5, 5000
    else:
        free_km, rate = 7, 4000
    chargeable = max(0.0, distance_km - free_km)
    raw = chargeable * rate
    ship = math.floor(raw / 1000 + 0.5) * 1000  # khop Math.round cua JS
    return ship + _heavy_surcharge(real_items)


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


def _recompute_order_economics(order, product_service, promotion_service, customer_service) -> dict:
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
            return {"ok": False, "error": "So luong khong hop le"}
        if not pid:
            continue
        server = product_service.read_product(str(pid))
        if not _is_orderable(server):
            name = (server or {}).get("Name") or (server or {}).get("FullName") or pid
            return {"ok": False, "error": f"San pham '{name}' ngung ban hoac khong hop le"}
        purchased.append((server, str(pid), qty))

    if not purchased:
        return {"ok": False, "error": "Gio hang trong hoac san pham khong hop le"}

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

    # 4. Ship: tinh lai tu lat/lng (khong tin shipCost/distanceKm client)
    ship_cost = 0.0
    if order.get("wantDelivery"):
        lat, lng = order.get("lat"), order.get("lng")
        if not _valid_latlng(lat, lng):
            return {"ok": False, "error": "Giao hang can vi tri (lat/lng) hop le"}
        if subtotal < _MIN_DELIVERY_SUBTOTAL:
            return {"ok": False, "error": "Don giao hang toi thieu 200.000d"}
        distance = _recompute_distance_km(lat, lng, None)  # KHONG fallback distanceKm client
        order["distanceKm"] = distance
        ship_items = [{"product": s, "quantity": qty} for (s, _pid, qty) in purchased]
        ship_cost = _calc_ship_cost(subtotal, distance, ship_items)
        if ship_cost > 0:
            new_items.append(_order_line(
                {"Id": _SHIP_PRODUCT_ID, "Code": _SHIP_PRODUCT_CODE, "Name": "Phi Giao hang",
                 "FullName": "Phi Giao hang", "BasePrice": ship_cost, "Unit": "Dich vu"},
                1, ship_cost, False, False))

    # 5. Diem thuong: cap theo so du THAT (logic RewardService.calculateFinal)
    available = _customer_available_points(customer_service, order.get("customer"))
    req_ship = max(0.0, _to_float(order.get("pointsUsedForShip")))
    req_order = max(0.0, _to_float(order.get("pointsUsedForOrder")))
    pts_ship = min(available, ship_cost, req_ship) if req_ship > 0 else 0.0
    remaining = max(0.0, available - pts_ship)
    pts_order = min(remaining, subtotal, req_order) if req_order > 0 else 0.0

    customer_paid = max(0.0, (subtotal - pts_order) + (ship_cost - pts_ship))

    # 6. Ghi de order bang du lieu server (chan ly)
    order["cartItems"] = new_items
    order["shipCost"] = ship_cost
    order["pointsUsedForShip"] = pts_ship
    order["pointsUsedForOrder"] = pts_order
    order["discountAmount"] = total_discount + pts_order
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
    product_service, promotion_service, order_service, customer_service, socketio
) -> Blueprint:
    """API public cho app DatHang - chi tra field an toan, khach khong thay du lieu noi bo."""
    bp = Blueprint("firebase_public", __name__, url_prefix="/api/public")

    def _enrich_clone_stock(products):
        """Gop OnHandNV cua clone vao product goc.
        Dung chung cache key 'clone_stock_map' voi endpoint noi bo de tiet kiem quota."""
        cache_key = "clone_stock_map"
        if product_service.cache.has(cache_key):
            clone_stock = product_service.cache.get(cache_key)
        else:
            all_products = product_service.read_all_products(include_inactive=False, include_deleted=False)
            clone_stock = {}
            for p in all_products:
                is_clone = p.get("isClone") is True or p.get("isClone") == "true"
                on_hand_nv = _to_float(p.get("OnHandNV"))
                on_hand = _to_float(p.get("OnHand"))
                if not (is_clone or (on_hand_nv > 0 and on_hand == 0)):
                    continue
                if on_hand_nv <= 0:
                    continue
                source_id = str(p.get("CloneSourceId") or "")
                if source_id:
                    clone_stock[source_id] = clone_stock.get(source_id, 0) + on_hand_nv
            product_service.cache.set(cache_key, clone_stock, ttl=3600)

        for p in products:
            pid = str(p.get("Id", ""))
            p["CloneOnHandNV"] = clone_stock.get(pid, 0)
        return products

    @bp.route("/products/featured", methods=["GET"])
    @handle_api_errors
    def public_featured():
        products = product_service.get_featured_products()
        products = _enrich_clone_stock(products)
        cleaned = _serialize_public_products(products)
        total = len(cleaned)
        limit, offset = _paginate()
        page = cleaned[offset:offset + limit] if limit > 0 else cleaned
        return jsonify({
            "products": page,
            "count": len(page),
            "total": total,
            "hasMore": (offset + len(page)) < total,
        })

    @bp.route("/categories", methods=["GET"])
    @handle_api_errors
    def public_categories():
        """Danh muc cho DatHang - KHONG goi thang KiotViet o request cua khach.

        `/api/kiotviet/categories` phu thuoc token KiotViet: token het han -> 502 -> FE
        nhan [] va mat sach thanh danh muc (loi da xay ra that). O day:
          - Ten danh muc: `product_service.read_categories()` (KiotViet -> snapshot Firestore).
          - Danh muc duoc hien: chi nhung CategoryId THUC SU con san pham ban duoc
            (bam vao khong bi trang rong), tru danh muc an.
          - Thieu ten trong snapshot thi lay `CategoryName` tren chinh product.
        """
        names: dict = {}
        for cat in product_service.read_categories():
            try:
                names[int(cat.get("Id"))] = {
                    "Name": (cat.get("Name") or "").strip(),
                    "Path": cat.get("Path") or "",
                }
            except (TypeError, ValueError):
                continue

        active_ids: dict = {}
        for prod in product_service.read_all_products():
            if not _is_orderable(prod):
                continue
            cid = prod.get("CategoryId")
            try:
                cid = int(cid)
            except (TypeError, ValueError):
                continue
            if cid in _HIDDEN_CATEGORY_IDS:
                continue
            active_ids.setdefault(cid, (prod.get("CategoryName") or "").strip())

        result = []
        for cid, product_name in active_ids.items():
            known = names.get(cid) or {}
            name = known.get("Name") or product_name
            if not name:
                continue  # khong biet ten -> khong hien chip trong
            result.append({
                "Id": cid,
                "Name": name,
                "Path": known.get("Path") or _category_path(name),
            })

        result.sort(key=lambda c: c["Name"])
        return jsonify(result)

    @bp.route("/products/by-category/<int:category_id>", methods=["GET"])
    @handle_api_errors
    def public_by_category(category_id: int):
        products = product_service.read_products_by_category(category_id)
        products = _enrich_clone_stock(products)
        cleaned = _serialize_public_products(products)
        total = len(cleaned)
        limit, offset = _paginate()
        page = cleaned[offset:offset + limit] if limit > 0 else cleaned
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
        products = _enrich_clone_stock(products)
        cleaned = _serialize_public_products(products)
        return jsonify({"products": cleaned, "count": len(cleaned), "query": query})

    @bp.route("/promotions/active", methods=["GET"])
    @handle_api_errors
    def public_active_promotions():
        promos = promotion_service.read_active_promotions()
        result = []
        product_cache: dict = {}

        def _resolve(product_id) -> dict | None:
            key = str(product_id)
            if key not in product_cache:
                product = product_service.read_product(key)
                product_cache[key] = _public_product(product) if product else None
            return product_cache[key]

        for pr in promos:
            target_product = None
            pid = pr.get("targetProductId")
            if pid:
                target_product = _resolve(pid)

            gift_products = []
            for entry in _public_gift_entries(pr):
                gp = _resolve(entry["productId"])
                if gp:
                    gift_products.append({**gp, "GiftQuantity": entry.get("quantity") or 1})

            result.append(_public_promotion(pr, target_product, gift_products))
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
            return jsonify({"error": "So dien thoai khong hop le"}), 400

        # Tinh lai toan bo tu server; reject neu don khong hop le
        econ = _recompute_order_economics(order, product_service, promotion_service, customer_service)
        if not econ.get("ok"):
            return jsonify({"error": econ.get("error", "Don hang khong hop le")}), 400

        # Luu ATOMIC: create() fail neu id da ton tai -> chan overwrite (khong race nhu read+set)
        oid = str(order.get("id") or ("DH" + str(int(time.time() * 1000))))
        order["id"] = oid
        try:
            order_service.orders_ref.document(oid).create(order)
            order_service.cache.invalidate("all_orders")
        except Exception as e:
            if type(e).__name__ in ("AlreadyExists", "Conflict") or "already exist" in str(e).lower():
                return jsonify({"error": "Order ID da ton tai"}), 409
            raise
        result = {"message": "order added"}
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
