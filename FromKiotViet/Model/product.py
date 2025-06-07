from typing import List, Optional


class ListProductUnit:
    def __init__(self, Code, Conversion, Id, MasterUnitId, Unit):
        self.Code = Code
        self.Conversion = Conversion
        self.Id = Id
        self.MasterUnitId = MasterUnitId
        self.Unit = Unit

    @staticmethod
    def from_dict(data: dict):
        return ListProductUnit(
            Code=data.get("Code"),
            Conversion=data.get("Conversion"),
            Id=data.get("Id"),
            MasterUnitId=data.get("MasterUnitId"),
            Unit=data.get("Unit")
        )


class Product:
    def __init__(
        self,
        Image: str,
        Code: str,
        FullName: str,
        Name: str,
        AverageCheckPoint: bool,
        BasePrice: float,
        FinalBasePrice: float,
        OnHand: float,
        Cost: float,
        PackCost: float,
        OriginalBoxPrice: float,
        Description: str,
        Unit: str,
        PackingSpec: float,
        UnitSpec: float,
        Retail: float,
        Box: float,
        Discount: float,
        Discount2: float,
        TotalPrice: float,
        ListProduct: List[ListProductUnit],
        ConversionValue: float,
        GroupName: str,
        Edited: bool,
        Master: bool,
        Id: int,
        discountBasePrice: Optional[float] = None
    ):
        self.Image = Image
        self.Code = Code
        self.FullName = FullName
        self.Name = Name
        self.AverageCheckPoint = AverageCheckPoint
        self.BasePrice = BasePrice
        self.FinalBasePrice = FinalBasePrice
        self.OnHand = OnHand
        self.Cost = Cost
        self.PackCost = PackCost
        self.OriginalBoxPrice = OriginalBoxPrice
        self.Description = Description
        self.Unit = Unit
        self.PackingSpec = PackingSpec
        self.UnitSpec = UnitSpec
        self.Retail = Retail
        self.Box = Box
        self.Discount = Discount
        self.Discount2 = Discount2
        self.TotalPrice = TotalPrice
        self.ListProduct = ListProduct
        self.ConversionValue = ConversionValue
        self.GroupName = GroupName
        self.Edited = Edited
        self.Master = Master
        self.Id = Id
        self.discountBasePrice = discountBasePrice

    @staticmethod
    def from_dict(data: dict):
        return Product(
            Image=data.get("Image", ""),
            Code=data.get("Code", ""),
            FullName=data.get("FullName", ""),
            Name=data.get("Name", ""),
            AverageCheckPoint=data.get("AverageCheckPoint", False),
            BasePrice=float(data.get("BasePrice", 0)),
            FinalBasePrice=float(data.get("FinalBasePrice", 0)),
            OnHand=float(data.get("OnHand", 0)),
            Cost=float(data.get("Cost", 0)),
            PackCost=float(data.get("PackCost", 0)),
            OriginalBoxPrice=float(data.get("OriginalBoxPrice", 0)),
            Description=data.get("Description", ""),
            Unit=data.get("Unit", ""),
            PackingSpec=float(data.get("PackingSpec", 0)),
            UnitSpec=float(data.get("UnitSpec", 0)),
            Retail=float(data.get("Retail", 0)),
            Box=float(data.get("Box", 0)),
            Discount=float(data.get("Discount", 0)),
            Discount2=float(data.get("Discount2", 0)),
            TotalPrice=float(data.get("TotalPrice", 0)),
            ListProduct=[
                ListProductUnit.from_dict(pu) for pu in data.get("ListProduct", [])
            ],
            ConversionValue=float(data.get("ConversionValue", 0)),
            GroupName=data.get("GroupName", ""),
            Edited=bool(data.get("Edited", False)),
            Master=bool(data.get("Master", False)),
            Id=int(data.get("Id", 0)),
            discountBasePrice=float(data["discountBasePrice"]) if "discountBasePrice" in data else None
        )
