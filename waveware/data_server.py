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
import traceback
import signal
from concurrent.futures import ProcessPoolExecutor

from waveware.config import *
from waveware.data import *
from waveware.hardware import LABEL_DEFAULT

#### Dashboard data server
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dash")

def make_app(hw):
    app = web.Application()
    #function making function (should scope internally to lambda inst)
    hwfi = lambda f,*a,**kw: lambda req: f(req,*a,**kw)
    #log.info(f'creating web server')
    app.add_routes(
        [
            web.get("/", hwfi(check,hw)), #works
            
            #the data broker to front end
            web.get("/getdata", hwfi(get_data,hw)), #works
            web.get("/getcurrent", hwfi(get_current,hw)), #works
            web.get("/run_summary", hwfi(run_summary,hw)), #works
            web.post("/save_table_config", hwfi(save_config,hw)), #works

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
            web.post('/control/set',hwfi(set_control_info,hw)),
            web.get('/control/get',hwfi(get_control_info,hw)),
            web.get('/control/test_pins',hwfi(test_pins,hw)),
            web.get('/control/status',hwfi(ctrl_status,hw)),
        ]
    )
    log.info(f'creating web server')

    dash_log = logging.getLogger('aiohttp.access')
    dash_log.setLevel(40)

    return web.AppRunner(app)
    
#Data Quality Methods
async def check(request,hw):
    name = request.match_info.get("name", "Anonymous")
    text = f"All Systems Normal {name}| Items: N={len(hw.cache)}"
    return web.Response(text=text)

async def mpu_calibrate(request,hw):
    loop = asyncio.get_event_loop()

    if not hw.active:
        raise Exception(f'DAQ not on')

    if hw.active_mpu_cal:
        raise Exception(f'active calibration process!')
    
    hw._cal_task = loop.create_task(hw.mpu_calibration_process())
    resp = web.Response(text='MPU Calibration begun, every 10 seconds place item in new orientation in 3 coord space, ensuring alternate faces')
    await hw._cal_task

    return resp

async def zero_positions(request,hw):
    loop = asyncio.get_event_loop()
    hw._zero_task = loop.create_task(hw.mark_zero())
    
    if not hw.active:
        raise Exception(f'DAQ not on')

    output = await hw._zero_task
    await write_s3(hw.labels['title'].replace(' ','-'),output,'zero_result')    
    output = json.dumps(output)
    resp = web.Response(text=f'Positions zeroed: {output}')
    return resp

#Start / Stop
async def stop_control(request,hw):
    assert not hw.control.stopped
    await hw.control.stop_control()
    return web.Response(text='stopped')

async def start_control(request,hw):
    assert hw.control.stopped
    await hw._start_sensors()    
    await hw.control.start_control()
    return web.Response(text='started')


#DATA LOGGING
async def ctrl_status(request,hw):
    out = hw.control_status
    return web.Response(body=json.dumps(out))

#TODO: check trigger / restart dynamics for these items
async def turn_daq_on(request,hw):
    '''switch puts data in buffer'''
    log.info("turning on")
    await hw._start_sensors()
    hw.active = True
    return web.Response(text="success")


async def turn_daq_off(request,hw):
    log.info("turning off")
    hw.active = False
    return web.Response(text="success")

#DATA ACCESS
async def get_current(request,hw):
    if hw.last_time and hw.last_time in hw.cache:
        data = hw.cache[hw.last_time]
        #if DEBUG: 
        #    log.info(f'current {data}')
        if data:
            return web.Response(body=json.dumps(data))
    return web.Response(body='no data!',status=420)

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
            if subset:
                return web.Response(body=json.dumps(subset))
        else:
            return web.Response(body=json.dumps(hw.cache)) 

    return web.Response(body='no data!',status=420)

#DATA LABELS & LOGGING
async def save_config(request,hw):
    try:
        params =  await request.json()
        hw.set_parameters(**params)
        with open(config_file,'w') as fp:
            fp.write(json.dumps(params))
        
        return web.Response(body=f'success')
    
    except Exception as e:
        return web.Response(body=f'error in setting: {e}',status=400)

async def run_summary(request,hw):
    return web.Response(body=json.dumps(hw.run_summary))

async def set_control_info(request,hw):
    try:
        #params = {k:float(v.strip()) if k.replace('.','').isalpha() else v for k,v in request.query.copy().items() }
        params =  await request.json()
        log.info(f'got {params} from {request}')
        s_data = {'data':params,'asOf':str(datetime.datetime.now())}

        #TODO: enable
        loop = asyncio.get_running_loop()
        await write_s3(hw.labels['title'].replace(' ','-'),s_data,'set_input')

        out = hw.set_parameters(**params)
        if out is True:
            o = web.Response(body='success')
        else:
            o = web.Response(body=f'validation error: {out}',status=400)

        loop.call_soon(write_results,hw)

        return o

    except Exception as e:
        log.info(f'issue in remote set control: {e}')
        traceback.print_tb(e.__traceback__)
        return web.Response(status=500,body=str(e))
    
async def write_results(hw):
        results = hw.run_summary
        s_data = {'data':results,'asOf':str(datetime.datetime.now())}
        await write_s3('summary',s_data,'session_results')

async def get_control_info(request,hw):
    return web.Response(body=json.dumps(hw.parameters()))


async def add_note(request,hw):
    #convert to subset
    dt = datetime.datetime.now()
    bdy = await request.json()

    await write_s3(hw.labels['title'].replace(' ','-'),bdy,title='test_note')

    return web.Response(body=f'Added Note: {bdy}')


