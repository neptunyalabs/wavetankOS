"""
in which we define motion classes
1. stepper_control: class provides a stepper control based off step/dir concept #TODO
2. motion_control: class provides a high level PWM based interface for speed/torque with position control #TODO
"""
import asyncpio
from math import cos,sin
import asyncio
import time
import traceback

class regular_wave:

    def __init__(self,Hs=0.1,Ts=1) -> None:
        self.hs = Hs
        self.ts = Ts
        self.update()

    def update(self):
        self.omg = (2*3.14159)/self.ts
        self.a = self.hs/2

    #wave interface
    def z_pos(self,t):
        return self.a*sin(self.omg*t)

    def z_vel(self,t):
        return self.a*self.omg*cos(self.omg*t)

class stepper_control:
    steps_per_rot = 360/1.8
    dz_per_rot = 0.01
    wave: regular_wave
    control_interval: float = 1./1000 #valid on linux, windows is 15ms
    
    min_dt = 10

    def __init__(self, fb:int, dir:int,step:int,**conf):
        """This class represents an A4988 stepper motor driver.  It uses two output pins
        for direction and step control signals."""
        self.wave = conf.get('wave',regular_wave())
        self.steps_per_rot = conf.get('steps_per_rot',360/1.8)
        self.dz_per_rot = conf.get('dz_per_rot',0.01)
        #self.on_time_us = 25 #us
        self.dz_per_step = self.dz_per_rot / self.steps_per_rot

        self._fb = fb
        self._dir = dir
        self._step = step
        
        #make it so
        self.fail_control = False
        self.fail_io = False        
        self.pi = asyncpio.pi()

        self.control_io_int = int(1E6*self.control_interval)

    async def _setup(self):
        await self.pi.connect()
        await self.pi.set_mode(self._dir,asyncpio.OUTPUT)
        await self.pi.set_mode(self._step,asyncpio.OUTPUT)
        await self.pi.set_mode(self._fb,asyncpio.INPUT)
        await self.pi.wave_clear()

    def setup(self):
        self.start = time.perf_counter()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._setup())

    def run(self):
        loop = asyncio.get_event_loop()
        self.control_task = loop.create_task(self.control())
        self.io_task = loop.create_task(self.control_io())

        try:
            loop.run_forever()
        except KeyboardInterrupt as e:
            print("Caught keyboard interrupt. Canceling tasks...")
            self.stop()
        finally:
            loop.close()

    def stop(self):
        loop = loop.get_event_loop()
        loop.run_until_complete(self._stop())        

    async def _stop(self):
        await self.pi.wave_tx_stop()
        await self.pi.wave_clear()
        await self.pi.stop()


    def is_safe(self):
        return not self.fail_control and not self.fail_io

    async def control(self):
        print(f'starting control...')
        while self.is_safe():
            try: #avoid loop overhead in subloop
                while self.is_safe():
                    t = time.perf_counter() - self.start
                    self.z_t = z = self.wave.z_pos(t)
                    self.v_t = v= self.wave.z_vel(t)

                    #TODO: set PWM width in real application to meet v
                    #r = self.pi.(self._res) #TODO: adc
                    #TODO: determine delta between z and bounds, stop if nessicary
                    #TODO: determine delta between z / r                    

                    if v != 0 and self.is_safe():
                        self.step_delay_us = max( int(1E6 * self.dz_per_step / abs(v)) , self.min_dt)
                    else:
                        self.step_delay_us = int(1E6)

                    self.dir_mult = 1 if v >= 0 else 0
                    
                    self.fail_control = False
                    await self.sleep(self.control_interval)
                    
            except Exception as e:
                self.fail_control = True
                print(f'control error: {e}')
        
        print(f'control ending...')
        await self._stop()

    async def control_io(self):
        print(f'starting control IO...')
        self.wave_last = None
        self.wave_next = None
        itick = 0
        printerval = 1000
        self.dt_io = 0.005 #u-seconds typical
        while self.is_safe():
            try: #avoid loop overhead in subloop
                while self.is_safe():
                    itick += 1

                    self.ct_st = time.perf_counter()
                    #dir set
                    #determine timing to meet step goal
                    dt = max(self.step_delay_us,self.min_dt) #div int by 2
                    
                    #increment pulses to handle async gap
                    inc = min(max(int((1E6*self.dt_io)/self.step_delay_us),1),100)

                    #define wave up for dt, then down for dt,j repeated inc
                    wave = [asyncpio.pulse(1<<self._step, 0, dt)]
                    wave.append(asyncpio.pulse(0, 1<<self._step, dt))
                    wave = wave*inc

                    ##create the new wave
                    self.wave_last = self.wave_next                    
                    await self.pi.wave_add_generic(wave)
                    self.wave_next = await self.pi.wave_create()

                    #eat up cycles waiting
                    if self.wave_last is not None:
                        #print(f'wave next {self.z_t} {self.v_t} {inc} {self.dir_mult} {self.step_delay_us}| {self.control_io_int}| {inc}| {len(wave)>>1}')
                        await self.pi.wave_delete(self.wave_last)
                        while self.wave_last == await self.pi.wave_tx_at():
                            #print(f'waiting...')
                            pass
                        await self.pi.wave_send_once(self.wave_next)
                        await self.pi.write(self._dir,self.dir_mult)
                        
                        
                    else:
                        #delete last
                        await self.pi.wave_send_once(self.wave_next)
                        await self.pi.write(self._dir,self.dir_mult)
                        
                    
                    self.fail_io = False
                    self.dt_io = time.perf_counter() - self.ct_st

                    if itick >= printerval:
                        itick = 0
                        print(f'step dt: {self.dt_io}| {self.step_delay_us}| {self.control_io_int}| {inc}| {len(wave)>>1}')

            except Exception as e:
                self.fail_io = True
                print(f'control io error: {e}')
                traceback.print_stack()

        print(f'control io ending...')
        await self._stop()

        
    async def sleep(self,wait_time,short=True):
        if short and wait_time >= 0.001:
            await asyncio.sleep(wait_time)
            return

        start = time.perf_counter()
        while True:
            if (time.perf_counter() - start) >= wait_time:
                break
            await asyncio.sleep(0) #no clock attempt, just straight to net







        






if __name__ == '__main__':

    rw = regular_wave()
    sc = stepper_control(9,6,12,wave=rw)
    sc.setup()
    sc.run()


