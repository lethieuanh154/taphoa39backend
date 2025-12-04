from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

from dateutil.parser import isoparse


@dataclass
class Product:
    Id: int
    Code: Optional[str] = None
    Name: Optional[str] = None
    FullName: Optional[str] = None
    CategoryId: Optional[int] = None
    isActive: bool = True
    isDeleted: bool = False
    Cost: float = 0.0
    BasePrice: float = 0.0
    OnHand: float = 0.0
    OnHandNV: float = 0.0
    Unit: Optional[str] = None
    MasterUnitId: Optional[int] = None
    MasterProductId: Optional[int] = None
    ConversionValue: float = 0.0
    Description: Optional[str] = None
    IsRewardPoint: bool = False
    ModifiedDate: Optional[datetime] = None
    Image: Optional[str] = None
    CreatedDate: Optional[datetime] = None
    ProductAttributes: List[Any] = field(default_factory=list)
    NormalizedName: Optional[str] = None
    NormalizedCode: Optional[str] = None
    OrderTemplate: Optional[str] = None

    @staticmethod
    def from_dict(data: dict) -> "Product":
        if "Id" not in data:
            raise KeyError("Id")

        def safe_float(value: Any, default: float = 0.0) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
            try:
                return int(value) if value is not None else default
            except (TypeError, ValueError):
                return default

        def safe_bool(value: Any, default: bool) -> bool:
            if isinstance(value, bool):
                return value
            if value in ("true", "True", 1, "1"):
                return True
            if value in ("false", "False", 0, "0"):
                return False
            return default

        def safe_datetime(value: Any) -> Optional[datetime]:
            if not value:
                return None
            try:
                return isoparse(value)
            except (TypeError, ValueError):
                return None

        return Product(
            Id=safe_int(data.get("Id"), 0) or 0,
            Code=data.get("Code"),
            Name=data.get("Name"),
            FullName=data.get("FullName"),
            CategoryId=safe_int(data.get("CategoryId")),
            isActive=safe_bool(data.get("isActive"), True),
            isDeleted=safe_bool(data.get("isDeleted"), False),
            Cost=safe_float(data.get("Cost"), 0.0),
            BasePrice=safe_float(data.get("BasePrice"), 0.0),
            OnHand=safe_float(data.get("OnHand"), 0.0),
            Unit=data.get("Unit"),
            MasterUnitId=safe_int(data.get("MasterUnitId")),
            MasterProductId=safe_int(data.get("MasterProductId")),
            ConversionValue=safe_float(data.get("ConversionValue"), 0.0),
            Description=data.get("Description"),
            IsRewardPoint=safe_bool(data.get("IsRewardPoint"), False),
            ModifiedDate=safe_datetime(data.get("ModifiedDate")),
            Image=data.get("Image"),
            CreatedDate=safe_datetime(data.get("CreatedDate")),
            ProductAttributes=data.get("ProductAttributes", []) or [],
            OnHandNV=safe_float(data.get("OnHandNV"), 0.0),
            NormalizedName=data.get("NormalizedName"),
            NormalizedCode=data.get("NormalizedCode"),
            OrderTemplate=data.get("OrderTemplate"),
        )