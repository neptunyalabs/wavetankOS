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
# see https://thecavepearlproject.org/2020/05/21/using-the-ads1115-in-continuous-mode-for-burst-sampling/
low_thres = 0x0000 
high_thres = 0x8000


drive_modes = ['manual','wave','stop','center','cal','local','extents']
default_mode = 'cal'

speed_modes = ['step','pwm','off']
default_speed_mode = os.environ.get('WAVE_SPEED_DRIVE_MODE','pwm').strip().lower()
assert default_speed_mode in speed_modes

class regular_wave:

    def __init__(self,Hs=1,Ts=3) -> None:
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
    
def speed_off_then_revert(f):

    async def fme(self,*args,**kwargs):

        cur_speed_mode = self.speed_control_mode
        if cur_speed_mode == 'off':
            await f(self,*args,**kwargs)
            return
        
        self.set_speed_mode('off')
        try:
            await f(self,*args,**kwargs)
        except Exception as e:
            print(f'error in {f.__name__} {e}')

        self.set_speed_mode(cur_speed_mode)
    
    return fme     

class stepper_control:
    steps_per_rot = 360/1.8
    dz_per_rot = 0.01
    wave: regular_wave
    control_interval: float = 10./1000 #valid on linux, windows is 15ms

    kzp_sup = 1#/T
    kzi_err = 0.1
    
    min_dt = 5

    adc_addr = 0x48

    def __init__(self, dir:int,step:int,speed_pwm:int,fb_an_pin:int,hlfb:int,torque_pwm:int=10,**conf):
        """This class represents an A4988 stepper motor driver.  It uses two output pins
        
        for direction and step control signals."""
        self.dt_stop_and_wait = 60

        #setup drive mode first
        self.drive_mode = 'cal'
        self.mode_changed = asyncio.Future()
        self.set_mode('cal')# #always start in calibration mode

        self.wave = conf.get('wave',regular_wave())
        self.steps_per_rot = conf.get('steps_per_rot',360/1.8)
        self.dz_per_rot = conf.get('dz_per_rot',0.01)
        #self.on_time_us = 25 #us
        self.dz_per_step = self.dz_per_rot / self.steps_per_rot
        self.max_speed_motor = 0.3 #TODO: get better motor constants

        self._dir_pin = dir
        self._step_pin = step
        self._vpwm_pin = speed_pwm
        self._tpwm_pin = torque_pwm
        self._adc_feedback_pin = fb_an_pin
        self._hlfb = hlfb
        #TODO: setup high/low interrupt on hlfb for ppr or torque / speed ect
        
        #fail setupso
        self._control_modes = {}
        self._control_mode_fail_parms = {}

        self.pi = asyncpio.pi()

        self._last_dir = 1
        self.feedback_volts = None
        self.fail_feedback = None
        self.reset()
        self.setup_i2c()
    
    def reset(self):
        self.fail_st = False
        self.fail_sc = False
        self.v_cmd =v= 0
        self.v_sup = 0
        self.dir_mult = 1 if v >= 0 else 0
        self._last_dir = 1 if v >= 0 else -1

        self.wave_last = None
        self.wave_next = None

        self.step_count = 0
        self.inx = 0
        self.coef_2 = 0
        self.coef_10 = 0
        self.coef_100 = 0
        self.z_err_cuml = 0

        tol = 0.5
        self.dzdvref = 0
        self.upper_lim = None
        self.center_inx = 0
        self.upper_v = 3.3-tol
        self.lower_v = tol     
        self.lower_lim = None
        self.vref_0 = (self.upper_v+self.lower_v)/2

    #SETUP 
    async def _setup(self):
        await self.pi.connect()
        await self.pi.set_mode(self._dir_pin,asyncpio.OUTPUT)
        await self.pi.set_mode(self._step_pin,asyncpio.OUTPUT)
        await self.pi.set_mode(self._tpwm_pin,asyncpio.OUTPUT)
        await self.pi.set_mode(self._vpwm_pin,asyncpio.OUTPUT)

        await self.pi.set_mode(self._hlfb,asyncpio.INPUT)
        await self.pi.set_mode(self._adc_feedback_pin,asyncpio.INPUT)
        #await self.pi.wave_clear()

    def setup(self):
        self.start = time.perf_counter()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._setup())

    
    def setup_i2c(self,pin = 0):
        self.smbus = smbus.SMBus(1)        
        cb = config_bit(pin,fvinx = 4)
        db = int(f'{dr}00011',2)
        data = [cb,db]
        #do this before reading different pin, 
        print(f'setting adc to: {[bin(d) for d in data]}')
        self.smbus.write_i2c_block_data(0x48, 0x01, data)
        #setup alert pin!
        #self.smbus.write_i2c_block_data(0x48, 0x02, [0x00,0x00])
        #self.smbus.write_i2c_block_data(0x48, 0x03, [0x80,0x00])

    #RUN / OPS


    def run(self):
        loop = asyncio.get_event_loop()

        def check_failure(res):
            try:
                res.result()
            except Exception as e:
                print(f'speed drive failure: {e}|\n{e.__traceback__}')

        self.speed_control_mode = default_speed_mode
        self.mode_changed = asyncio.Future()
        self.speed_control_mode_changed = asyncio.Future()
        self.first_feedback = d = asyncio.Future()
        self.feedback_task = loop.create_task(self.feedback(d))
        
        self.speed_off_task = loop.create_task(self.speed_control_off())
        self.speed_off_task.add_done_callback(check_failure)

        self.speed_pwm_task = loop.create_task(self.speed_pwm_control())
        self.speed_pwm_task.add_done_callback(check_failure)

        self.speed_step_task = loop.create_task(self.step_speed_control())
        self.speed_step_task.add_done_callback(check_failure)
        

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
                self.start_control()

        self.first_feedback.add_done_callback(go)

        try:
            loop.run_forever()
        except KeyboardInterrupt as e:
            print("Caught keyboard interrupt. Canceling tasks...")
            self.stop()
        finally:
            loop.close()

    #STOPPPING / SAFETY
    def stop(self):
        loop = loop.get_event_loop()
        loop.run_until_complete(self._stop())        

    async def _stop(self):
        await self.pi.wave_tx_stop()
        await self.pi.wave_clear()
        await self.pi.stop()



    def is_safe(self):
        #base = any((self._control_mode_fail_parms.values()))
        base = self._control_mode_fail_parms[self.drive_mode]
        return all([not base,
                    not self.fail_sc,
                    not self.fail_st])
                    #not self.stuck])
    
    def set_mode(self,new_mode):
        assert new_mode in drive_modes,'bad drive mode! choose: {drive_modes}'
        new_mode = new_mode.lower().strip()
        if new_mode == self.drive_mode:
            print(f'same drive mode: {new_mode}')
            return
        
        self.drive_mode = new_mode
        print(f'setting mode: {self.speed_control_mode}')
        if hasattr(self,'mode_changed'):
            self.mode_changed.set_result(new_mode)
        self.mode_changed = asyncio.Future()
    
    def set_speed_mode(self,new_mode):
        assert new_mode in speed_modes,'bad drive mode! choose: {drive_modes}'
        new_mode = new_mode.lower().strip()
        if new_mode == self.speed_control_mode:
            print(f'same speed mode: {new_mode}')
            return
        
        self.speed_control_mode = new_mode
        print(f'setting speed mode: {self.speed_control_mode}')
        if hasattr(self,'speed_control_mode_changed'):
            self.speed_control_mode_changed.set_result(new_mode)
        self.speed_control_mode_changed = asyncio.Future()        

    def make_control_mode(self,mode,loop_function,*args,**kw):
        loop = asyncio.get_event_loop()
        #make the loop task
        func = self.control_mode(loop_function,mode)
        task = loop.create_task(func)
        
        #task.add_done_callback #TODO: handle failures
        self._control_modes[mode]=task
        self._control_mode_fail_parms[mode] = False

        def _fail_control(res):
            print(f'mode done! {mode}')
            try:
                res.result()
            except Exception as e:
                traceback.print_exception(e)

        task.add_done_callback(_fail_control)
        return task

    def start_control(self):
        print('starting...')
        loop = asyncio.get_event_loop()
        self.set_mode(default_mode)

        self.goals_task = self.make_control_mode('wave',self.wave_goal)
        self.stop_task = self.make_control_mode('stop',self.run_stop)
        self.center_task = self.make_control_mode('center',self.center_head)
        self.cal_task = self.make_control_mode('cal',self.calibrate)
        self.local_task = self.make_control_mode('local',self.local_cal)
        self.extent_task = self.make_control_mode('extents',self.find_extends)
        
        #TODO: interactive
        #self.manual_task = self.make_control_mode('manual',self.manual_mode)



    async def control_mode(self,loop_function:callable,mode_name:str):
        """runs an async function"""
        print(f'creating control {mode_name}|{loop_function.__name__}...')
        
        while self.is_safe():
            start_mode = self.mode_changed

            if (isinstance(mode_name,str) and self.drive_mode == mode_name) or (isinstance(mode_name,(list,tuple)) and self.drive_mode in mode_name):
                print(f'starting control {mode_name}|{loop_function.__name__}...')
                try: #avoid loop overhead in subloop
                    while self.is_safe() and start_mode is self.mode_changed:
                        await loop_function()
                        self._control_mode_fail_parms[mode_name] = False
                        
                except Exception as e:
                    self._control_mode_fail_parms[mode_name] = True
                    print(f'control {mode_name}|{loop_function.__name__} error: {e}')
                    task = asyncio.current_task()
                    task.print_stack()
            
            #if your not the active loop wait until the mode has changed to check again. Only one mode can run at a time
            await self.mode_changed

        print(f'control io ending...')
        await self._stop()
        

    #CALIBRATE
    @speed_off_then_revert
    async def calibrate(self,t_on=100,t_off=99000,inc=1):
        ##do some small jitters and estimate the local sensitivity, catch on ends
        
        print(f'calibrating!')
        self._st_cal = time.perf_counter()
        
        self.reset()

        await self.local_cal(t_on=t_on,t_off=t_off,inc=inc)
        await self.center_head(t_on=t_on,t_off=t_off,inc=inc)
        await self.find_extends(t_on=t_on,t_off=t_off,inc=inc)
        await self.center_head(t_on=t_on,t_off=t_off,inc=inc)       

    @speed_off_then_revert
    async def local_cal(self,t_on=100,t_off=9900,inc=1):
        print('local cal...')
        #determine local sensitivity
        await self.pi.write(self._step_pin,0)
        await self.pi.write(self._step_pin,1)
        await self.pi.write(self._step_pin,0)
        for upr,lwr in [[1,-1],[10,-10],[100,-100]]:
            
            print(f'fwd: {upr}')
            for step_plus in range(upr):
                #change dir if nessicary

                #define wave up for dt, then down for dt,j repeated inc
                wave = [asyncpio.pulse(1<<self._step_pin, 0, t_on)]
                wave.append(asyncpio.pulse(0, 1<<self._step_pin, t_off))
                wave = wave * inc

                await self.step_wave(wave,dir=1)
            
            print(f'rv: {lwr}')
            for step_minus in range(lwr,0):
                #change dir if nessicary

                #define wave up for dt, then down for dt,j repeated inc
                wave = [asyncpio.pulse(1<<self._step_pin, 0, t_on)]
                wave.append(asyncpio.pulse(0, 1<<self._step_pin, t_off))
                wave = wave * inc
                
                await self.step_wave(wave,dir=-1)
            
    #drive center
    @speed_off_then_revert
    async def find_extends(self,t_on=100,t_off=9900,inc=1):
        print('find extents...')
        start_coef_100 = self.coef_100
        start_coef_10 = self.coef_10
        start_coef_2 = self.coef_2
        
        start_dir = 1
        while abs(self.coef_10) > 1E-6:
            wave = [asyncpio.pulse(1<<self._step_pin, 0, t_on)]
            wave.append(asyncpio.pulse(0, 1<<self._step_pin, t_off))
            wave = wave * inc
            await self.step_wave(wave,dir=start_dir)
        print(f'found upper: {self.inx - 10}')
        self.upper_v = self.feedback_volts
        self.upper_lim = self.inx - 10

        self.coef_100 = start_coef_100
        self.coef_10 = start_coef_10
        self.coef_2 = start_coef_2


        start_dir = -1
        while abs(self.coef_10) > 1E-6:
            wave = [asyncpio.pulse(1<<self._step_pin, 0, t_on)]
            wave.append(asyncpio.pulse(0, 1<<self._step_pin, t_off))
            wave = wave * inc
            await self.step_wave(wave,dir=start_dir)

        print(f'found lower: {self.inx + 10}')
        self.lower_lim = self.inx + 10
        self.lower_v = self.feedback_volts
        self.coef_100 = start_coef_100
        self.coef_10 = start_coef_10
        self.coef_2 = start_coef_2

        #TODO: write calibration file
        #TODO: write the z-index and prep for z offset
        self.di_dz = self.upper_lim - self.lower_lim + 20
        self.dvref_range = self.upper_v - self.lower_v
        #calculated z per 
        self.dz_range = self.dz_per_step * self.di_dz
        #how much z changes per vref
        self.dzdvref = self.dz_range/self.dvref_range  
        
        #offset defaults to center
        #TODO: change reference position via api
        self.zi_0 = (self.upper_lim+self.lower_lim)/2 #center
        self.vref_0 = (self.upper_v+self.lower_v)/2 #center


    @speed_off_then_revert
    async def center_head(self,t_on=100,t_off=9900,inc=1,tol=0.01):
        print('center head...') 
        fv = self.feedback_volts
        dv=self.vref_0-fv

        #print(dv,coef_100,inx)
        #set direction
        est_steps = dv / float(self.coef_100)
        if est_steps <= 0:
            dir = -1
        else:
            dir = 1

        #define wave up for dt, then down for dt,j repeated inc
        wave = [asyncpio.pulse(1<<self._step_pin, 0, t_on)]
        wave.append(asyncpio.pulse(0, 1<<self._step_pin, t_off))
        wave = wave * inc

        await self.step_wave(wave,dir=dir)
        
        self.center_v = self.feedback_volts
        self.center_inx = self.inx


    #Wave Control Goal
    async def wave_goal(self):
        ###constantly determines

        t = time.perf_counter() - self.start
        self.z_t = z = self.wave.z_pos(t)
        self.z_t_1 = z = self.wave.z_pos(t+self.control_interval)
        self.v_t = v= self.wave.z_vel(t)
        self.v_t_1 = v= self.wave.z_vel(t+self.control_interval)
        
        #avg velocity
        #v = self.v_t
        v = (self.v_t + self.v_t_1)/2
        v = min(max(v,-self.max_speed_motor),self.max_speed_motor)

        #always measure goal pos for error
        
        z = self.z_t
        z_err = z - self.z_cur
        self.z_err_cuml = z_err*self.kzi_err + self.z_err_cuml*(1-self.kzi_err)
        
        #correct integral for pwm ala velocity
        self.dv_err = z_err * self.kzp_sup / self.wave.ts
        self.v_sup = self.v_cmd + self.dv_err

        #determine direction
        self.dir_mult = 1 if v >= 0 else 0
        self._last_dir = 1 if v >= 0 else -1
        
        #self.v_cmd = self.v_sup #TODO: validate this for position holding
        self.v_cmd = v
        await self.sleep(self.control_interval)

    async def run_stop(self):
        self.v_cmd = 0      
        await self.sleep(self.control_interval)
                    

    #FEEDBACK
    @property
    def maybe_stuck(self):
        if abs(self.coef_2) < 1E-5 and self.step_count > 1000:
            return True
        return False
    
    @property
    def stuck(self):
        if abs(self.coef_10) < 1E-6 and self.step_count > 1000:
            return True
        return False

    async def feedback(self,feedback_futr=None):
        print(f'starting feedback!')
        self.dvds = None
        VR = volt_ref[fv_inx]
        # self._adc_feedback_pin_cb = asyncio.Future()

