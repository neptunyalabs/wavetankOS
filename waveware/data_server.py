# from piplates import DACC

import datetime
import asyncio

from aiohttp import web
from dash.dependencies import Input, Output,State
import sys,os

import json
import numpy as np
import pandas as pd
import pathlib
import logging
import requests

from waveware.data import *
from waveware.hardware import LABEL_DEFAULT

#### Dashboard data server
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dash")

def make_web_app(hw):
    app = web.Application()
    #function making function (should scope internally to lambda inst)
    hwfi = lambda f,*a,**kw: lambda req: f(req,*a,**kw)
    app.add_routes(
        [
            web.get("/", hwfi(check,hw)),
            
            #the data broker to front end
            web.get("/getdata", hwfi(get_data,hw)),
            web.get("/getcurrent", hwfi(get_current,hw)),

            web.post("/set_meta", hwfi(set_labels,hw)),
            web.post("/add_note", hwfi(add_note,hw)),

            #start recording
            web.get("/turn_on", hwfi(turn_daq_on,hw)),
            web.get("/turn_off", hwfi(turn_daq_off,hw)),

            #TODO: add API functionality
            #boolean commands
            web.get('/hw/zero_pos',hwfi(zero_control,hw))
            web.get('/hw/mpu_calibrate',hwfi(mpu_calibrate,hw))
            
            web.get('/control/run',hwfi(start_control,hw))
            web.get('/control/stop',hwfi(stop_control,hw))
            web.get('/control/calibrate',hwfi(control_cal,hw))
            #complex control inputs (post/json)
            web.post('/control/set_wave',hwfi(set_wave,hw))
            web.post('/control/z_set',hwfi(set_z_pos,hw))
            web.post('/control/set_bounds',hwfi(set_z_bounds,hw))
            
        ]
    )
    return web.AppRunner(app)
    
#Data Quality Methods
async def mpu_calibrate(request,hw):
    loop = asyncio.get_event_loop()
    if hw.active_mpu_cal:
        raise Exception(f'active calibration process!')
    
    hw._cal_task = loop.create_task(hw.mpu_calibration_process())
    resp = web.Response(text='MPU Calibration begun, every 10 seconds place item in new orientation in 3 coord space, ensuring alternate faces')
    await hw._cal_task

    return resp

async def zero_positions(request,hw):
    loop = asyncio.get_event_loop()
    hw._zero_task = loop.create_task(hw.mark_zero())
    resp = web.Response(text='Positions zeroed')
    await hw._zero_task
    return resp

# WEB APPLICATION
async def check(request,hw):
    name = request.match_info.get("name", "Anonymous")
    text = f"All Systems Normal {name}| Items: N={len(hw.cache)}"
    return web.Response(text=text)


#DATA LOGGING
async def turn_daq_on(request,hw):
    log.info("turning on")
    hw.active = True
    return web.Response(text="success")


async def turn_daq_off(request,hw):
    log.info("turning off")
    hw.active = False
    return web.Response(text="success")

#DATA ACCESS
async def get_current(request,hw):
    if hw.last_time and hw.last_time in hw.cache:
        return web.Response(body=json.dumps(hw.cache[hw.last_time]))
    return web.Response(text='no data, turn on DAC')

async def get_data(request,hw):
    """
    returns the cache data in format ts:data
    :param after: a timestamp, which is used to filter older values
    """
    if hw.cache:
        after = request.query.get("after",None)
        if after is not None:
            after = float(after)
            subset = {k:v for k,v in hw.cache.items() if k > after}
            return web.Response(body=json.dumps(subset))
        else:
            return web.Response(body=json.dumps(hw.cache)) 

    return web.Response(text='no data, turn on DAC')

#DATA LABELS & LOGGING
async def reset_labels(request,hw):
    log.info("resetting labels")
    hw.update_labels(**LABEL_DEFAULT)
    return web.Response(body=json.dumps(hw.labels))


async def set_meta(request,hw):
    
    #convert to subset
    params = {k:float(v.strip()) if k.isalpha() else v for k,v in request.query.copy().items() if k in hw.labels and v}
    log.info(f"setting labels: {params}")
    hw.update_labels(**params)

    return web.Response(body=json.dumps(hw.labels))


async def add_note(request,hw):
    
    #convert to subset
    requests.get('')
    dt = datetime.datetime.now()
    return web.Response(body='Added Note: {}')



#Data Recording
async def push_data(self):
    """Periodically looks for new data to upload 1/3 of window time"""
    while True:

        try:

            if self.active and self.unprocessed:

                data_rows = {}
                data_set = {
                    "data": data_rows,
                    "num": len(self.unprocessed),
                    "test": self.labels['title'],
                }
                #add items from deque
                while self.unprocessed:
                    row_ts = self.unprocessed.pop()
                    if row_ts in self.cache:
                        row = self.cache[row_ts]
                        if row:
                            data_rows[row_ts] = row

                # Finally try writing the data
                if data_rows:
                    log.info(f"writing to S3")
                    await self.write_s3(data_set)
                else:
                    log.info(f"no data, skpping s3 write")
                # Finally Wait Some Time
                await asyncio.sleep(self.window / 3.0)

            elif self.active:
                log.info(f"no data")
                await asyncio.sleep(self.window / 3.0)
            else:
                log.info(f"not active")
                await asyncio.sleep(self.window / 3.0)

        except Exception as e:
            log.error(str(e), exc_info=1)

async def write_s3(self,data: dict,title=None):
    """writes the dictionary to the bucket
    :param data: a dictionary to write as json
    :param : default='data', use to log actions ect
    """
    if ON_RASPI:
        up_time = datetime.datetime.now(tz=datetime.timezone.utc)
        data["upload_time"] = str(up_time)
        date = up_time.date()
        time = f"{up_time.hour}-{up_time.minute}-{up_time.second}"
        if title is not None and title:
            key = f"{folder}/{self.labels['title']}/{date}/{title}_{time}.json"
        else:
            #data
            key = f"{folder}/{self.labels['title']}/{date}/data_{time}.json"

        session = get_session()
        async with session.create_client('s3',region_name='us-east-1',config='wavetank') as client:

            resp = await client.put_object(
                Bucket=bucket, Key=key, Body=json.dumps(data)
            )
            log.info(f"success writing {key}")
            log.debug(f"got s3 resp: {resp}")
    else:
        log.info("mock writing s3...")