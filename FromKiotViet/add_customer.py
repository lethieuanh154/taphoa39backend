import requests
from typing import Any, Dict

from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer

url = "https://api-man1.kiotviet.vn/api/customers"


def add_customer_to_kiotviet(customer_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(customer_payload, dict):
        raise ValueError("customer_payload must be a JSON object")

    normalized_payload = dict(customer_payload)
    normalized_payload.setdefault("BranchId", LatestBranchId)
    normalized_payload.setdefault("IsActive", True)

    headers = {
        "Authorization": auth_token,
        "branchid": LatestBranchId,
        "retailer": retailer,
        "Content-Type": "application/json",
    }

    body = {
        "Customer": normalized_payload,
        "isMergedSupplier": False,
        "isCreateNewSupplier": False,
        "MergedSupplierId": 0,
        "SkipValidateEmail": False,
    }

    response = requests.post(url, headers=headers, json=body, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(
            f"KiotViet API error {response.status_code}: {response.text}"
        )

    return response.json()
