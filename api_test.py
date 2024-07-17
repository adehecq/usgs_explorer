import os
from usgsxplore.api import API
from usgsxplore.scenes_downloader import ScenesDownloader

api = API(os.getenv("USGSXPLORE_USERNAME"), token=os.getenv("USGSXPLORE_TOKEN"))
#api.download("declassii", ["DZB1216-500525L001001", "DZB1216-500525L006001","DZB1216-500523L001001","IDJFZKZKFK"], pbar_type=2)
#api.download("landsat_tm_c2_l1", ["LT50380372012126EDC00", "LT50310332012125EDC00"], pbar_type=2)
api.download("corona2", ["DS1117-2086DA003", "DS1117-2086DA004"], pbar_type=2)
api.logout()