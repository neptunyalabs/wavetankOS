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

from waveware.config import *

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data")

#File Path
path = pathlib.Path(__file__)
fdir = path.parent
disk_cache = diskcache.Cache(os.path.join(fdir,'data_cache','dl_cache.db'))

memcache = ExpiringDict(max_len=window * 2 / poll_rate, max_age_seconds=window* 2)