from unicodedata import category
import requests
import json
import os

import unidecode
from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer

# URL API

def get_items_category(category_id):
    # Headers
    productUrl = f"https://api-man1.kiotviet.vn/api/branchs/{LatestBranchId}/masterproducts"

    header = {
        "Authorization": auth_token,
        "retailer": retailer,
        "branchid": LatestBranchId
    }
    param = {
        "format": "json",
        "Includes": "ProductAttributes",
        "ForSummaryRow": "true",
        "CategoryId": category_id,
        "AttributeFilter": "[]",
        "BranchId": LatestBranchId,
        "ProductTypes": "",
        "IsImei": 2,
        "IsFormulas": 2,
        "IsActive": "true",
        "AllowSale": "",
        "IsBatchExpireControl": 2,
        "ShelvesIds": "",
        "TrademarkIds": "",
        "StockoutDate": "alltime",
        "CreatedDate": "alltime",
        "supplierIds": "",
        "isNewFilter": "true",
        "take": 2000,
        "skip": 0,
        "page": 1,
        "pageSize": 2000,
        "filter[logic]": "and"
    }
    response = requests.get(productUrl, headers=header, params=param)
    if response.status_code == 200:
        data: list = response.json().get("Data", [])
        return data[1:]
    else:
        return None