import requests
from FromKiotViet.get_authorization import get_token, refresh_token
from Utility.get_env import LatestBranchId, retailer

url = f"https://api-kvsync1.kiotviet.vn/api/resource/fetch"

param = {
      "clientId":"WebAppWN-3e31c9b0-cd4a-43e6-be25-a5d1330372fd-500111210-878979",
      "resourceName":"Products",
      "pageSize":20000
  }

def _build_header():
    return {
        "Authorization": get_token(),
        "retailer": retailer,
        "branchid": LatestBranchId
    }

def get_all():
    response = requests.get(url, headers=_build_header(), params=param)
    if response.status_code == 200:
        data = response.json()
        raw_items = data.get('Data', [])
        filtered_items = [item for item in raw_items if not item.get('isDeleted', False) ]
        print(f"Total products : {len(filtered_items)}")
        return filtered_items

    # Token expired → refresh and retry once
    if response.status_code in (401, 403):
        print(f"⚠️ KiotViet token expired (status={response.status_code}), refreshing...")
        refresh_token()
        if get_token():
            response = requests.get(url, headers=_build_header(), params=param)
            if response.status_code == 200:
                data = response.json()
                raw_items = data.get('Data', [])
                filtered_items = [item for item in raw_items if not item.get('isDeleted', False)]
                print(f"Total products (after refresh): {len(filtered_items)}")
                return filtered_items

    print(f"❌ KiotViet API error: status={response.status_code}, body={response.text[:500]}")
    return None
    

def get_deleted_products():
  response = requests.request("GET", url, headers=_build_header(), params=param)
  if response.status_code == 200:
      data = response.json()
      raw_items = data.get('Data', [])
      filtered_items = [item for item in raw_items if item.get('isDeleted', False)]
      print(f"Total products deleted: {len(filtered_items)}")
      return filtered_items
  else:
      return None

def get_inactive_products():
  response = requests.request("GET", url, headers=_build_header(), params=param)
  if response.status_code == 200:
      data = response.json()
      raw_items = data.get('Data', [])
      filtered_items = [item for item in raw_items if not item.get('isActive', True)]
      print(f"Total products inactive: {len(filtered_items)}")
      return filtered_items
  else:
      return None
  