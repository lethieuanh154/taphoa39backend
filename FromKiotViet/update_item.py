import json
import requests
from Utility.get_env import LatestBranchId, retailer
from FromKiotViet.get_authorization import auth_token

# URL API for categories
url = "https://api-man1.kiotviet.vn/api/products/photo"

Name= "Tương ớt Chinsu 5kg"
Code= "8936221042975"
Description= ""
BasePrice= 150000
Cost= 0
OnHand= 1
CompareOnHand= 10  # need
CompareCost= 10 # need
CompareBasePrice= 150000
CompareCode= "8936221042975"
CompareName= "Tương ớt Chinsu 5kg"

payload = {'Product': f'{{"Id":38080826,"ProductType":2,"CategoryId":1436920,"CategoryName":"","isActive":true,"HasVariants":false,"VariantCount":1,"AllowsSale":true,"isDeleted":false,"Name":"{Name}","FullName":"Tương ớt Chinsu 5kg (chai)","Code":"{Code}","Description":"{Description}","BasePrice":{BasePrice},"Cost":{Cost},"LatestPurchasePrice":0,"OnHand":{OnHand},"OnOrder":0,"OnHandCompareMin":0,"OnHandCompareMax":0,"CompareOnHand":{CompareOnHand},"CompareCost":{CompareCost},"CompareBasePrice":{CompareBasePrice},"CompareCode":"{CompareCode}","CompareName":"{CompareName}","CompareUnit":"chai","CompareProductShelves":[],"CompareMinQuantity":0,"CompareMaxQuantity":999999999,"CompareCategoryId":1436920,"CompareDescription":"","CompareOrderTemplate":"","Reserved":0,"ActualReserved":0,"MinQuantity":0,"MaxQuantity":999999999,"CustomId":0,"CustomValue":0,"Unit":"chai","ConversionValue":1,"OrderTemplate":"","ProductAttributes":[],"ProductShelves":[],"ProductUnits":[],"IsLotSerialControl":false,"IsRewardPoint":true,"RewardPoint":0,"CompareRewardPoint":0,"IsBatchExpireControl":false,"FormulaCount":0,"TradeMarkName":"","Type4":2,"PageSize":0,"HasVariantProduct":false,"Type1":1,"MasterCode":"SPC004628","OriginalBasePrice":150000,"GenuineGuarantees":[],"StoreGuarantees":[],"RepeatGuarantee":{{"Uuid":-1,"TimeType":2,"ProductId":38080826,"RetailerId":500111210,"Description":"Toàn bộ sản phẩm"}},"GuaranteesToDelete":[],"ProductFormulas":[],"ProductFormulasOld":[],"ProductImages":[],"ListPriceBookDetail":[{{"__type":"<>f__AnonymousType324`10[[System.Int32, mscorlib],[System.Int64, mscorlib],[System.String, mscorlib],[System.Nullable`1[[System.Int32, mscorlib]], mscorlib],[System.Boolean, mscorlib],[System.Collections.Generic.List`1[[System.Object, mscorlib]], mscorlib],[System.Object, mscorlib],[System.Object, mscorlib],[System.Object, mscorlib],[System.Object, mscorlib]], KiotViet.Web.Api","Id":0,"PriceBookId":813695,"PriceBookName":"Bảng giá sỉ","ProductId":38080826,"IsAuto":false,"ListDependencies":[],"Price":-1}}]}}',
'BranchForProductCostss': '[{"Id":878979,"Name":"Chi nhánh trung tâm"}]',
'ListUnitPriceBookDetail': '[]'}

headers = {
  'Authorization': auth_token,
  'retailer': retailer,
  'branchid': LatestBranchId
}

def set_data():
    try:
        response = requests.post(url, headers=headers, data=payload )
        response.raise_for_status()  # Raise an exception for HTTP errors
        print("Response:", response.json())
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")

set_data()