from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


CUSTOMER_FIELD_NAMES: Tuple[str, ...] = (
    "Id",
    "BranchId",
    "Code",
    "Name",
    "CompareCode",
    "CompareName",
    "ContactNumber",
    "TaxCode",
    "Email",
    "CreatedBy",
    "CreatedDate",
    "CreatedName",
    "CustomerType",
    "Debt",
    "GenderName",
    "Groups",
    "IsActive",
    "isDeleted",
    "Address",
    "Organization",
    "TotalInvoiced",
    "TotalPoint",
    "TotalReturn",
    "TotalRevenue",
    "RewardPoint",
    "LocationName",
    "WardName",
)


@dataclass
class Customer:
	Id: Optional[Any] = None
	BranchId: Optional[Any] = None
	Code: Optional[str] = None
	Name: Optional[str] = None
	CompareCode: Optional[str] = None
	CompareName: Optional[str] = None
	ContactNumber: Optional[str] = None
	TaxCode: Optional[str] = None
	Email: Optional[str] = None
	CreatedBy: Optional[Any] = None
	CreatedDate: Optional[str] = None
	CreatedName: Optional[str] = None
	CustomerType: Optional[str] = None
	Debt: Optional[Any] = None
	GenderName: Optional[str] = None
	Groups: Optional[str] = None
	IsActive: Optional[bool] = None
	isDeleted: Optional[bool] = None
	Address: Optional[str] = None
	Organization: Optional[str] = None
	TotalInvoiced: Optional[Any] = None
	TotalPoint: Optional[Any] = None
	TotalReturn: Optional[Any] = None
	TotalRevenue: Optional[Any] = None
	RewardPoint: Optional[Any] = None
	LocationName: Optional[str] = None
	WardName: Optional[str] = None

	_FIELD_ORDER: Tuple[str, ...] = field(default=CUSTOMER_FIELD_NAMES, init=False, repr=False)

	@classmethod
	def from_dict(cls, data: Dict[str, Any], default_branch_id: Optional[Any] = None) -> "Customer":
		payload: Dict[str, Any] = {}
		for field_name in cls._FIELD_ORDER:
			if field_name == "Id":
				payload[field_name] = data.get("Id", data.get("id"))
			else:
				payload[field_name] = data.get(field_name)

		instance = cls(**payload)
		if instance.BranchId is None and default_branch_id is not None:
			instance.BranchId = default_branch_id
		return instance

	@classmethod
	def from_frontend_payload(
		cls,
		data: Dict[str, Any],
		default_branch_id: Optional[Any] = None,
	) -> "Customer":
		if not isinstance(data, dict):
			raise ValueError("Payload must be an object")

		name = (data.get("name") or "").strip()
		if not name:
			raise ValueError("name is required")

		contact = (data.get("phone") or data.get("contactNumber") or "").strip() or None
		gender = data.get("gender")
		gender_value = str(gender) if gender not in (None, "") else None

		instance = cls(
			Name=name,
			CompareName=name,
			ContactNumber=contact,
			Address=(data.get("address") or "").strip() or None,
			Email=(data.get("email") or "").strip() or None,
			CustomerType=str(data.get("type")) if data.get("type") is not None else None,
			GenderName=gender_value,
			TaxCode=(data.get("taxCode") or "").strip() or None,
			Organization=(data.get("organization") or "").strip() or None,
			Debt=0,
			TotalInvoiced=0,
			TotalPoint=0,
			TotalReturn=0,
			TotalRevenue=0,
			RewardPoint=0,
			IsActive=True,
			isDeleted=False,
		)

		if default_branch_id is not None:
			instance.BranchId = default_branch_id

		return instance

	def ensure_id(self, fallback_id: Any) -> None:
		if fallback_id is None:
			return
		self.Id = fallback_id

	def apply_kiotviet_response(self, response: Dict[str, Any]) -> None:
		if not isinstance(response, dict):
			return

		if response.get("Id") is not None:
			self.Id = response.get("Id")

		if response.get("Code"):
			self.Code = response.get("Code")
			if not self.CompareCode:
				self.CompareCode = response.get("Code")

		if not self.Name and response.get("Name"):
			self.Name = response.get("Name")
			self.CompareName = response.get("Name")

		if not self.LocationName and response.get("LocationName"):
			self.LocationName = response.get("LocationName")

		if not self.WardName and response.get("WardName"):
			self.WardName = response.get("WardName")

		if not self.Groups and response.get("Groups"):
			self.Groups = response.get("Groups")

	def to_dict(self, include_none: bool = False, include_id_alias: bool = True) -> Dict[str, Any]:
		result: Dict[str, Any] = {}
		for field_name in self._FIELD_ORDER:
			value = getattr(self, field_name)
			if value is None and not include_none:
				continue
			result[field_name] = value

		if include_id_alias and self.Id is not None:
			result["id"] = str(self.Id)

		return result

	def to_kiotviet_payload(self) -> Dict[str, Any]:
		return self.to_dict(include_none=False, include_id_alias=False)