async def test_pins(request,hw):
    
    pi = hw.pi
    out = {}

    #control
    obj = hw.control
    fails = False
    
    #enc_pins = [v for vs in hw.encoder_pins for v in vs]
    #+hw.echo_pins+enc_pins#FIXME: this destroys sensor cbs ect, only output for now
    save_last = hw.last

    for pin in [obj._motor_en_pin,obj._dir_pin,obj._step_pin,obj._tpwm_pin,obj._vpwm_pin,hw._echo_trig_pin]:
        try:
            cur_mode = await pi.get_mode(pin)
            await pi.write(pin,0)
            val1 = await pi.read(pin)
            await pi.write(pin,1)
            val2 = await pi.read(pin)
            await pi.write(pin,0)
            val3 = await pi.read(pin)            
            await pi.set_mode(pin,cur_mode)
            works = val1==0 and val2==1 and val3==0
            if works != True:
                log.info(f'issue on pin: {pin}')
            out[pin] = (works,'W' if cur_mode==1 else 'R',val1,val2,val3)
            #TODO: assert ok!
        except Exception as e:
            fails = True
            log.info(f'issue on pin: {pin}| {e}')
    
    hw.last = save_last

    if any(v[0]==False for pin,v in out.items()):
        fails = True

    return web.Response(body=json.dumps(out),status=200 if not fails else 411)









some_flag = False


#Data Recording
async def push_data(hw):
    """Periodically looks for new data to upload 1/3 of window time"""
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(1) as pool:
        hw._pool = pool
        while True:
            global some_flag
            if some_flag:
                pool.shutdown(wait=True)
                sys.exit()
            try:

                if hw.active and hw.unprocessed:

                    data_rows = {}
                    data_set = {
                        "data": data_rows,
                        "num": len(hw.unprocessed),
                        "test": hw.title,
                    }
                    #add items from deque
                    while hw.unprocessed:
                        row_ts = hw.unprocessed.pop()
                        if row_ts in hw.cache:
                            row = hw.cache[row_ts]
                            if row:
                                data_rows[row_ts] = row

                    # Finally try writing the data (data rows already set above in data_set)
                    if data_rows and LOG_TO_S3:
                        if DEBUG: log.info(f"writing to S3")
                        
                        out = await asyncio.gather(
                            loop.run_in_executor(pool,sync_write_s3, hw.title.replace(' ','-'),data_set)
                            )

                        if DEBUG: log.info(f"wrote to S3, got: {out}")

                    else:
                        log.info(f"no data, skpping s3 write")
                    # Finally Wait Some Time
                    await asyncio.sleep(hw.window / 10.0)

                elif hw.active:
                    log.info(f"no data")
                    await asyncio.sleep(hw.window / 10.0)
                else:
                    log.info(f"not active")
                    await asyncio.sleep(hw.window / 10.0)

            except Exception as e:
                log.error(str(e), exc_info=1)

async def write_s3(test,data: dict,title=None):
    """writes the dictionary to the bucket
    :param data: a dictionary to write as json
    :param : default='data', use to log actions ect
    """
    from waveware.config import aws_profile,bucket,folder

    if ON_RASPI or folder.upper()=='TEST':
        up_time = datetime.datetime.now(tz=datetime.timezone.utc)
        data["upload_time"] = str(up_time)
        date = up_time.date()
        time = f"{up_time.hour}-{up_time.minute}-{up_time.second}"
        
        #SET THE PATH
        if title is not None and title:
            key = f"{folder}/{test}/{date}/{title}_{time}.json"
        else:
            #data
            key = f"{folder}/{test}/{date}/data_{time}.json"

        session = aiobotocore.session.AioSession(profile=aws_profile)
        async with session.create_client('s3',region_name='us-east-1') as client:

            resp = await client.put_object(
                Bucket=bucket, Key=key, Body=json.dumps(data)
            )
            log.info(f"success writing {key}")
            log.debug(f"got s3 resp: {resp}")
            return True
        
    else:
        log.info(f"mock writing s3...: {aws_profile}|{title}|{len(data)}")

        return True

def sync_write_s3(test,data: dict,title=None):
    """writes the dictionary to the bucket
    :param data: a dictionary to write as json
    :param : default='data', use to log actions ect
    """
    import botocore
    from waveware.config import aws_profile,bucket,folder

    if ON_RASPI or folder.upper()=='TEST':
        up_time = datetime.datetime.now(tz=datetime.timezone.utc)
        data["upload_time"] = str(up_time)
        date = up_time.date()
        time = f"{up_time.hour}-{up_time.minute}-{up_time.second}"
        
        #SET THE PATH
        if title is not None and title:
            key = f"{folder}/{test}/{date}/{title}_{time}.json"
        else:
            #data
            key = f"{folder}/{test}/{date}/data_{time}.json"

        session = botocore.session.Session(profile=aws_profile)
        client = session.create_client('s3',region_name='us-east-1')
        resp = client.put_object(
            Bucket=bucket, Key=key, Body=json.dumps(data)
        )
        log.info(f"success writing {key}")
        #log.debug(f"got s3 resp: {resp}")
        return True
        
    else:
        log.info(f"mock writing s3...: {aws_profile}|{title}|{len(data)}")

        return True


def print_some_num():
    print("From worker :{}".format(os.getpid()))

def handler(arg1, arg2):
    global some_flag
    print("Got interrupt")
    some_flag = True
    print("Shutdown")

signal.signal(signal.SIGTERM,handler)
signal.signal(signal.SIGINT,handler)