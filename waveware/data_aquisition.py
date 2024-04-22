"""Module to control and gather data from raspberry system"""

import asyncio
import aiohttp
from aiohttp import web
import aiobotocore
from aiobotocore.session import get_session


from collections import deque
from expiringdict import ExpiringDict

try:
    from piplates import DAQCplate
    ON_RASPI = True
except:
    ON_RASPI = False

import datetime
import time
import logging
import json
import os, sys
import tempfile
import pathlib
import random

# BUCKET CONFIG
# Permissons only for this bucket so not super dangerous
bucket = "nept-wavetank-data"
folder = "V1"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data")

# GLOBALS
POLL_RATE = 1.0 / 25.0
WINDOW = 60.0
WAIT_TIME = 1.0



# BOOLEAN
ACTIVE = False

TEST_NAME = "DEMOCAL"
LABEL_DEFAULT = {
    #TODO: define other label characteristics
    #test-name
    #Hs - significant wave height run
}

LABEL_SET = {**LABEL_DEFAULT}


# DATA STORAGE:
"""Store Data in key:value pandas format in queue format
all items will have a `timestamp` that is use to orchestrate using `after` search, items are moved from the buffer to the cache after they have been processed, with additional calculations.
"""
buffer = asyncio.Queue(1000)
unprocessed = deque([], maxlen=1000)
cache = ExpiringDict(max_len=WINDOW * 2 / POLL_RATE, max_age_seconds=WINDOW * 2)
LAST = None

#Store filtered values for low pass

#Sensor Constants

#PINS


START_TIME = time.time()
FAKE_INIT_TIME = 60.

is_fake_init = lambda: True if (time.time() - START_TIME) <  FAKE_INIT_TIME else False

# DATA FUNCTIONS:
async def poll_data():
    """polls the piplates for new data, and outputs the raw measured in real units"""
    alpha = 0.0
    inttime = 0
    while True:
        try:
            ts = time.time()
            if ACTIVE:
                BIAS = CONST['biases']
                if ON_RASPI:
                    ADVolts = DAQCplate.getADCall(PLATE_ADDR)

                    data = {
                        "p1t": calc_pressure(ADVolts[P1T])-BIAS['p1t'],
                        "p1s": calc_pressure(ADVolts[P1S])-BIAS['p1s'],
                        "p2t": calc_pressure(ADVolts[P2T])-BIAS['p2t'],
                        "p2s": calc_pressure(ADVolts[P2S])-BIAS['p2s'],
                        "timestamp": ts,
                        "test": LABEL_SET['title'],
                    }
                    if LABEL_SET['title'] == 'TEST':
                        if int(ts) != inttime:
                            #print(ADVolts,data)
                            pass
                        inttime = int(ts)
                else:
                    log.debug("mocking data..")
                    alpha = alpha * (1 - 0.1) + 0.1 * random.random()

                    rho = (1000 - 1.225) * (1 - alpha) + 1.225


                    
                    
                    if is_fake_init():
                        p1t = 100000*(1+0.05*(random.random()-0.5))
                        p1s = 100000*(1+0.05*(random.random()-0.5))
                        p2t = 100000*(1+0.05*(random.random()-0.5))
                        p2s = 100000*(1+0.05*(random.random()-0.5))

                    else:
                        v1 = 1 + random.random()
                        p1t = 100000 + 50000 * random.random()
                        p1s = p1t - 0.5 * rho * v1**2

                        v2 = v1 * 3
                        p2t = 100000 + 100000 * random.random()
                        p2s = p2t - 0.5 * rho * v2**2

                    
                    data = {
                        "p1t": p1t +FAKE_BIAS['p1t'] - BIAS['p1t'],
                        "p1s": p1s +FAKE_BIAS['p1s'] - BIAS['p1s'],
                        "p2t": p2t +FAKE_BIAS['p2t'] - BIAS['p2t'],
                        "p2s": p2s +FAKE_BIAS['p2s'] - BIAS['p2s'],
                        "timestamp": ts,
                        "test": LABEL_SET['title'],
                    }
                if data:
                    await buffer.put(data)
                await asyncio.sleep(POLL_RATE)
            else:
                await asyncio.sleep(1)

        except Exception as e:
            log.error(str(e), exc_info=1)


