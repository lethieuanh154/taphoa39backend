import requests
from typing import List, Dict, Any

from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer

url = "https://api-man1.kiotviet.vn/api/customers/deleteCustomerList"


def delete_customers_from_kiotviet(customer_ids: List[int]) -> Dict[str, Any]:
    """
    Xóa danh sách khách hàng trên KiotViet.

    Args:
        customer_ids: Danh sách ID (số) của khách hàng cần xóa.

    Returns:
        Response JSON từ KiotViet, ví dụ:
        {"Message": "Xóa thành công danh sách khách hàng đã chọn", "Code": 1}

    Raises:
        ValueError: Nếu danh sách rỗng.
        RuntimeError: Nếu KiotViet API trả về lỗi.
    """
    if not customer_ids:
        raise ValueError("customer_ids must not be empty")

    headers = {
        "Authorization": auth_token,
        "branchid": LatestBranchId,
        "retailer": retailer,
        "Content-Type": "application/json",
    }

    body = {"Ids": customer_ids}

    response = requests.post(url, headers=headers, json=body, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(
            f"KiotViet API error {response.status_code}: {response.text}"
        )

    return response.json()
