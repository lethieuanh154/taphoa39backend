from unicodedata import category
import requests
from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer
import os
import json

def get_item(tearm):
    url = f"https://api-man1.kiotviet.vn/api/products/suggest?tearm={tearm}&IncludeCombo=true&ShowAllItem=false&IsShowOnHand=true&ExcludeProductIds=&IsGetTotalOnhand=false"

    # Headers
    header = {
        "Authorization": auth_token,
        "retailer": retailer,
        "branchid": LatestBranchId
    }

    response = requests.get(url, headers=header)
    if response.status_code == 200:
        data = response.json()
        return data
    else:
        return None
