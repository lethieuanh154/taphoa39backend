from unicodedata import category
import requests
import json
import os

import unidecode
from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer

# URL API
productUrl = f"https://api-man1.kiotviet.vn/api/branchs/{LatestBranchId}/masterproducts"

def get_items_category(category_id):
    # Headers

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
    
def get_items_out_of_stock():
    header = {
        "Authorization": auth_token,
        "retailer": retailer,
        "branchid": LatestBranchId
    }
    param = {
        "format": "json",
        "Includes": "ProductAttributes",
        "ForSummaryRow": True,
        "CategoryId": 0,
        "AttributeFilter": [],
        "BranchId": -1,
        "ProductTypes": "",
        "IsImei": 2,
        "IsFormulas": 2,
        "IsActive": True,
        "AllowSale": "",
        "OrderBy": "OnHand",
        "Reverse": False,
        "OnhandFilter": 5,
        "OnhandFilterStr": "<=:1",
        "IsBatchExpireControl": 2,
        "ShelvesIds": "",
        "TrademarkIds": "",
        "StockoutDate": "alltime",
        "CreatedDate": "alltime",
        "supplierIds": "",
        "isNewFilter": True,
        "take": 10000,
        "skip": 0,
        "page": 1,
        "pageSize": 100,
        "sort": [
          {
            "field": "OnHand",
            "dir": "asc"
          }
        ],
        "filter": {
          "logic": "and"
        }
    }

    response = requests.get(productUrl, headers=header, params=param)
    if response.status_code == 200:
        data: list = response.json().get("Data", [])
        total: int = response.json().get("Total")
        return {'data': data[1:], 'Total': total}
    else:
        return None
    