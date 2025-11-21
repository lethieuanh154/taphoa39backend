from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer


BASE_URL = "https://api-man1.kiotviet.vn/api/branchs/{branch_id}/masterproducts"

DEFAULT_HEADERS = {
	"Accept": "application/json, text/plain, */*",
	"Authorization": auth_token,
	"BranchId": str(LatestBranchId),
	"FingerPrintKey": "211d1f5bb8cc08a94863d2291f1c866d_Chrome_Desktop_Máy tính Windows",
	"IsUseKvClient": "1",
	"Referer": "https://taphoa39dn.kiotviet.vn/",
	"Retailer": retailer,
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
	"X-GROUP-ID": "10",
	"X-Language": "vi-VN",
	"X-RETAILER-CODE": retailer,
	"X-TIMEZONE": "",
	"sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
	"sec-ch-ua-mobile": "?0",
	"sec-ch-ua-platform": '"Windows"',
}

DEFAULT_PARAMS = {
	"format": "json",
	"Includes": "ProductAttributes",
	"ForSummaryRow": "true",
	"CategoryId": 0,
	"AttributeFilter": "[]",
	"BranchId": -1,
	"ProductTypes": "",
	"IsImei": 2,
	"IsFormulas": 2,
	"IsActive": "true",
	"RelateToChannel": "false",
	"AllowSale": "true",
	"OrderBy": "OnHand",
	"Reverse": "true",
	"OnhandFilter": 4,
	"IsBatchExpireControl": 2,
	"ShelvesIds": "",
	"TrademarkIds": "",
	"StockoutDate": "alltime",
	"CreatedDate": "alltime",
	"supplierIds": "",
	"isNewFilter": "true",
	"sort[0][field]": "OnHand",
	"sort[0][dir]": "desc",
	"filter[logic]": "and",
}


def _build_paging(page: int, page_size: int, skip: Optional[int] = None) -> Dict[str, Any]:
	if page <= 0:
		page = 1
	if page_size <= 0:
		page_size = 10000
	if skip is None:
		skip = (page - 1) * page_size

	return {
		"page": page,
		"pageSize": page_size,
		"take": page_size,
		"skip": skip,
	}


def fetch_out_of_stock_master_products(
	*,
	branch_id: Optional[int] = None,
	page: int = 1,
	page_size: int = 10000,
	timeout: int = 30,
) -> Dict[str, Any]:
	"""Return the raw KiotViet response for the masterproducts out-of-stock API."""

	branch = branch_id or LatestBranchId
	url = BASE_URL.format(branch_id=branch)

	params = dict(DEFAULT_PARAMS)
	params.update(_build_paging(page, page_size))

	headers = dict(DEFAULT_HEADERS)
	headers["Authorization"] = auth_token
	headers["BranchId"] = str(branch)
	headers["X-RETAILER-CODE"] = retailer
	headers["Retailer"] = retailer

	response = requests.get(url, headers=headers, params=params, timeout=timeout)
	response.raise_for_status()
	return response.json()


def get_out_of_stock_master_products_data(**kwargs) -> Any:
	"""Convenience helper that returns only the "Data" array from the response."""

	payload = fetch_out_of_stock_master_products(**kwargs)
	return payload.get("Data") or payload.get("data") or []
