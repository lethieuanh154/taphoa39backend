import requests
from Utility.get_env import UserName, Password, LatestBranchId, retailer


def get_authen():
    auth_url = "https://api-man1.kiotviet.vn/api/account/login?quan-ly=true"
    body = {
        "model": {
            "RememberMe": "true",
            "ShowCaptcha": "false",
            "UserName": UserName,
            "Password": Password,
            "Language": "vi-VN",
            "LatestBranchId": LatestBranchId
        },
        "IsManageSide": "true",
        "FingerPrintKey": "211d1f5bb8cc08a94863d2291f1c866d_Chrome_Desktop_Máy tính Windows"
    }
    params = {"quan-ly": "true"}
    headers = {
        "retailer": retailer
    }
    response = requests.post(auth_url, json=body, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json().get("token", "")
        return "Bearer " + data
    else:
        return None


auth_token = get_authen()
