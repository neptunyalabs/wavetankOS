import asyncio
from aiohttp import web

global ON_RASPI

import logging
import os, sys
import pathlib

from waveware.hardware import hardware_control
from waveware.data_server import make_web_app,push_data
from waveware.config import *

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data")

async def close(web_app):
    await web_app.close()
    if web_app:
        await web_app.kill()

# MAIN
async def run_dashboard():
    """Launches the dashboard task and shuts it down"""
    pth = pathlib.Path(__file__)

    dash_path = f"live_dashboard.py"
    dash_path = os.path.join(pth.parent,dash_path)
   
    while True:
        cmd = f'{sys.executable} "{dash_path}"'
        log.info(f"running {cmd}")
        # sys.executable,'-c',dash_path,
        dash = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ,
            shell=True,
        )

        await asyncio.sleep(3)

        stdout, stderr = await dash.communicate()

        log.info(f"[{cmd!r} exited with {dash.returncode}]")
        if stdout:
            log.info(f"[stdout]\n{stdout.decode()}")
        if stderr:
            log.info(f"[stderr]\n{stderr.decode()}")

        await dash.wait()
        return dash

async def main(hw,web_app,skip_dash=False):
    log.info("starting data aquisition")
    # Create App & Setup
    await web_app.setup()

    # CREATE PIPELINE TASKS
    # 1. data poll
    poll_task = asyncio.create_task(hw.poll_data())
    # 2. process data
    process_task = asyncio.create_task(hw.process_data())
    # 3. push data
    push_task = asyncio.create_task(push_data(hw))

    # Run Site
    site = web.TCPSite(web_app, "0.0.0.0", 8777)
    site_task = asyncio.create_task(site.start())

    # Run Dashboard
    if not skip_dash:
        dash = run_dashboard()
        dash_task = asyncio.create_task(dash)

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
        #configure the system
        hw = hardware_control(encoder_pins,echo_pins,cntl_conf=control_conf,**pins_kw)
        app = make_web_app(hw)

        task = main(hw,app,skip_dash=args.no_dash)
        loop.run_until_complete(task)
        loop.run_forever()  # to keep tasks spawning

    except KeyboardInterrupt:
        print("Received exit, exiting")
        sys.exit("Keyboard Interrupt")

    loop.run_until_complete(close())


if __name__ == "__main__":


    cli()