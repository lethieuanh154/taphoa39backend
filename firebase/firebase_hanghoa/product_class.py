from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional, Union

from dateutil.parser import isoparse

# Mapping TaxIds -> Tax value (number hoac string)
# KiotViet GET /api/tax/getAll?type=1:
#   Id=1  Name="0%"    Value=0   -> Tax: 0
#   Id=2  Name="5%"    Value=5   -> Tax: 5
#   Id=3  Name="8%"    Value=8   -> Tax: 8
#   Id=4  Name="10%"   Value=10  -> Tax: 10
#   Id=5  Name="KCT"             -> Tax: "KCT"  (Khong chiu thue)
#   Id=12 Name="KKKNT"           -> Tax: "KKKNT" (Khong ke khai nop thue)
TAX_MAPPING: dict[int, Union[int, str]] = {
    1: 0,
    2: 5,
    3: 8,
    4: 10,
    5: "KCT",
    12: "KKKNT",
}
DEFAULT_TAX: Union[int, str] = 0

# String tax values (khong chiu thue)
STRING_TAX_VALUES = {"KCT", "KKKNT"}


def get_tax_value(tax_ids) -> Union[int, str]:
    """
    Chuyen doi TaxIds tu KiotViet sang gia tri Tax.

    Args:
        tax_ids: Co the la list [1], [2], int, string "2", hoac None/""

    Returns:
        int | str: Gia tri Tax (0, 5, 8, 10, "KCT", "KKKNT")
    """
    # Xu ly None hoac string rong
    if tax_ids is None or tax_ids == "" or tax_ids == []:
        return DEFAULT_TAX

    # Neu la list, lay phan tu dau tien
    if isinstance(tax_ids, list):
        if len(tax_ids) == 0:
            return DEFAULT_TAX
        tax_id = tax_ids[0]
        # Kiem tra phan tu dau la rong
        if tax_id == "" or tax_id is None:
            return DEFAULT_TAX
    else:
        tax_id = tax_ids

    # Xu ly string rong
    if isinstance(tax_id, str) and tax_id.strip() == "":
        return DEFAULT_TAX

    # Chuyen sang int
    try:
        tax_id = int(tax_id)
    except (TypeError, ValueError):
        return DEFAULT_TAX

    return TAX_MAPPING.get(tax_id, DEFAULT_TAX)


@dataclass
class Product:
    Id: int
    Code: Optional[str] = None
    Name: Optional[str] = None
    FullName: Optional[str] = None
    CategoryId: Optional[int] = None
    CategoryName: Optional[str] = None
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
    TaxIds: Optional[List[int]] = None
    Tax: Optional[Union[int, str]] = None  # Tax value: 0, 5, 8, 10 (number) hoac "KCT", "KKKNT" (string)

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

        # Parse TaxIds va tu dong tinh Tax
        tax_ids_raw = data.get("TaxIds")
        tax_ids = None
        if tax_ids_raw is not None:
            if isinstance(tax_ids_raw, list):
                tax_ids = tax_ids_raw
            else:
                tax_ids = [tax_ids_raw]

        # Tu dong tinh Tax tu TaxIds (number: 0, 5, 8, 10 hoac string: "KCT", "KKKNT")
        # Uu tien lay Tax tu data neu da co, neu khong thi tinh tu TaxIds
        existing_tax = data.get("Tax")
        if existing_tax is not None:
            # Giu nguyen string tax values ("KCT", "KKKNT")
            if isinstance(existing_tax, str) and existing_tax.strip() in STRING_TAX_VALUES:
                tax_value = existing_tax.strip()
            else:
                try:
                    tax_value = int(existing_tax)
                except (TypeError, ValueError):
                    tax_value = get_tax_value(tax_ids)
        else:
            tax_value = get_tax_value(tax_ids)

        return Product(
            Id=safe_int(data.get("Id"), 0) or 0,
            Code=data.get("Code"),
            Name=data.get("Name"),
            FullName=data.get("FullName"),
            CategoryId=safe_int(data.get("CategoryId")),
            CategoryName=data.get("CategoryName"),
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
            TaxIds=tax_ids,
            Tax=tax_value,
        )