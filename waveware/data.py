import logging
import boto3
import diskcache
import logging
import json
import pathlib
import os

import pandas as pd
import pytz
import datetime
import numpy as np
import pigpio

try:
    import RPi.GPIO as gpio
    ON_RASPI = True
    pigpio.exceptions = True #TODO: make false
except:
    ON_RASPI = False
    pigpio.exceptions = True

pst = pytz.timezone('US/Pacific')
utc = pytz.utc

def to_test_time(timestamp):
    dt = datetime.datetime.fromtimestamp(timestamp,tz=pytz.UTC)
    return dt.astimezone(pst)

def to_date(timestamp):
    return to_test_time(timestamp).date()

aws_profile = os.environ.get('AWS_PROFILE','wavetank')
bucket = os.environ.get('WAVEWARE_S3_BUCKET',"nept-wavetank-data")
folder = os.environ.get('WAVEWARE_FLDR_NAME',"V1")
PLOT_STREAM = (os.environ.get('PLOT_STREAM','false')=='true')

path = pathlib.Path(__file__)
fdir = path.parent
cache = diskcache.Cache(os.path.join(fdir,'data_cache'))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data")




LABEL_DEFAULT = {
    "title": "test",
    "hs_in": 0/1000., #m
    "ts-in": 10.0, #s
    "trq_pct": 0,
    "kp-gain":0,
    "ki-gain":0,
    "kd-gain":0,

}