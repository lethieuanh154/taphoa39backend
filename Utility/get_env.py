import os
from dotenv import load_dotenv

load_dotenv()

UserName = os.getenv('User')
LatestBranchId = os.getenv('LatestBranchId')
Password = os.getenv('Password')
retailer = os.getenv('retailer')