async def process_data():
    """a simple function to provide efficient calculation of variables"""
    while True:
        try:
            #swap refs with namespace fancyness
            last = locals().get('new',None)

            new = await buffer.get()

            # station 1
            pt, ps = new["p1t"], new["p1s"]
            new["p1t"] = pt
            new["p1s"] = ps

            a1,a2 = low_pass['p1t'], low_pass['p1s']
            if last and 'p1t_lp' in last:
                new["p1t_lp"] = pt * (1-a1) + last["p1t_lp"] * a1
                new["p1s_lp"] = ps * (1-a2) + last["p1s_lp"] * a2
            else:
                new["p1t_lp"] = pt 
                new["p1s_lp"] = ps

            ptlp = new['p1t_lp']
            pslp = new['p1s_lp']

            # alpha check
            a = current_data["alpha1"]
            if abs(ptlp - pslp) < 250:
                alp = 1.0
            else:
                alp = 0.0
            a = new["alpha1"] = a * (1.0 - lpa) + lpa * alp
            current_data["alpha1"] = a

            # Calculate density based on filtered alpha
            new["rho1"] = rho = (1000 - 1.225) * (1 - a) + 1.225

            new["V1"] = (ptlp - pslp) * 2.0 / rho

            # Station 2
            pt, ps = new["p2t"], new["p2s"]
            new["p2t"] = pt
            new["p2s"] = ps

            a1,a2 = low_pass['p2t'], low_pass['p2s']
            if last and 'p2t_lp' in last:
                new["p2t_lp"] = pt * (1-a1) + last["p2t_lp"] * a1
                new["p2s_lp"] = ps * (1-a2) + last["p2s_lp"] * a2
            else:
                new["p2t_lp"] = pt 
                new["p2s_lp"] = ps            

            ptlp = new['p2t_lp']
            pslp = new['p2s_lp']

            # alpha check
            a = current_data["alpha2"]
            if abs(ptlp - pslp) < 250:
                alp = 1.0
            else:
                alp = 0.0
            a = new["alpha2"] = a * (1.0 - lpa) + lpa * alp
            current_data["alpha2"] = a

            # Calculate density based on filtered alpha
            new["rho2"] = rho = (1000 - 1.225) * (1 - a) + 1.225

            new["V2"] = (ptlp - pslp) * 2.0 / rho

            ts = new["timestamp"]
            new.update(**LABEL_SET)

            global LAST
            LAST = ts
            cache[LAST] = new
            unprocessed.append(ts)

        except Exception as e:
            log.error(str(e), exc_info=1)


async def push_data():
    """Periodically looks for new data to upload 1/3 of window time"""
    while True:

        try:

            if ACTIVE and unprocessed:

                data_rows = {}
                data_set = {
                    "data": data_rows,
                    "num": len(unprocessed),
                    "test": LABEL_SET['title'],
                }
                while unprocessed:
                    row_ts = unprocessed.pop()
                    if row_ts in cache:
                        row = cache[row_ts]
                        if row:
                            data_rows[row_ts] = row

                # Finally try writing the data
                if data_rows:
                    log.info(f"writing to S3")
                    await write_s3(data_set)
                else:
                    log.info(f"no data, skpping s3 write")
                # Finally Wait Some Time
                await asyncio.sleep(WINDOW / 3.0)

            elif ACTIVE:
                log.info(f"no data")
                await asyncio.sleep(WINDOW / 3.0)
            else:
                log.info(f"not active")
                await asyncio.sleep(WINDOW / 3.0)

        except Exception as e:
            log.error(str(e), exc_info=1)


