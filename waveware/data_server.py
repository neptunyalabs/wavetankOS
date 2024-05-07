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


#### Dashboard data server
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dash")

def make_web_app(hw):
    app = web.Application()
    #function making function (should scope internally to lambda inst)
    hwfi = lambda f,*a,**kw: lambda req: f(req,*a,**kw)
    app.add_routes(
        [
            web.get("/", hwfi(handle,hw)),
            web.get("/turn_on", hwfi(turn_daq_on,hw)),
            web.get("/turn_off", hwfi(turn_daq_off,hw)),
            
            web.get("/getdata", hwfi(get_data,hw)),
            web.get("/getcurrent", hwfi(get_current,hw)),

            web.get("/reset_labels",hwfi(reset_labels,hw)),
            web.get("/set_labels",hwfi(set_labels,hw)),
        ]
    )
    return web.AppRunner(app)
    

# WEB APPLICATION
async def handle(request,hw):
    name = request.match_info.get("name", "Anonymous")
    text = f"All Systems Normal {name}| Items: N={len(hw.cache)}"
    return web.Response(text=text)


async def turn_daq_on(request,hw):
    log.info("turning on")
    hw.active = True
    return web.Response(text="success")


async def turn_daq_off(request,hw):
    log.info("turning off")
    hw.active = False
    return web.Response(text="success")

async def get_after(request,hw):
    """returns the data after the `after` param if it exists, otherwise return everything"""
    log.info("get data")
    after = request.query.get("after", None)
    data = [v for k, v in hw.cache.items() if after is None or k > after]
    data_set = {
        "data": data,
        "num": len(data),
        "test": hw.title,
    }
    return web.Response(body=json.dumps(data_set))


async def reset_labels(request,hw):
    log.info("resetting labels")
    hw.update_labels(**LABEL_DEFAULT)
    return web.Response(body=json.dumps(hw.labels))


async def set_labels(request,hw):
    
    #convert to subset
    params = {k:int(v) if 'title' not in k else v for k,v in request.query.copy().items() if k in hw.labels and v}
    log.info(f"setting labels: {params}")
    hw.update_labels(**params)

    return web.Response(body=json.dumps(hw.labels))

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