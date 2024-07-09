import os
from usgsxplore.api import API


api = API(os.getenv("USGS_USERNAME"), token=os.getenv("USGS_TOKEN"))
scenes = api.search("landsat_tm_c2_l1", bbox=(5.7074, 45.1611, 5.7653, 45.2065), date_interval=("2010-01-01","2019-12-31"))
print(len(scenes))
api.logout()