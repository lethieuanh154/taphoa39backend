from dataclasses import dataclass
from datetime import datetime
from typing import List, Any

@dataclass
class Product:
    Id: int
    Code: str
    Name: str
    FullName: str
    CategoryId: int
    isActive: bool
    isDeleted: bool
    Cost: float
    BasePrice: float
    OnHand: float
    Unit: str
    MasterUnitId: int
    MasterProductId: int
    ConversionValue: float
    Description: str
    IsRewardPoint: bool
    ModifiedDate: datetime
    Image: str
    CreatedDate: datetime
    ProductAttributes: List[Any]
    NormalizedName: str
    NormalizedCode: str
    OrderTemplate: str
    @staticmethod
    def from_dict(data: dict) -> "Product":
       return Product(
           Id=data["Id"],
           Code=data["Code"],
           Name=data["Name"],
           FullName=data["FullName"],
           CategoryId=data["CategoryId"],
           isActive=data["isActive"],
           isDeleted=data["isDeleted"],
           Cost=float(data["Cost"]),
           BasePrice=float(data["BasePrice"]),
           OnHand=float(data["OnHand"]),
           Unit=data["Unit"],
           MasterUnitId=data["MasterUnitId"],
           MasterProductId=data["MasterProductId"],
           ConversionValue=float(data["ConversionValue"]),
           Description=data["Description"],
           IsRewardPoint=data["IsRewardPoint"],
           ModifiedDate=datetime.fromisoformat(data["ModifiedDate"]),
           Image=data["Image"],
           CreatedDate=datetime.fromisoformat(data["CreatedDate"]),
           ProductAttributes=data.get("ProductAttributes", []),
           NormalizedName=data["NormalizedName"],
           NormalizedCode=data["NormalizedCode"],
           OrderTemplate=data["OrderTemplate"],
       )