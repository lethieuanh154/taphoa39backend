import time

import requests
from FromKiotViet.get_authorization import get_token, refresh_token
from Utility.get_env import LatestBranchId, retailer

url = f"https://api-kvsync1.kiotviet.vn/api/resource/fetch"

param = {
      "clientId":"WebAppWN-3e31c9b0-cd4a-43e6-be25-a5d1330372fd-500111210-878979",
      "resourceName":"Products",
      "pageSize":20000
  }

# KiotViet fetch 20k products thường mất 30-60s → read timeout phải rộng
FETCH_TIMEOUT = (10, 180)
MAX_ATTEMPTS = 3

def _build_header(token: str):
    return {
        "Authorization": token,
        "retailer": retailer,
        "branchid": LatestBranchId
    }

def get_all():
    token = get_token() or refresh_token()
    if not token:
        print("❌ KiotViet: không lấy được token (kiểm tra UserName/Password/retailer trong env).")
        return None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, headers=_build_header(token), params=param, timeout=FETCH_TIMEOUT)
        except requests.RequestException as exc:
            print(f"⚠️ KiotViet fetch products lỗi mạng (attempt {attempt}/{MAX_ATTEMPTS}): {exc}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 * attempt)
                continue
            return None

        if response.status_code == 200:
            raw_items = response.json().get('Data', [])
            filtered_items = [item for item in raw_items if not item.get('isDeleted', False)]
            suffix = "" if attempt == 1 else f" (attempt {attempt})"
            print(f"Total products : {len(filtered_items)}{suffix}")
            return filtered_items

        if response.status_code in (401, 403):
            print(f"⚠️ KiotViet token expired (status={response.status_code}), refreshing...")
            token = refresh_token()
            if not token:
                print("❌ KiotViet: refresh token thất bại.")
                return None
            continue

        if response.status_code >= 500 or response.status_code == 429:
            print(f"⚠️ KiotViet trả {response.status_code} (attempt {attempt}/{MAX_ATTEMPTS}), retry...")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 * attempt)
                continue

        print(f"❌ KiotViet API error: status={response.status_code}, body={response.text[:500]}")
        return None

    print(f"❌ KiotViet fetch products thất bại sau {MAX_ATTEMPTS} lần thử.")
    return None


def get_deleted_products():
  response = requests.request("GET", url, headers=_build_header(get_token()), params=param, timeout=FETCH_TIMEOUT)
  if response.status_code == 200:
      data = response.json()
      raw_items = data.get('Data', [])
      filtered_items = [item for item in raw_items if item.get('isDeleted', False)]
      print(f"Total products deleted: {len(filtered_items)}")
      return filtered_items
  else:
      return None

def get_inactive_products():
  response = requests.request("GET", url, headers=_build_header(get_token()), params=param, timeout=FETCH_TIMEOUT)
  if response.status_code == 200:
      data = response.json()
      raw_items = data.get('Data', [])
      filtered_items = [item for item in raw_items if not item.get('isActive', True)]
      print(f"Total products inactive: {len(filtered_items)}")
      return filtered_items
  else:
      return None
  