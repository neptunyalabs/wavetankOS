import asyncio
from aiohttp import web

global ON_RASPI

import logging
import os, sys
import pathlib
import traceback

from waveware.hardware import hardware_control
from waveware.data_server import make_app,push_data
from waveware.config import *

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data")


class program:
    """a thin stateful class to handle async tasks, and dashboard subprocess"""
    dash_proc: asyncio.subprocess
    app:web.TCPSite
    hw:hardware_control


    # MAIN
    async def run_dashboard(self):
        """Launches the dashboard task and shuts it down"""
        pth = pathlib.Path(__file__)

        dash_path = f"live_dashboard.py"
        dash_path = os.path.join(pth.parent,dash_path)
    
        while True:
            cmd = f'{sys.executable} "{dash_path}"'
            log.info(f"running {cmd}")
            # sys.executable,'-c',dash_path,
            
            env = os.environ
            if ON_RASPI:
                #goal wavetank.local hosting! #BUG: issue with WSL on port 80 (and with MDNS)
                env['PORT']='80'

            #assign dashboard
            self.dash_proc = dash = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                shell=True,
            )
            

            await asyncio.sleep(3)

            await dash.wait()
            log.info(f'dashboard exited!!!')
            stdout, stderr = await dash.communicate()

            log.info(f"[{cmd!r} exited with {dash.returncode}]")
            if stdout:
                log.info(f"[stdout]\n{stdout.decode()}")
            if stderr:
                log.info(f"[stderr]\n{stderr.decode()}")

            await dash.wait()
            return dash

    async def main(self,skip_dash=False):
        try:
            log.info("starting hw data server..")
            # Create App & Setup
            await self.app.setup() #turn on webapp
            await 

            # CREATE PIPELINE TASKS
            # 1. data poll
            self.poll_task = asyncio.create_task(self.hw.poll_data())
            # 2. process data
            self.process_task = asyncio.create_task(self.hw.process_data())
            # 3. push data
            self.push_task = asyncio.create_task(push_data(self.hw))

            # Run Site
            self.site = web.TCPSite(self.app, "0.0.0.0", embedded_srv_port)
            self.site_task = asyncio.create_task(self.site.start())

            # Run Dashboard
            if not skip_dash:
                self.dash = self.run_dashboard()
                self.dash_task = asyncio.create_task(self.dash)
            else:
                self.dash = None
        except Exception as e:
            print(f'error in main: {e}')
            traceback.print_tb(e.__traceback__)
            sys.exit(1)

    def setup(self):
        #configure the system
        self.hw = hardware_control(encoder_pins,echo_pins,cntl_conf=control_conf,**pins_kw)
        self.hw.setup()
        self.app = make_app(self.hw)

    def print_dash(self,out):
        out = out.result()[0]
        #log.info(f'DASH RESULT: {str(out)}')
        stdout,stderr = out
        log.info(f'DASH OUT:\n{stdout.decode()}')
        log.info(f'DASH ERR:\n{stderr.decode()}')

    
    async def close(self,print_dash=True):
        app = self.dash
        if app is not None:
            app.close()

        if hasattr(self,'dash_proc'):
            cb = asyncio.gather(self.dash_proc.communicate())
            
            if print_dash:
                cb.add_done_callback(self.print_dash)

            res = self.dash_proc.kill()
            log.info(f'dash proc kill: {res}')
            await cb

        await asyncio.sleep(0.1)

    def cli(self):
        """The main task does several things:
        1. polls data and adds it to the buffer
        2. process the data from a queue to the cache, and mark timestamp unprocessed
        3. periodically push the unprocessed data to the bucket
        4. also run the webserver to serve the cache data, as well as apply labels and start/stop the data process
        """
        import argparse
        parser = argparse.ArgumentParser('launch control')
        parser.add_argument("--no-dash",action="store_true",help='dont launch dashboard')
        parser.add_argument("--print-dash",action="store_true",help='prints dashboard stdout / stderr on keyboard interrupt')

        args = parser.parse_args()

        loop = asyncio.get_event_loop()
        self.setup()
        try:
            task = self.main(skip_dash=args.no_dash)
            loop.run_until_complete(task)
            loop.run_forever()  # to keep tasks spawning

        except KeyboardInterrupt:
            log.info("Received exit, exiting")

        loop.run_until_complete(self.close(print_dash=args.print_dash))


if __name__ == "__main__":
    """run the cli"""
    prog = program()
    prog.cli()