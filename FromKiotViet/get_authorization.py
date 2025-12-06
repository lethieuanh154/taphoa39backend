import requests
from Utility.get_env import UserName, Password, LatestBranchId, retailer


def get_authen_with_credentials(username: str, password: str, branch_id: str, retailer_name: str) -> str:
    """
    Get KiotViet authentication token with provided credentials.
    
    Args:
        username: KiotViet username
        password: KiotViet password
        branch_id: Latest branch ID
        retailer_name: Retailer name
        
    Returns:
        Bearer token string or None if authentication fails
    """
    auth_url = "https://api-man1.kiotviet.vn/api/account/login? quan-ly=true"
    body = {
        "model": {
            "RememberMe": "true",
            "ShowCaptcha": "false",
            "UserName": username,
            "Password": password,
            "Language": "vi-VN",
            "LatestBranchId": branch_id
        },
        "IsManageSide": "true",
        "FingerPrintKey": "211d1f5bb8cc08a94863d2291f1c866d_Chrome_Desktop_Máy tính Windows"
    }
    params = {"quan-ly": "true"}
    headers = {
        "retailer": retailer_name
    }
    
    try:
        response = requests.post(auth_url, json=body, headers=headers, params=params, timeout=30)
        if response.status_code == 200:
            data = response. json().get("token", "")
            return "Bearer " + data if data else None
        else:
            return None
    except requests.RequestException:
        return None


def get_authen() -> str:
    """
    Get KiotViet authentication token using environment credentials.
    Legacy function for backward compatibility. 
    """
    return get_authen_with_credentials(UserName, Password, LatestBranchId, retailer)


# Cache the token for reuse
auth_token = get_authen()