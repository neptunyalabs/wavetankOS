import logging
import boto3
import diskcache
import logging
import json
import pathlib
import os

from matplotlib.pylab import *
import pandas as pd
import pytz
import datetime
import seaborn as sns
import numpy as np

pst = pytz.timezone('US/Pacific')
utc = pytz.utc

def to_test_time(timestamp):
    dt = datetime.datetime.fromtimestamp(timestamp,tz=pytz.UTC)
    return dt.astimezone(pst)

def to_date(timestamp):
    return to_test_time(timestamp).date()

bucket = "nept-wavetank-data"
folder = "V1"

path = pathlib.Path(__file__)
fdir = path.parent
cache = diskcache.Cache(os.path.join(fdir,'data_cache'))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data")

#TODO: deploy account for wave tank script
aws_profile = os.environ.get('AWS_PROFILE','wavetank')