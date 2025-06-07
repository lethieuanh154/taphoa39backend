from FromKiotViet.get_all_product_by_category import get_items_category
from FromKiotViet.get_category import get_category
from FromKiotViet.get_one_product import get_item
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from FromKiotViet.get_authorization import auth_token
from Utility.get_env import LatestBranchId, retailer


def get_all():
    url = f"https://api-kvsync1.kiotviet.vn/api/resource/fetch?clientId=WebAppWN-3e31c9b0-cd4a-43e6-be25-a5d1330372fd-500111210-878979&resourceName=Products&pageSize=10000"

    # Headers
    header = {
        "Authorization": auth_token,
        "retailer": retailer,
        "branchid": LatestBranchId
    }

    response = requests.get(url, headers=header)
    if response.status_code == 200:
        data = response.json()
        raw_items = data.get('Data', [])

        # Lọc bỏ các object có isDeleted = true
        filtered_items = [item for item in raw_items if not item.get('isDeleted', False)]

        return filtered_items
    else:
        return None
    # # … lấy category_list, get_items_category như cũ
    # all_items = []
    # category_id_list = get_category()
    # for cat in category_id_list:
    #     all_items.extend(get_items_category(cat["Id"]))

    # # Bây giờ, thay vì loop tuần tự, ta parallel:
    # entire_product = []
    # # Ta lấy danh sách tên sản phẩm (hoặc mã) để truyền vào get_item
    # names_list = [p["Name"] for p in all_items]

    # # Tạo ThreadPoolExecutor
    # max_workers = 20  # Tùy chỉnh, thường từ 5–20
    # with ThreadPoolExecutor(max_workers=max_workers) as executor:
    #     future_to_name = {executor.submit(get_item, name): name for name in names_list}

    #     for future in as_completed(future_to_name):
    #         name = future_to_name[future]
    #         try:
    #             data = future.result()
    #             if data:
    #                 # Nếu API suggest trả về một list, ta extend luôn
    #                 entire_product.extend(data)
    #         except Exception as e:
    #             # Bắt & ghi log error nhưng không dừng toàn bộ
    #             print(f"Error fetching suggest for {name}: {e}")

    # return entire_product
