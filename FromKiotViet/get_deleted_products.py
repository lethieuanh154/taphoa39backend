import requests
from Utility.get_env import LatestBranchId, retailer
from FromKiotViet.get_authorization import auth_token

url = f"https://api-kvsync1.kiotviet.vn/api/resource/fetch?clientId=WebAppWN-3e31c9b0-cd4a-43e6-be25-a5d1330372fd-500111210-{LatestBranchId}&resourceName=Products&pageSize=20000"

payload = ""
headers = {
  'Authorization': auth_token,
  'retailer': retailer,
  'branchid': LatestBranchId
}


def get_deleted_products():
  response = requests.request("GET", url, headers=headers, data=payload)

  if response.status_code == 200:
      data = response.json()
      raw_items = data.get('Data', [])
      # Lọc bỏ các object có isDeleted = false hoặc isActive = true
      filtered_items = [item for item in raw_items if item.get('isDeleted', False)]

      print(f"Total products fetched: {len(filtered_items)}")
      return filtered_items
  else:
      return None
    
def get_inactive_products():
  response = requests.request("GET", url, headers=headers, data=payload)

  if response.status_code == 200:
      data = response.json()
      raw_items = data.get('Data', [])
      # Lọc bỏ các object có isDeleted = false hoặc isActive = true
      filtered_items = [item for item in raw_items if not item.get('isActive', True)]

      print(f"Total products fetched: {len(filtered_items)}")
      return filtered_items
  else:
      return None
    
get_deleted_products()