async def write_s3(data: dict,title=None):
    """writes the dictionary to the bucket
    :param data: a dictionary to write as json
    :param : default='data', use to log actions ect
    """
    if ON_RASPI:
        up_time = datetime.datetime.utcnow()
        data["upload_time"] = str(up_time)
        date = up_time.date()
        time = f"{up_time.hour}-{up_time.minute}-{up_time.second}"
        if title is not None and title:
            key = f"{folder}/{LABEL_SET['title']}/{date}/{title}_{time}.json"
        else:
            #data
            key = f"{folder}/{LABEL_SET['title']}/{date}/data_{time}.json"

        session = get_session()
        async with session.create_client(
            "s3",
            region_name="us-west-1",
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
        ) as client:

            resp = await client.put_object(
                Bucket=bucket, Key=key, Body=json.dumps(data)
            )
            log.info(f"success writing {key}")
            log.debug(f"got s3 resp: {resp}")
    else:
        log.info("mock writing s3...")


# WEB APPLICATION
async def handle(request):
    name = request.match_info.get("name", "Anonymous")
    text = "Hello, " + name + f"\nN={len(cache)}"
    return web.Response(text=text)


async def turn_daq_on(request):
    global ACTIVE
    log.info("turning on")
    ACTIVE = True
    return web.Response(text="success")


async def turn_daq_off(request):
    global ACTIVE
    log.info("turning off")
    ACTIVE = False
    return web.Response(text="success")


async def get_after(request):
    """returns the data after the `after` param if it exists, otherwise return everything"""
    log.info("get data")
    after = request.query.get("after", None)
    data = [v for k, v in cache.items() if after is None or k > after]
    data_set = {
        "data": data,
        "num": len(data),
        "test": LABEL_SET['title'],
    }
    return web.Response(body=json.dumps(data_set))


async def reset_labels(request):
    log.info("resetting labels")
    global LABEL_DEFAULT, LABEL_SET
    LABEL_SET.update(**LABEL_DEFAULT)
    return web.Response(body=json.dumps(LABEL_DEFAULT))


async def set_labels(request):
    
    global LABEL_DEFAULT, LABEL_SET
    
    #print(request.query)
    params = {k:int(v) if 'title' not in k else v for k,v in request.query.copy().items() if k in LABEL_DEFAULT and v}
    log.info(f"setting labels: {params}")
    LABEL_SET.update(**params)

    return web.Response(body=json.dumps(LABEL_SET))

async def get_current(request):
    if LAST and LAST in cache:
        return web.Response(body=json.dumps(cache[LAST]))
    return web.Response(text='no data, turn on DAQ')

async def get_data(request):
    """
    returns the cache data in format ts:data
    :param after: a timestamp, which is used to filter older values
    """
    if cache:
        after = request.query.get("after",None)
        if after is not None:
            after = float(after)
            subset = {k:v for k,v in cache.items() if k > after}
            return web.Response(body=json.dumps(subset))
        else:
            return web.Response(body=json.dumps(cache)) 

    return web.Response(text='no data, turn on DAQ')

async def calibrate(request,fail_threshold=0.05,max_lp=0.99):
    """a calibration method to adjust data to atmospheric pressure
    
    method:
    1. check to ensure data is within appropriate variance (less than 5% difference from full scale), if not raise a 507 error
    2. average data in buffer and determine a bias
    3. determine std deviation in data to adjust low pass filter
    4. calculate biases and store them
    5. write a response to 3s with the calibration info time stamped, if this step fails return a 202 code with the calibrated values in message
    6. finally return a 200 code with the calibrated values in message
    """
    #1/2/3. check data while using online algorithm to calculate avg / std-dev
    try:
        if not cache:
            raise Exception("no data")

        data=  {k:v for k,v in cache.items()}
        ts =   list(sorted(data.keys()))
        pdat = pressure_data = {k:{'N':0,'avg':0,'var':0} for k in pressure_pins}
        N = len(ts)
        #loop over time
        for i,t in enumerate(ts):    
            #loop over each pin
            A = 1.0 / (1+i)
            B = 1.0 - A
            for pskey,pin in pressure_pins.items():
                d =  data[t][pskey]
                pdat[pskey]['avg'] = avg= d * A + B * pdat[pskey]['avg']
                pdat[pskey]['var'] =  A*((d-avg)**2.0) + B*pdat[pskey]['var']
                if i == N-1:
                    pdat[pskey]['N'] = i

        _bias = CONST['biases'].copy()
        _lp = CONST['low_pass'].copy()

        #4. Calculate calibrations
        for pskey,pin in pressure_pins.items():
            avg = pdat[pskey]['avg']
            var = pdat[pskey]['var']
            std = var**0.5
            pctdev = std/avg
            if pctdev >= fail_threshold and ON_RASPI:
                return web.HTTPInsufficientStorage(text=f'sensor not ready {pskey}|{avg}|{std}')
            
            _bias[pskey] = avg - PATM
            #ensure a 50% -> max_lp% low pass, and should be closer to 100% near failure
            #(std/avg)/fail_threas <= 1 but enforce max low pass
            lop = pctdev/fail_threshold
            _lp[pskey] = min(MIN_LP+lop/2,max_lp)

        #set em!
        
        biases = _bias
        low_pass = _lp
        CONST['biases'] = biases
        CONST['low_pass'] = low_pass

        data = {'bias':biases,'lp':low_pass,'timestamp':time.time()}
        try:
            await write_s3(data,title='calibration')
        except Exception as e:
            log.error(e,exc_info=1)
            return web.HTTPAccepted(text=json.dumps(data))

        return web.Response( text = json.dumps(data) )
    
    except Exception as e:
        log.error(e,exc_info=1)
        return web.HTTPInternalServerError(text=str(e))




