import time

import requests
from FromKiotViet.get_authorization import get_token, refresh_token
from Utility.get_env import LatestBranchId, retailer

# API list bien the cua 1 master product. Khac voi resource/fetch (sync toan bo):
# resource/fetch tra `Image` cap MASTER (moi bien the deu giong nhau),
# endpoint nay tra `Image` RIENG cua tung bien the.
url = f"https://api-man1.kiotviet.vn/api/branchs/{LatestBranchId}/masterproducts"

TIMEOUT = (10, 60)
MAX_ATTEMPTS = 3


def _build_header(token: str):
    return {
        "Authorization": token,
        "retailer": retailer,
        "branchid": LatestBranchId,
    }


def _build_payload(take: int):
    return {
        "$inlinecount": "allpages",
        "$format": "json",
        "CategoryIds": "[]",
        "AttributeFilter": "[]",
        "ConditionTaxIds": "",
        "BranchId": -1,
        "ProductTypes": "",
        "IsImei": 2,
        "IsFormulas": 2,
        "IsActive": True,
        "AllowSale": None,
        "IsBatchExpireControl": 2,
        "ShelvesIds": "",
        "TrademarkIds": "",
        "StockoutDate": "alltime",
        "CreatedDate": "alltime",
        "supplierIds": "",
        "isNewFilter": True,
        "$top": take,
        "Skip": 0,
        "Take": take,
        "PageSize": take,
        "Page": 1,
    }


def get_variants(master_product_id, take: int = 100):
    """Lay tat ca bien the cua 1 master product.

    Returns list item (moi item co Id/ProductId, Code, Image rieng), hoac None neu loi.
    """
    token = get_token() or refresh_token()
    if not token:
        print("❌ KiotViet: không lấy được token (kiểm tra UserName/Password/retailer trong env).")
        return None

    params = {
        "format": "json",
        "Includes": "ProductAttributes",
        "MasterProductId": master_product_id,
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                url,
                headers=_build_header(token),
                params=params,
                json=_build_payload(take),
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            print(f"⚠️ KiotViet masterproducts {master_product_id} lỗi mạng "
                  f"(attempt {attempt}/{MAX_ATTEMPTS}): {exc}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 * attempt)
                continue
            return None

        if response.status_code == 200:
            return response.json().get("Data", []) or []

        if response.status_code in (401, 403):
            print(f"⚠️ KiotViet token expired (status={response.status_code}), refreshing...")
            token = refresh_token()
            if not token:
                print("❌ KiotViet: refresh token thất bại.")
                return None
            continue

        if response.status_code >= 500 or response.status_code == 429:
            print(f"⚠️ KiotViet trả {response.status_code} "
                  f"(attempt {attempt}/{MAX_ATTEMPTS}), retry...")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 * attempt)
                continue
            return None

        print(f"❌ KiotViet masterproducts {master_product_id} trả {response.status_code}: "
              f"{response.text[:200]}")
        return None

    return None


def get_variant_images(master_product_id, take: int = 100) -> dict:
    """Map {product_id_str: image_url} cho cac bien the cua 1 master product."""
    items = get_variants(master_product_id, take=take)
    if not items:
        return {}
    images = {}
    for item in items:
        pid = item.get("ProductId") or item.get("Id")
        image = item.get("Image") or item.get("ProductImage")
        if pid and image:
            images[str(pid)] = image
    return images
