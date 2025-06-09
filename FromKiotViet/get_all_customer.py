import requests
from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer


def get_entire_customer():
    url = "https://api-man1.kiotviet.vn/api/customers"
    payload = {}
    headers = {
      'Authorization': auth_token,
      'branchid': LatestBranchId,
      'retailer': retailer
    }
    param = {
        "format": "json",
        "Includes": "TotalInvoiced",
        "Includes": "Location",
        "Includes": 'WardName',
        "ForManageScreen": True,
        "ForSummaryRow": True,
        "UsingTotalApi": True,
        "UsingStoreProcedure": False,
        "SwitchToOrmLite": True,
        "inlinecount": "allpages",
        "DateFilterType": "alltime",
        "NewCustomerDateFilterType":"alltime",
        "NewCustomerLastTradingDateFilterType":"alltime",
        "CustomerBirthDateFilterType":"alltime",
        "top":10000
        }
    response = requests.request("GET", url, headers=headers, data=payload, params=param)
    print(response.status_code)
    if response.status_code == 200:
        print(200)
        data: list = response.json().get("Data", [])
        return data[1:]
    else:
        return None
