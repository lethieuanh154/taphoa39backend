import requests

import unidecode
from Utility.get_env import LatestBranchId, retailer
from FromKiotViet.get_authorization import get_token, refresh_token


def get_category():
    url = "https://api-man1.kiotviet.vn/api/categories"
    headers = {
        "Authorization": get_token(),
        "retailer": retailer,
        "branchid": LatestBranchId
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 401:
            headers["Authorization"] = refresh_token()
            response = requests.get(url, headers=headers)
        response.raise_for_status()
        data: list = response.json().get("Data", [])
        if not data:
            return None

        result = [
            {
                "Id": item.get("Id"),
                "Name": item.get("Name"),
                "Path": unidecode.unidecode(item.get("Name")).replace("-", "").replace(",", "").replace("__",
                                                                                                        "_").replace(
                    " ", "_").replace("__", "_").upper(),

            } for item in data
        ]
        return result  # Return the full result list
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return None
