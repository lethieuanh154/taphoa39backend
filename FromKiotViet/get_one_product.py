from unicodedata import category
import requests
from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer
import os
import json

def get_item(tearm):
    url = f"https://api-man1.kiotviet.vn/api/branchs/878979/masterproducts?format=json&Includes=ProductAttributes&ForSummaryRow=true&CategoryId=0&AttributeFilter=%5B%5D&ProductKey={tearm}&BranchId=-1&ProductTypes=&IsImei=2&IsFormulas=2&IsActive=true&AllowSale=&IsBatchExpireControl=2&ShelvesIds=&TrademarkIds=&StockoutDate=alltime&CreatedDate=alltime&supplierIds=&isNewFilter=true&take=100&skip=0&page=1&pageSize=100&filter%5Blogic%5D=and"

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