#         def trigger_read(gpio,level,tick):
#             adc = self._adc_feedback_pin_cb
#             adc.set_result(tick)
#             self._adc_feedback_pin_cb = asyncio.Future()
#             
# 
#         await self.pi.callback(self._adc_feedback_pin,asyncpio.FALLING_EDGE,trigger_read)
        self.t_no_inst = False
        while True:
            vlast = vnow = self.feedback_volts #prep vars
            try:
                while True:
                    vlast = vnow if vnow is not None else 0
                    st_inx = self.inx
                    wait = wait_factor/float(dr_inx)
                    
                    #TODO: add feedback interrupt on GPIO7
                    #-await deferred, in pigpio callback set_result
                    #tick = await self._adc_feedback_pin_cb
                    await self.sleep(wait)
                    
                    try:
                        data = self.smbus.read_i2c_block_data(0x48, 0x00, 2)
                    except Exception as e:
                        print('read i2c issue',e)
                        continue
                    
                    # Convert the data
                    raw_adc = data[0] * 256 + data[1]
                    if raw_adc > 32767:
                        raw_adc -= 65535
                    self.feedback_volts = vnow = (raw_adc/32767)*VR
                    self.z_cur = (vnow)*self.dzdvref
                    

                    if feedback_futr is not None:
                        feedback_futr.set_result(True)
                        feedback_futr = None #twas, no more 

                    
                    Nw = int(self.inx - st_inx)

                    #ok!
                    self.fail_feedback = False                    
                    
                    #stop catching
                    if self.drive_mode == 'stop':
                        continue

                    elif Nw < 1:
                        #no steps, no thank you
                        if self.t_no_inst is False:
                            print(f'no steps')
                            self.t_no_inst = time.perf_counter()
                        
                        elif time.perf_counter() - self.t_no_inst>self.dt_stop_and_wait:
                            print(f'stopping')
                            #self.set_mode('stop') #FIXME
                        
                        continue #dont add voltage change or check stuck
                    
                    self.t_no_inst = False
                    self.dvds = (vnow-vlast)/((self._last_dir*Nw))
                    self.coef_2 = (self.coef_2 + self.dvds)/2
                    self.coef_10 = (self.coef_10*0.9 + self.dvds*0.1)
                    self.coef_100 = (self.coef_100*0.99 + self.dvds*0.01)

                    if self.maybe_stuck:
                        print(f'CAUTION: maybe stuck: {self.coef_2}')

                    if self.stuck:
                        #self.set_mode('stop') #FIXME
                        pass


            except Exception as e:
                self.fail_feedback = True
                print(f'control error: {e}')       
                traceback.print_tb(e.__traceback__)

    #to handle stepping controls
    async def step_wave(self,wave,dir=None):
        """places waveform on pin with appropriate callbacks"""

        if dir is None:
            dir = self._last_dir
        elif self._last_dir != dir:
            dv = 1 if dir >= 0 else 0
            await self.pi.write(self._dir_pin,dv)
            self._last_dir = dir

        
        self.wave_last = self.wave_next #push back

        if self.wave_last is not None:
            ##create the new wave
            pad_amount = await self.pi.wave_get_micros()
            
            #TODO: make sure this is a good idea
            wave = [asyncpio.pulse(0, 0, pad_amount)] + wave
            await self.pi.wave_add_generic(wave)

            self.wave_next = await self.pi.wave_create()
            await self.pi.wave_send_once( self.wave_next)              
            while self.wave_last == await self.pi.wave_tx_at():
                #print(f'waiting...')
                await asyncio.sleep(0)

            await self.pi.wave_delete(self.wave_last)

        else:
            #do it raw
            ##create the new wave
            await self.pi.wave_add_generic(wave)

            self.wave_next = await self.pi.wave_create()
            await self.pi.wave_send_once( self.wave_next)
        
        Nw = max(int(len(wave)/2),1)
        
        if (abs(self.inx)%10==0):
            vnow = self.feedback_volts
            if vnow is None: vnow = 0
            DIR = 'FWD' if dir > 0 else 'REV'             
            print(f'{DIR}:|{self.inx:<4}|{self.v_cmd} |{vnow:3.5f}'+' '.join([f'|{v:10.7f}' if v else '|'+'-'*10 for v in (self.dvds,self.coef_2,self.coef_10,self.coef_100) ]))
        
        self.step_count += Nw
        self.inx = self.inx + dir*Nw


    #SPEED CONTROL MODES:
    async def speed_control_off(self):
        while True:
            stc = self.speed_control_mode_changed
            while self.speed_control_mode == 'off' and self.speed_control_mode_changed is stc:
                await self.sleep(0.1)

            await self.speed_control_mode_changed

    async def step_speed_control(self):
        """uses pigpio waves hardware concepts to drive output"""
        print(f'setting up step speed control')
        self._speed_stopped = False
        self._pause_ongoing = False

        await self.pi.write(self._dir_pin,1 if self._last_dir > 0 else 0)
        self.dt_st = 0.005
        while True:
            stc = self.speed_control_mode_changed
            try:        
                while self.speed_control_mode in ['pwm','step'] and self.speed_control_mode_changed is stc:
                    self.ct_st = time.perf_counter()

                    v_dmd = self.v_cmd

                    if v_dmd != 0 and self.is_safe():
                        d_us = max( int(1E6 * self.dz_per_step / abs(v_dmd)) , self.min_dt)
                        steps = True
                    else:
                        steps = False
                        d_us = int(1E5) #no 

                    #determine timing to meet step goal
                    dt = max(d_us,self.min_dt) #div int by 2
                    max_step = (self.control_interval/self.dt_st)

                    #increment pulses to handle async gap
                    inc = min(max(int((1E6*self.dt_st)/d_us),1),max_step)

                    #define wave up for dt, then down for dt,j repeated inc
                    if steps:
                        wave = [asyncpio.pulse(1<<self._step_pin, 0, dt)]
                        wave.append(asyncpio.pulse(0, 1<<self._step_pin, dt))
                        wave = wave*inc
                    else:
                        wave = [asyncpio.pulse(0, 0, dt)]

                    await self.step_wave(wave)
                        
                    self.fail_st = False
                    self.dt_st = time.perf_counter() - self.ct_st
                
                #now your not in use
                print(f'exit step speed control inner loop')
                await self.pi.write(self._step_pin,0)
                await self.speed_control_mode_changed

            except Exception as e:
                #kill PWM
                self.fail_st = True
                print(f'issue in speed step routine {e}')
                await self.pi.write(self._step_pin,0)

    async def speed_pwm_control(self):
        """uses pigpio hw PWM to control pwm dutycycle"""
        print(f'setting pwm speed control')
        self._speed_stopped = False
        self._pause_ongoing = False
        
        self.dt_sc = 0.005
        self.pwm_speed_base = 1000
        self.pwm_speed_freq = 500
        self.pwm_mid = int(self.pwm_speed_base/2)
        self.pwm_speed_k = self.pwm_mid / self.max_speed_motor 

        #Set the appropriate pin config
        a = await self.pi.set_PWM_frequency(self._vpwm_pin,self.pwm_speed_freq)
        assert a == self.pwm_speed_freq, f'bad pwm freq result! {a}'
        b = await self.pi.set_PWM_range(self._vpwm_pin,self.pwm_speed_base)
        assert b == self.pwm_speed_base, f'bad pwm range result! {b}'
        await self.pi.write(self._vpwm_pin,0)

        while True:
            stc = self.speed_control_mode_changed
            try:
                while self.speed_control_mode in ['pwm','step'] and self.speed_control_mode_changed is stc:
                    self.ct_sc = time.perf_counter()
                    
                    #TODO: Set hardware PWM frequency and dutycycle on pin 12. This cancels waves

                    v_dmd = self.v_cmd

                    #set PWM cycle for velocity using
                    if self._speed_stopped and v_dmd == 0:
                        await self.pi.write(self._vpwm_pin,0)
                        await self.sleep(0.1)
                    else:
                        
                        if v_dmd == 0 or v_dmd is None:
                            if self._pause_ongoing is False:
                                self._pause_ongoing = time.perf_counter()

                            elif time.perf_counter()-self._pause_ongoing > 5:
                                print(f'go to zero')
                                self._speed_stopped = True

                        elif v_dmd != 0:
                            self._pause_ongoing = False
                            self._speed_stopped = False

                        dc = self.pwm_mid + (v_dmd*self.pwm_speed_k)
                        await self.pi.set_PWM_dutycycle(self._vpwm_pin,dc)

                    self.fail_sc = False
                    self.dt_sc = time.perf_counter() - self.ct_sc

                #now your not in use
                print(f'exit pwm speed control inner loop')
                await self.pi.write(self._vpwm_pin,0)
                await self.speed_control_mode_changed

            except Exception as e:
                #kill PWM
                self.fail_sc = True
                print(f'issue in pwm speed routine {e}')
                await self.pi.write(self._vpwm_pin,0)
            await self.pi.write(self._vpwm_pin,0)
        
        
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
    sc = stepper_control(4,6,12,7,13,wave=rw)
    sc.setup()
    sc.run() 