app = web.Application()
app.add_routes(
    [
        web.get("/", handle),
        web.get("/turn_on", turn_daq_on),
        web.get("/turn_off", turn_daq_off),
        
        web.get("/getdata", get_data),
        web.get("/getcurrent", get_current),

        web.get("/reset_labels",reset_labels),
        web.get("/set_labels",set_labels),
        web.get("/calibrate",calibrate),
    ]
)
apprun = web.AppRunner(app)

# MAIN
async def main(skip_dash=False):
    log.info("starting data aquisition")
    # Create App & Setup

    await apprun.setup()

    # CREATE PIPELINE TASKS
    # 1. data poll
    poll_task = asyncio.create_task(poll_data())
    # 2. process data
    process_task = asyncio.create_task(process_data())
    # 3. push data
    push_task = asyncio.create_task(push_data())

    # Run Site
    site = web.TCPSite(apprun, "0.0.0.0", 8777)
    site_task = asyncio.create_task(site.start())

    # Run Dashboard
    if not skip_dash:
        dash_task = asyncio.create_task(run_dashboard())


DASH = None


async def run_dashboard():
    """Launches the dashboard task and shuts it down"""
    pth = pathlib.Path(__file__)

    dash_path = f"live_dashboard.py"
    dash_path = os.path.join(pth.parent,dash_path)
    global DASH
    while True:
        cmd = f'{sys.executable} "{dash_path}"'
        log.info(f"running {cmd}")
        # sys.executable,'-c',dash_path,
        DASH = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ,
            shell=True,
        )

        await asyncio.sleep(3)

        stdout, stderr = await DASH.communicate()

        log.info(f"[{cmd!r} exited with {DASH.returncode}]")
        if stdout:
            log.info(f"[stdout]\n{stdout.decode()}")
        if stderr:
            log.info(f"[stderr]\n{stderr.decode()}")

        await DASH.wait()
        return DASH


async def close():
    global DASH
    await apprun.close()
    if DASH:
        await DASH.kill()

def cli():
    """The main task does several things:
    1. polls data and adds it to the buffer
    2. process the data from a queue to the cache, and mark timestamp unprocessed
    3. periodically push the unprocessed data to the bucket
    4. also run the webserver to serve the cache data, as well as apply labels and start/stop the data process
    """    
    import argparse
    parser = argparse.ArgumentParser('launch control')
    parser.add_argument("--no-dash",action="store_true",help='dont launch dashboard')

    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main(skip_dash=args.no_dash))
        loop.run_forever()  # to keep tasks spawning

    except KeyboardInterrupt:
        print("Received exit, exiting")
        sys.exit("Keyboard Interrupt")

    loop.run_until_complete(close())


if __name__ == "__main__":


    cli()