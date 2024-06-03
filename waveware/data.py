import logging
import diskcache
import logging
import pathlib
import os

import pytz
import datetime
import pigpio
import sys
from expiringdict import ExpiringDict
from math import cos,sin

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data")

#File Path
path = pathlib.Path(__file__)
fdir = path.parent
disk_cache = diskcache.Cache(os.path.join(fdir,'data_cache'))

#polling & data range
poll_rate = float(os.environ.get('WAVEWARE_POLL_RATE',1.0 / 25))
poll_temp = float(os.environ.get('WAVEWARE_POLL_TIME',60))
window = float(os.environ.get('WAVEWARE_WINDOW',30))

memcache = ExpiringDict(max_len=window * 2 / poll_rate, max_age_seconds=window * 2)