# 
#     async def control_io_steps(self):
#         print(f'starting control IO...')
#         self.wave_last = None
#         self.wave_next = None
#         itick = 0
#         printerval = 1000
#         self.dt_io = 0.005 #mseconds typical async
#         while self.is_safe():
#             start_mode = self.mode_changed
#             if self.drive_mode == 'steps':
#                 print(f'starting steps control io')
#                 self._zi_inx_start = self.inx
#                 try: #avoid loop overhead in subloop
#                     while self.is_safe() and start_mode is self.mode_changed:
#                         itick += 1
# 
#                         self.ct_st = time.perf_counter()
#                         #dir set
#                         #determine timing to meet step goal
#                         dt = max(self.step_delay_us,self.min_dt) #div int by 2
#                         max_step = (self.control_interval/self.dt_io)
# 
#                         #increment pulses to handle async gap
#                         inc = min(max(int((1E6*self.dt_io)/self.step_delay_us),1),)
# 
#                         #define wave up for dt, then down for dt,j repeated inc
#                         wave = [asyncpio.pulse(1<<self._step_pin, 0, dt)]
#                         wave.append(asyncpio.pulse(0, 1<<self._step_pin, dt))
#                         wave = wave*inc
# 
#                         ##create the new wave
#                         self.wave_last = self.wave_next                    
#                         await self.pi.wave_add_generic(wave)
#                         self.wave_next = await self.pi.wave_create()
# 
#                         #eat up cycles waiting
#                         if self.wave_last is not None:
#                             #print(f'wave next {self.z_t} {self.v_t} {inc} {self.dir_mult} {self.step_delay_us}| {self.control_io_int}| {inc}| {len(wave)>>1}')
#                             await self.pi.wave_delete(self.wave_last)
#                             while self.wave_last == await self.pi.wave_tx_at():
#                                 #print(f'waiting...')
#                                 pass
#                             await self.pi.wave_send_once(self.wave_next)
#                             await self.pi.write(self._dir_pin,self.dir_mult)
#                             
#                             
#                         else:
#                             #delete last
#                             await self.pi.wave_send_once(self.wave_next)
#                             await self.pi.write(self._dir_pin,self.dir_mult)
# 
#                         #update metrics
#                         self.inx += inc * ( 1 if self.dir_mult else -1 )
#                         self.steps += inc
#                             
#                         #print(self.feedback_volts)
#                         self.fail_io = False
#                         self.dt_io = time.perf_counter() - self.ct_st
# 
#                         if itick >= printerval:
#                             itick = 0
#                             print(f'step dt: {self.dt_io}| {self.step_delay_us}| {self.control_io_int}| {inc}| {len(wave)>>1}')
# 
#                 except Exception as e:
#                     self.fail_io = True
#                     print(f'control io error: {e}')
#                     traceback.print_stack()
#                 
#             await self.mode_changed
# 
#         print(f'control io ending...')
#         await self._stop()