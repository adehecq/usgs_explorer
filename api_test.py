import os
from usgsxplore.api import API


api = API(os.getenv("USGS_USERNAME"), token=os.getenv("USGS_TOKEN"))
#api.download("declassii", ["DZB1216-500525L001001", "DZB1216-500525L006001","DZB1216-500523L001001"])
api.download("landsat_tm_c2_l1", ["LT50380372012126EDC00", "LT50310332012125EDC00"])
api.logout()