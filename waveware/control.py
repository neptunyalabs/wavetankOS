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

import smbus
import time
import sys,os,pathlib
# Get I2C bus

control_dir = pathlib.Path(__file__).parent

#ADC stuff
p_adc = {0:'100',1:'101',2:'110',3:'111'}
fv_ref = {6:'000',4:'001',2:'010',1:'011'}
volt_ref = {6:6.144,4:4.096,2:2.048,1:1.024}
dr_ref = {8:'000',16:'001',32:'010',64:'011',128:'100',250:'101',475:'110',860:'111'}

def config_bit(pinx,fvinx=4):
    dv = p_adc[pinx]
    vr = fv_ref[fvinx]
    return int(f'1{dv}{vr}0',2)

wait_factor = 2
fv_inx = 4
dr_inx = 860
dr = dr_ref[dr_inx]


drive_modes = ['steps','cal','stop']

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
    
    min_dt = 3

    adc_addr = 0x48

    def __init__(self, dir:int,step:int,fb_an_pin=0,**conf):
        """This class represents an A4988 stepper motor driver.  It uses two output pins
        
        for direction and step control signals."""
        
        #setup drive mode first
        self.drive_mode = 'cal'
        self.mode_changed = asyncio.Future()
        self.set_mode('cal')# #always start in calibration mode

        self.wave = conf.get('wave',regular_wave())
        self.steps_per_rot = conf.get('steps_per_rot',360/1.8)
        self.dz_per_rot = conf.get('dz_per_rot',0.01)
        #self.on_time_us = 25 #us
        self.dz_per_step = self.dz_per_rot / self.steps_per_rot

        self._dir = dir
        self._step = step
        self._fb_an_pin = fb_an_pin
        
        #make it so
        self.fail_control = False
        self.fail_io = False        
        self.pi = asyncpio.pi()

        self._last_dir = 1
        self.feedback_volts = None
        self.fail_feedback = None
        self.control_io_int = int(1E6*self.control_interval)

        self.setup_i2c()
             
    async def _setup(self):
        await self.pi.connect()
        await self.pi.set_mode(self._dir,asyncpio.OUTPUT)
        await self.pi.set_mode(self._step,asyncpio.OUTPUT)
        await self.pi.wave_clear()

    def setup(self):
        self.start = time.perf_counter()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._setup())

    def run(self):
        loop = asyncio.get_event_loop()
        self.first_feedback = d = asyncio.Future()
        self.feedback_task = loop.create_task(self.feedback(d))
        

        def go(*args,docal=True,**kw):
            nonlocal self, loop
            print('feedback OK.')

            cal_file = os.path.join(control_dir,'wave_cal.json')
            has_file = os.path.exists(cal_file)
            if docal and not has_file:
                print(f'calibrate first...')
                task = loop.create_task(self.calibrate())
                task.add_done_callback(lambda *a,**kw:go(*a,docal=False,**kw))
            else:
                print('starting...')
                self.set_mode('steps')
                self.control_task = loop.create_task(self.control_steps())
                self.io_task = loop.create_task(self.control_io_steps())

        self.first_feedback.add_done_callback(go)

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
        return all([not self.fail_control, 
                    not self.fail_io, 
                    not self.fail_feedback])
    
    def set_mode(self,new_mode):
        assert new_mode in drive_modes,'bad drive mode! choose: {drive_modes}'
        new_mode = new_mode.lower().strip()
        if new_mode == self.drive_mode:
            print(f'same old drive mode: {new_mode}')
        
        self.drive_mode = new_mode
        if hasattr(self,'mode_changed'):
            self.mode_changed.set_result(new_mode)
        self.mode_changed = asyncio.Future()
    
    def setup_i2c(self,pin = 0):
        self.smbus = smbus.SMBus(1)        
        cb = config_bit(pin,fvinx = 4)
        db = int(f'{dr}00011',2)
        data = [cb,db]
        #do this before reading different pin, 
        self.smbus.write_i2c_block_data(0x48, 0x01, data)

    async def calibrate(self,t_on=100,t_off=9900,inc=1):
        ##do some small jitters and estimate the local sensitivity, catch on ends
        
        print(f'calibrating!')
        self._st_cal = time.perf_counter()
        
        self.wave_last = None
        self.wave_next = None

        self.step_count = 0
        self.inx = 0
        self.coef_2 = 0
        self.coef_10 = 0
        self.coef_100 = 0

        self.upper_lim = None
        self.center_inx = 0
        self.lower_lim = None
        

        await self.local_cal(t_on=t_on,t_off=t_off,inc=inc)
        await self.center_head(t_on=t_on,t_off=t_off,inc=inc)
        await self.find_extends(t_on=t_on,t_off=t_off,inc=inc)
        await self.center_head(t_on=t_on,t_off=t_off,inc=inc)       

    async def local_cal(self,t_on=100,t_off=9900,inc=1):
        print('local cal...')
        #determine local sensitivity
        for upr,lwr in [[1,-1],[10,-10],[100,-100]]:
            
            print(f'fwd: {upr}')
            for step_plus in range(upr):
                #change dir if nessicary

                #define wave up for dt, then down for dt,j repeated inc
                wave = [asyncpio.pulse(1<<self._step, 0, t_on)]
                wave.append(asyncpio.pulse(0, 1<<self._step, t_off))
                vlast = self.feedback_volts
                wave = wave * inc

                await self.step_wave(wave,dir=1)
            
            print(f'rv: {lwr}')
            for step_minus in range(lwr,0):
                #change dir if nessicary

                #define wave up for dt, then down for dt,j repeated inc
                wave = [asyncpio.pulse(1<<self._step, 0, t_on)]
                wave.append(asyncpio.pulse(0, 1<<self._step, t_off))
                wave = wave * inc
                
                await self.step_wave(wave,dir=-1)
            
        #drive center
    async def find_extends(self,t_on=100,t_off=9900,inc=1):
        print('find extents...')
        start_coef_100 = self.coef_100
        start_coef_10 = self.coef_10
        start_coef_2 = self.coef_2
        
        start_dir = 1
        while abs(self.coef_10) > 1E-6:
            wave = [asyncpio.pulse(1<<self._step, 0, t_on)]
            wave.append(asyncpio.pulse(0, 1<<self._step, t_off))
            wave = wave * inc
            await self.step_wave(wave,dir=start_dir)
        print(f'found upper: {self.inx - 10}')
        self.upper_lim = self.inx - 10

        self.coef_100 = start_coef_100
        self.coef_10 = start_coef_10
        self.coef_2 = start_coef_2


        start_dir = -1
        while abs(self.coef_10) > 1E-6:
            wave = [asyncpio.pulse(1<<self._step, 0, t_on)]
            wave.append(asyncpio.pulse(0, 1<<self._step, t_off))
            wave = wave * inc
            await self.step_wave(wave,dir=start_dir)

        print(f'found lower: {self.inx + 10}')
        self.lower_lim = self.inx + 10

        self.coef_100 = start_coef_100
        self.coef_10 = start_coef_10
        self.coef_2 = start_coef_2



    async def center_head(self,t_on=100,t_off=9900,inc=1):
        print('center head...')
        cent_voltage = 3.3/2
        fv = self.feedback_volts
        dv=cent_voltage-fv
        while abs(dv) > 0.01:

            fv = self.feedback_volts
            dv=cent_voltage-fv

            #print(dv,coef_100,inx)
            #set direction
            est_steps = dv / float(self.coef_100)
            if est_steps <= 0:
                dir = -1
            else:
                dir = 1
            #define wave up for dt, then down for dt,j repeated inc
            wave = [asyncpio.pulse(1<<self._step, 0, t_on)]
            wave.append(asyncpio.pulse(0, 1<<self._step, t_off))
            wave = wave * inc

            await self.step_wave(wave,dir=dir)
        
        self.center_inx = self.inx




    async def step_wave(self,wave,dir=1):

        if self._last_dir != dir:
            dv = 1 if dir >= 0 else 0
            await self.pi.write(self._dir,dv)
            self._last_dir = dir

        if hasattr(self,'wave_last') and self.wave_last is not None:
            await self.pi.wave_delete(self.wave_last)
            while self.wave_last == await self.pi.wave_tx_at():
                #print(f'waiting...')
                await asyncio.sleep(0)
        
        vlast = self.feedback_volts
        Nw = max(int(len(wave)/2),1)

        ##create the new wave
        self.wave_last = self.wave_next                    
        await self.pi.wave_add_generic(wave)

        self.wave_next = await self.pi.wave_create()
        await self.pi.wave_send_once( self.wave_next)
        
        vnow = self.feedback_volts

        dvds = (vnow-vlast)/((dir*Nw))
        self.coef_2 = (self.coef_2 + dvds)/2
        self.coef_10 = (self.coef_10*0.9 + dvds*0.1)
        self.coef_100 = (self.coef_100*0.99 + dvds*0.01)
        if (abs(self.inx)%10==0):
            DIR = 'FWD' if dir > 0 else 'REV'             
            print(f'{DIR}:|{self.inx:<4}| {vnow:3.5f}'+' '.join([f'|{v:10.7f}' for v in (dvds,self.coef_2,self.coef_10,self.coef_100)]))
        
        self.step_count += Nw
        self.inx = self.inx + dir*Nw

        ###Move one direction until d(feedback)/ds = 0
        ###Then move the other


    async def feedback(self,feedback_futr=None):
        while True:
            try:
                while True:
                    wait = wait_factor/float(dr_inx)
                    await asyncio.sleep(wait)
                    data = self.smbus.read_i2c_block_data(0x48, 0x00, 2)
                    
                    # Convert the data
                    raw_adc = data[0] * 256 + data[1]
                    if raw_adc > 32767:
                        raw_adc -= 65535
                    self.feedback_volts = (raw_adc/32767)*volt_ref[fv_inx]
                    self.fail_feedback = False

                    if feedback_futr is not None:
                        feedback_futr.set_result(True)
                        feedback_futr = None #twas, no more 

            except Exception as e:
                self.fail_feedback = True
                print(f'control error: {e}')       

    #TODO: set PWM width in real application to meet v
    #r = self.pi.(self._res) #TODO: adc
    #TODO: determine delta between z and bounds, stop if nessicary
    #TODO: determine delta between z / r    

    async def control_steps(self):
        print(f'starting control...')
        while self.is_safe():
            start_mode = self.mode_changed
            if self.drive_mode == 'steps':
                try: #avoid loop overhead in subloop
                    while self.is_safe() and start_mode is self.mode_changed:
                        t = time.perf_counter() - self.start
                        self.z_t = z = self.wave.z_pos(t)
                        self.z_t_1 = z = self.wave.z_pos(t+self.control_interval)
                        self.v_t = v= self.wave.z_vel(t)
                        self.v_t_1 = v= self.wave.z_vel(t+self.control_interval)


                        z = self.z_t #always measure goal pos for error
                        v = (self.v_t + self.v_t_1)/2 #correct integral for pwm                

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
            
            await self.mode_changed

        print(f'something failed!')
        await self._stop()

    async def control_io_steps(self):
        print(f'starting control IO...')
        self.wave_last = None
        self.wave_next = None
        itick = 0
        printerval = 1000
        self.dt_io = 0.005 #u-seconds typical
        while self.is_safe():
            start_mode = self.mode_changed
            if self.drive_mode == 'steps':
                try: #avoid loop overhead in subloop
                    while self.is_safe() and start_mode is self.mode_changed:
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
                            
                        print(self.feedback_volts)
                        self.fail_io = False
                        self.dt_io = time.perf_counter() - self.ct_st

                        if itick >= printerval:
                            itick = 0
                            print(f'step dt: {self.dt_io}| {self.step_delay_us}| {self.control_io_int}| {inc}| {len(wave)>>1}')

                except Exception as e:
                    self.fail_io = True
                    print(f'control io error: {e}')
                    traceback.print_stack()
                
            await self.mode_changed

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
    sc = stepper_control(6,12,wave=rw)
    sc.setup()
    sc.run()


