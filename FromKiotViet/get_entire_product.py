import requests
from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer

url = f"https://api-kvsync1.kiotviet.vn/api/resource/fetch"
  # Headers
header = {
      "Authorization": auth_token,
      "retailer": retailer,
      "branchid": LatestBranchId
  }
param = {
      "clientId":"WebAppWN-3e31c9b0-cd4a-43e6-be25-a5d1330372fd-500111210-878979",
      "resourceName":"Products",
      "pageSize":20000
  }

def get_all():
    response = requests.get(url, headers=header, params=param)
    if response.status_code == 200:
        data = response.json()
        raw_items = data.get('Data', [])
        filtered_items = [item for item in raw_items if not item.get('isDeleted', False)]
        print(f"Total products : {len(filtered_items)}")
        return filtered_items
    else:
        return None
    

def get_deleted_products():
  response = requests.request("GET", url, headers=header, params=param)
  if response.status_code == 200:
      data = response.json()
      raw_items = data.get('Data', [])
      # Lọc bỏ các object có isDeleted = false hoặc isActive = true
      filtered_items = [item for item in raw_items if item.get('isDeleted', False)]
      print(f"Total products deleted: {len(filtered_items)}")

      return filtered_items
  else:
      return None
    
def get_inactive_products():
  response = requests.request("GET", url, headers=header, params=param)
  if response.status_code == 200:
      data = response.json()
      raw_items = data.get('Data', [])
      # Lọc bỏ các object có isDeleted = false hoặc isActive = true
      filtered_items = [item for item in raw_items if not item.get('isActive', True)]

      print(f"Total products inactive: {len(filtered_items)}")
      return filtered_items
  else:
      return None
  