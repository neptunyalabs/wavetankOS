# from piplates import DACC

import datetime
import asyncio

import aiobotocore
from aiobotocore.session import get_session

from aiohttp import web
from dash.dependencies import Input, Output,State
import sys,os

import json
import numpy as np
import pandas as pd
import pathlib
import logging
import requests

from waveware.config import *
from waveware.hardware import LABEL_DEFAULT

#### Dashboard data server
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dash")

def make_app(hw):
    app = web.Application()
    #function making function (should scope internally to lambda inst)
    hwfi = lambda f,*a,**kw: lambda req: f(req,*a,**kw)
    log.info(f'creating web server')
    app.add_routes(
        [
            web.get("/", hwfi(check,hw)), #works
            
            #the data broker to front end
            web.get("/getdata", hwfi(get_data,hw)), #works
            web.get("/getcurrent", hwfi(get_current,hw)), #works

            web.post("/set_const", hwfi(set_const,hw)),
            web.post("/log_note", hwfi(add_note,hw)),

            #start recording
            web.get("/turn_on", hwfi(turn_daq_on,hw)), #works
            web.get("/turn_off", hwfi(turn_daq_off,hw)), #works

            #TODO: add API functionality
            #process commands
            web.get('/hw/zero_pos',hwfi(zero_positions,hw)), #works
            web.get('/hw/mpu_calibrate',hwfi(mpu_calibrate,hw)),
            
            #TODO: EN pin High, speed ctl on
            web.get('/control/enable',hwfi(start_control,hw)),  #works
            #TODO: EN pin High, speed ctl off
            web.get('/control/disable',hwfi(stop_control,hw)), #works
            web.get('/control/stop',hwfi(stop_control,hw)), #works
            #web.get('/control/calibrate',hwfi(control_cal,hw)),
            #complex control inputs (post/json)
            web.post('/control/set_inputs',hwfi(set_inputs,hw)),
        ]
    )
    log.info(f'creating web server')
    return web.AppRunner(app)
    
#Data Quality Methods
async def check(request,hw):
    name = request.match_info.get("name", "Anonymous")
    text = f"All Systems Normal {name}| Items: N={len(hw.cache)}"
    return web.Response(text=text)

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
    
    output = await hw._zero_task
    
    resp = web.Response(text='Positions zeroed: {output}')
    return resp

#CONTROL
async def run_wave(request,hw):
    assert not hw.control.started
    hw.control.set_mode('wave')
    resp = web.Response(text='Wave Started')
    return resp

async def set_inputs(request,hw):
    pass #TODO

async def set_const(request,hw):
    pass #TODO

async def stop_control(request,hw):
    assert not hw.control.stopped
    await hw.control.stop_control()
    return web.Response(text='stopped')

async def start_control(request,hw):
    assert hw.control.stopped
    await hw.control.start_control()
    return web.Response(text='started')


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
async def push_data(hw):
    """Periodically looks for new data to upload 1/3 of window time"""
    while True:

        try:

            if hw.active and hw.unprocessed:

                data_rows = {}
                data_set = {
                    "data": data_rows,
                    "num": len(hw.unprocessed),
                    "test": hw.labels['title'],
                }
                #add items from deque
                while hw.unprocessed:
                    row_ts = hw.unprocessed.pop()
                    if row_ts in hw.cache:
                        row = hw.cache[row_ts]
                        if row:
                            data_rows[row_ts] = row

                # Finally try writing the data
                if data_rows:
                    log.info(f"writing to S3")
                    await write_s3(hw,data_set)
                else:
                    log.info(f"no data, skpping s3 write")
                # Finally Wait Some Time
                await asyncio.sleep(hw.window / 3.0)

            elif hw.active:
                log.info(f"no data")
                await asyncio.sleep(hw.window / 3.0)
            else:
                log.info(f"not active")
                await asyncio.sleep(hw.window / 3.0)

        except Exception as e:
            log.error(str(e), exc_info=1)

async def write_s3(hw,data: dict,title=None):
    """writes the dictionary to the bucket
    :param data: a dictionary to write as json
    :param : default='data', use to log actions ect
    """
    from waveware.config import aws_profile,bucket,folder

    if ON_RASPI or folder=='TEST':
        up_time = datetime.datetime.now(tz=datetime.timezone.utc)
        data["upload_time"] = str(up_time)
        date = up_time.date()
        time = f"{up_time.hour}-{up_time.minute}-{up_time.second}"
        if title is not None and title:
            key = f"{folder}/{hw.labels['title']}/{date}/{title}_{time}.json"
        else:
            #data
            key = f"{folder}/{hw.labels['title']}/{date}/data_{time}.json"

        session = aiobotocore.session.AioSession(profile=aws_profile)
        async with session.create_client('s3',region_name='us-east-1') as client:

            resp = await client.put_object(
                Bucket=bucket, Key=key, Body=json.dumps(data)
            )
            log.info(f"success writing {key}")
            log.debug(f"got s3 resp: {resp}")
    else:
        log.info(f"mock writing s3...: {aws_profile}|{title}|{len(data)}")