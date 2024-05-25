"""
in which we define motion classes
1. stepper_control: class provides a stepper control based off step/dir concept #TODO
2. motion_control: class provides a high level PWM based interface for speed/torque with position control #TODO
"""
import asyncpio
import asyncio
import time
import traceback
import signal

import json
import threading
import time
import sys,os,pathlib

from waveware.config import *
import random

# Get I2C bus

log = logging.getLogger('cntl')


control_dir = pathlib.Path(__file__).parent

class MovementError(Exception): pass
class StuckError(MovementError): pass
class NoMotion(MovementError): pass



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
dr_inx = 128#860
dr = dr_ref[dr_inx]
min_res = volt_ref[fv_inx]/(2**16/2)
# see https://thecavepearlproject.org/2020/05/21/using-the-ads1115-in-continuous-mode-for-burst-sampling/
low_thres = 0x0000 
high_thres = 0x8000


vmove=vmove_default=[0.0001,0.001]

PR_INT = 1000
    
steps_per_rot = 360/1.8
dz_per_rot = 0.01 #rate commad

class wave_control:
    enabled = False
    wave: regular_wave
    control_interval: float = 10./1000 #valid on linux, windows is 15ms

    kp_zerr = 0.0
    ki_zerr = 0.0
    kd_zerr = 0.0

    
    min_dt = 25
    pulse_dt = 100
    dz_range = 0.3 #meters #TODO: input actual length of lead screw

    adc_addr = 0x48
    t_command = 0 #torque fraction of upper limit 0-1

    def __init__(self, dir:int,step:int,speed_pwm:int,fb_an_pin:int,hlfb:int,torque_pwm,motor_en_pin,pi=None,**conf):
        """This class represents an A4988 stepper motor driver.  It uses two output pins
        
        for direction and step control signals."""
        #setup drive mode first
        self.drive_mode = 'stop'
        self.mode_changed = asyncio.Future()
        self.set_mode('stop')# #always start in calibration mode

        self.force_cal =  conf.get('force_cal',False)
        self.wave = conf.get('wave',regular_wave())
        self.steps_per_rot = conf.get('steps_per_rot',steps_per_rot)
        self.dz_per_rot = conf.get('dz_per_rot',dz_per_rot)
        #self.on_time_us = 25 #us
        self.dz_per_step = self.dz_per_rot / self.steps_per_rot


        self.max_speed_motor = 0.5 #TODO: get better motor constants
                
        self.stopped = True
        self._motor_en_pin = motor_en_pin
        self._dir_pin = dir
        self._step_pin = step
        self._vpwm_pin = speed_pwm
        self._tpwm_pin = torque_pwm
        self._adc_feedback_pin = fb_an_pin
        self._hlfb = hlfb

        self.dt_sc = 0.005
        self.pwm_speed_base = 1000
        self.pwm_speed_freq = 500        
        
        #TODO: setup high/low interrupt on hlfb for ppr or torque / speed ect

        #setup pi if one isn't provided
        #FIXME; cant print un-connected pi
        if pi is None:
            pi = asyncpio.pi()
            log.info(f'control making pi: {type(pi)}|{id(pi)}')
            self.pi = pi
        else:
            log.info(f'adding pi: {type(pi)}|{id(pi)}')
            self.pi = pi

        self.reset()

        
    
    def reset(self):
        #fail setupso
        self.enabled = False
        self._control_modes = {}
        self._control_mode_fail_parms = {'stop':False,
                                        'center':False,
                                        'cal':False,
                                        'wave':False}

        self.speed_control_mode = default_speed_mode
        self.mode_changed = None
        self.speed_control_mode_changed = None
        self.first_feedback = None

        self._last_dir = 1
        self.feedback_volts = None
        self.fail_feedback = None

        self.fail_st = False
        self.fail_sc = False
        self.v_cmd =v= 0
        self.v_cur =v= 0
        self.v_sup = 0
        self.v_wave = 0
        self.z_cmd = 0
        self.z_cur = 0
        self.z_est = 0

        self.wave_last = None
        self.wave_next = None

        #TODO: redo calibration system
        c0 = -0.0001

        self.err_int = 0
        self.dt = 0
        self.inx = 0
        self.coef_2 = c0
        self.coef_10 = c0
        self.coef_100 = c0
        self._coef_2 = c0
        self._coef_10 = c0
        self._coef_100 = c0        
        self.dvdt_2 = 0
        self.dvdt_10 = 0
        self.dvdt_100 = 0        
        self.z_err_cuml = 0

        tol = 0.25
        self.v_active_tol = 0.1
        self.act_max_speed = LABEL_DEFAULT['vz-max']
        
        self.v_max = 3.3
        self.v_min = 0
        self.zero_frac = 0.5
        self.lower_frac = 0.33
        self.upper_frac = 0.66
        self.upper_v = self.v_max - tol
        self.lower_v = tol
        self.vref_0 = (self.upper_v + self.lower_v)*self.zero_frac

        self.update_const()  

    #SETUP 
    async def _setup(self):


        if ON_RASPI:
            if not hasattr(self,'pi') or not isinstance(self.pi,asyncpio.pi):
                log.info(f'making pi last sec')
                self.pi = asyncpio.pi()
            if not hasattr(self.pi,'connected'):
                con = await self.pi.connect()
                self.pi.connected = True
                log.info(f'PI Connection Res: {con}')

            await self.pi.set_mode(self._motor_en_pin,asyncpio.OUTPUT)
            await self.pi.set_mode(self._dir_pin,asyncpio.OUTPUT)
            await self.pi.set_mode(self._step_pin,asyncpio.OUTPUT)
            await self.pi.set_mode(self._tpwm_pin,asyncpio.OUTPUT)
            await self.pi.set_mode(self._vpwm_pin,asyncpio.OUTPUT)

            await self.pi.set_mode(self._hlfb,asyncpio.INPUT)
            await self.pi.set_mode(self._adc_feedback_pin,asyncpio.INPUT)

            await self.pi.write(self._motor_en_pin,0)
            await self.pi.write(self._dir_pin,0)
            await self.pi.write(self._step_pin,0)
            await self.pi.write(self._tpwm_pin,0)
            await self.pi.write(self._vpwm_pin,0)
            log.info(f'raspi setup!')   



    def setup(self,i2c=False,cntl=False):
        self.start = time.perf_counter()
        loop = asyncio.get_event_loop()

        self.feedback_task = loop.create_task(self.feedback())
        self.feedback_task.add_done_callback(check_failure('feedbck task'))

        if i2c:
            self.setup_i2c()

        if cntl:
            #requires i2c, but that can be set in outer fw
            self.setup_control()            

        self.speed_control_mode = default_speed_mode

        self.mode_changed = asyncio.Future()
        self.speed_control_mode_changed = asyncio.Future()    

        loop.run_until_complete(self._setup())    

    def set_speed_tasks(self):
        #SPEED CONTROL MODES
        loop = asyncio.get_event_loop()
        self.start = time.perf_counter()
        
        if DEBUG: log.info(f'set tasks ex feedback / speed / pwm & steps')

        self.speed_off_task = loop.create_task(self.speed_control_off())
        self.speed_off_task.add_done_callback(check_failure( 'speed off tsk'))

        self.speed_pwm_task = loop.create_task(self.speed_pwm_control())
        self.speed_pwm_task.add_done_callback(check_failure('speed pwm tsk'))

        self.speed_step_task = loop.create_task(self.step_speed_control())
        self.speed_step_task.add_done_callback(check_failure('speed steps'))
                    

    #RUN / OPS
    def run(self,vmove=0.001):
        """run program without interactive ensuring that calibration occurs first"""
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.start_control())
        self.first_feedback = d = asyncio.Future()

        self.set_speed_tasks()

        def go(*args,docal=True,**kw):
            nonlocal self, loop
            self.start = time.perf_counter()
            log.info(f'feedback OK. cal = {docal}')
            self.set_mode('center')
            
        self.first_feedback.add_done_callback(go)

        try:
            loop.run_forever()

        except KeyboardInterrupt as e:
            log.info("Caught keyboard interrupt. Canceling tasks...")
            self.stop()
            sys.exit(0)
        finally:
            loop.close()



    #STOPPPING / SAFETY
    #TODO: Enable here is for the clearpath motor, A4899 stepper enable is active. low
    #External Control Methods
    async def enable_control(self):
        log.info('enable control')
        if not self.enabled:
            if ON_RASPI:
                val = await self.pi.write(self._motor_en_pin,1)
            self.enabled = True
        else:
            log.info(f'already enabled!')

    async def start_control(self):
        self.start = time.perf_counter()
        await self.enable_control()
        if self.enabled and self.stopped:
            self.set_speed_tasks()
            self.stopped = False
            await asyncio.sleep(1)
        elif not self.stopped:
            log.info(f'already started!!')
        elif not self.enabled:
            log.info(f'not enabled!')

    async def disable_control(self):
        log.info('disabiling motor!')
        if ON_RASPI:
            await self.pi.write(self._motor_en_pin,0) #disable force
        self.enabled = False

    async def stop_control(self):
        await self.disable_control()
        await self._stop()

    def stop(self):
        loop = asyncio.get_event_loop()
        if loop.is_running:
            loop.call_soon(self._stop)
        else:
            loop.run_until_complete(self._stop())     
            loop.run_until_complete(self._close())
        self.stopped = True

    async def _stop(self):
        if DEBUG: log.info(f'task stop')
        self.stopped = True
        await self.sleep(0.1)

        self.set_mode('stop')

        if hasattr(self,'speed_off_task') and not self.speed_off_task.cancelled:
            self.speed_off_task.cancel()
        
        if hasattr(self,'speed_pwm_task') and not self.speed_pwm_task.cancelled:
            self.speed_pwm_task.cancel()

        if hasattr(self,'speed_step_task') and not self.speed_step_task.cancelled:
            self.speed_step_task.cancel()

        await self.sleep(0.1)
        if ON_RASPI:

            #Set PWM Drive off
            log.info(f'setting pwm off')
            try:
                pt = await self.pi.set_PWM_dutycycle(self._vpwm_pin,0)
                #vpt = await self.pi.write(self._vpwm_pin,0)
                vt = await self.pi.set_PWM_dutycycle(self._tpwm_pin,0)
                #tp = await self.pi.write(self._tpwm_pin,0)
            except Exception as e:
                log.info(f'exception turning off pwm: {e}')      

            log.info(f'setting steps off')
            try:
                sp =await self.pi.write(self._step_pin,0)
                dp = await self.pi.write(self._dir_pin,0)
            except Exception as e:
                log.info(f'exception turning off steps: {e}')             

            

            await self._close(stop=False)

            await self.sleep(0.1)           

    async def _close(self,stop=True):
        try:
            await self.pi.wave_tx_stop()
        except Exception as e:
            log.info(f'pigpio wavestop error: {e}')
        
        try:
            await self.pi.wave_clear()
        except Exception as e:
            log.info(f'pigpio close error: {e}')                

        time.sleep(1)
        if stop: await self.pi.stop()


    # async def exec_cb(self,exc,loop):
    #     log.info(f'got exception: {exc}| {loop}')
    #     await self._stop()
    #     #sys.exit(1) #os.kill(os.getpid(), signal.SIGKILL)


    
    def setup_i2c(self,cv_inx = 0,smb=None,lock=None):
        if smb is None:
            self.smbus = smbus.SMBus(1)
        else:
            self.smbus = smb

        if lock is None:
            self.i2c_lock = threading.Lock()
        else:
            self.i2c_lock = lock

        try:
            cb = config_bit(cv_inx,fvinx = 4)
            db = int(f'{dr}00011',2)
            data = [cb,db]
            #do this before reading different pin, 
            log.info(f'setting adc to: {[bin(d) for d in data]}')
            with self.i2c_lock:
                self.smbus.write_i2c_block_data(0x48, 0x01, data)
            #setup alert pin!
            #self.smbus.write_i2c_block_data(0x48, 0x02, [0x00,0x00])
            #self.smbus.write_i2c_block_data(0x48, 0x03, [0x80,0x00])
            self.adc_ready = True

        #TODO: handle i2c failure and restart or reattempt

        except Exception as e:
            log.error('issue setting up temp',exc_info=e)
            self.adc_ready = False        

    def is_safe(self):
        #base = any((self._control_mode_fail_parms.values()))
        base = False
        if self.drive_mode in self._control_mode_fail_parms:
            base = self._control_mode_fail_parms[self.drive_mode]
        else:
            log.warning(f'no drivemode found: {self.drive_mode}')
        return all([not base,
                    not self.fail_sc,
                    not self.fail_st])
    
    def set_mode(self,new_mode):
        log.info(f'setting mode: {new_mode}')
        new_mode = new_mode.strip().lower()
        assert new_mode in drive_modes,f'bad drive mode {new_mode}! choose: {drive_modes}'
        new_mode = new_mode.lower().strip()

        if new_mode == self.drive_mode:
            if DEBUG: log.info(f'same drive mode: {new_mode}')
            if new_mode == 'stop':
                self.v_cmd = 0
            else:
                self.start = time.perf_counter()
            return
        
        self.drive_mode = new_mode
        log.info(f'set mode: {self.drive_mode}')
        if hasattr(self,'mode_changed'):
            self.mode_changed.set_result(new_mode)
        self.mode_changed = asyncio.Future()
    
    def set_speed_mode(self,new_mode):
        new_mode = new_mode.strip().lower()
        assert new_mode in speed_modes,f'bad speed mode {new_mode}! choose: {speed_modes}'
        new_mode = new_mode.lower().strip()
        if new_mode == self.speed_control_mode:
            log.info(f'same speed mode: {new_mode}')
            return
        
        self.speed_control_mode = new_mode
        log.info(f'setting speed mode: {self.speed_control_mode}')
        if hasattr(self,'speed_control_mode_changed'):
            self.speed_control_mode_changed.set_result(new_mode)
        self.speed_control_mode_changed = asyncio.Future()        

    def make_control_mode(self,mode,loop_function):
        loop = asyncio.get_event_loop()
        #make the loop task
        func = self.control_mode(loop_function,mode)
        
        
        #task.add_done_callback #TODO: handle failures
        self._control_modes[mode]=None #not started
        self._control_mode_fail_parms[mode] = False

        def _fail_control(res):
            log.info(f'mode done! {mode}')
            try:
                res.result()
            
            except MovementError:
                self.v_cmd = 0
                loop.run_until_complete(self.run_stop())
                self.set_speed_mode('stop')

            except Exception as e:
                traceback.print_exception(e)

        #def on_start(*res):
        task = loop.create_task(func)
        self._control_modes[mode]=task
        #setattr(self,tsk_name,task)
        #self.started.add_done_callback(on_start)
        task.add_done_callback(_fail_control)
        return task
        



    def setup_control(self):
        log.info('starting...')
        assert self.adc_ready, f'cannot run without feedback!'

        loop = asyncio.get_event_loop()
        self.set_mode('stop')
        self.started = asyncio.Future()
        

        self.goals_task = self.make_control_mode('wave',self.wave_goal)
        self.stop_task = self.make_control_mode('stop',self.run_stop)
        self.center_task = self.make_control_mode('center',self.center_head)


    #FEEDBACK & CONTROL TASKS
    async def feedback(self,feedback_futr=None):
        log.info(f'starting feedback!')
        self.dvds = None
        VR = volt_ref[fv_inx]
        

        #TODO: get interrupt working, IO error on read, try latching?
        # self._adc_feedback_pin_cb = asyncio.Future()
        # def trigger_read(gpio,level,tick):
        #     adc = self._adc_feedback_pin_cb
        #     adc.set_result(tick)
        #     self._adc_feedback_pin_cb = asyncio.Future()
        #     
        # 
        # await self.pi.callback(self._adc_feedback_pin,asyncpio.FALLING_EDGE,trigger_read)

        tlast = tnow = time.perf_counter() - self.start
        
        self.z_cur = self.wave.z_pos(tnow)
        self.v_wave = self.wave.z_vel(tnow)
        vdtlast = vdtnow = self.v_command
        vlast = vnow = self.feedback_volts #prep vars


        while ON_RASPI:
                  
            try:
                while True:
                    tlast = tnow #push back
                    vdtlast = vdtnow
                    vlast = vnow if vnow is not None else 0
                    st_inx = self.inx
                    wait = wait_factor/float(dr_inx)
                    
                    #TODO: add feedback interrupt on GPIO7
                    #-await deferred, in pigpio callback set_result
                    #tick = await self._adc_feedback_pin_cb
                    await self.sleep(wait)
                    
                    try:
                        with self.i2c_lock:
                            data = self.smbus.read_i2c_block_data(0x48, 0x00, 2)
                        raw_adc = data[0] * 256 + data[1]
                        if raw_adc > 32767:
                            raw_adc -= 65535

                        self.feedback_volts = vnow = (raw_adc/32767)*VR
                        self.z_cur = (vnow - self.safe_vref_0)*self.dzdvref

                        if feedback_futr is not None:
                            feedback_futr.set_result(True)
                            feedback_futr = None #twas, no more                
                        #ok!
                        self.fail_feedback = False

                    except Exception as e:
                        log.info('read i2c issue',e)
                        continue
                    
                    # Convert the data
                    vdtnow = self.v_command
                    tnow = time.perf_counter() - self.start

                    kw = dict(tlast=tlast,vdtlast=vdtlast,vlast=vlast,st_inx=st_inx,vnow=vnow)
                    self.calc_rates(vdtnow,tnow,**kw)

            except Exception as e:
                self.fail_feedback = True
                log.info(f'control error: {e}')       
                traceback.print_tb(e.__traceback__)

        log.warning(f'NO FEEDBACK!!!!')           

    def calc_rates(self,vdtnow,tnow,**kw):
        vnow = kw.get('vnow')
        vlast = kw.get('vlast')
        tlast = kw.get('tlast')
        vdtlast = kw.get('vdtlast')
        st_inx = kw.get('st_inx')
        dv = (vnow-vlast)
        self.dt = dt = (tnow-tlast)
        accel = (vdtnow -vdtlast)/dt #speed
        self.z_est = self.z_est + vdtnow*dt+0.5*accel*dt**2

        #calc dynamic rates
        self.dvdt = vdir_bias*dv / dt
        self.dvdt_2 = (self.dvdt_2 + self.dvdt)/2
        self.dvdt_10 = (self.dvdt_10*0.9 + self.dvdt*0.1)
        self.dvdt_100 = (self.dvdt_100*0.99 + self.dvdt*0.01)

        #measured
        self.v_cur = self.dvdt_10*self.dzdvref

        #TODO: determine stationary
        
        Nw = abs(int(self.inx - st_inx))
        
        #stop catching
        if self.v_command == 0:
            return #dont determine rates as vcmd = 0

        elif Nw < 1:
            #no steps, no thank you
            return
        
        #increment measure if points exist
        self.t_no_inst = False
        self.dvds = dv/((self._last_dir*Nw))
        self._coef_2 = (self._coef_2 + self.dvds)/2
        self._coef_10 = (self._coef_10*0.9 + self.dvds*0.1)
        self._coef_100 = (self._coef_100*0.99 + self.dvds*0.01)


    #CONTROL MODES
    async def control_mode(self,loop_function:callable,mode_name:str):
        """runs an async function that sets v_cmd for the speed control systems"""
        log.info(f'creating control {mode_name}|{loop_function.__name__}...')
        
        while True:
            start_mode = self.mode_changed

            if (isinstance(mode_name,str) and self.drive_mode == mode_name) or (isinstance(mode_name,(list,tuple)) and self.drive_mode in mode_name):
                log.info(f'starting control {mode_name}|{loop_function.__name__}...')
                try: #avoid loop overhead in subloop
                    while self.is_safe() and start_mode is self.mode_changed:
                        await loop_function() #continuously call zit
                        self._control_mode_fail_parms[mode_name] = False
                    if not self.is_safe():
                        log.warning(f'no longer safe, exiting {mode_name} control')
                        await self._stop()
                except Exception as e:
                    self._control_mode_fail_parms[mode_name] = True
                    log.info(f'control {mode_name} failure|{loop_function.__name__} error: {e}')
                    task = asyncio.current_task()
                    traceback.print_tb(e)
            
            #if your not the active loop wait until the mode has changed to check again. Only one mode can run at a time
            await self.mode_changed

        log.warning(f'control io ending...')
        await self._stop()

    #Control
    async def pid_control(self,v_goal):
        
        fv = self.feedback_volts
        err = fv - v_goal

        #TODO: integral windup prevention
        self.err_int = self.err_int + err*self.dt

        Vp = err * self.kp_zerr
        Vi = self.err_int * self.ki_zerr
        Vd = self.dvdt_10 * self.kd_zerr

        self.v_cmd = Vp #+Vi+Vd

        await self.sleep(self.control_interval)

        return err

    async def center_head(self,find_tol = 0.01,set_mode=False):
        err = await self.pid_control(self.safe_vref_0)

        if set_mode is not False and abs(err)<find_tol:
            self.set_mode(set_mode)
            return
        
    async def wave_goal(self):
        ###constantly determines
        t = time.perf_counter() - self.start
        v_goal = self.hwave_to_v(self.wave.z_pos(t))
        err = await self.pid_control(v_goal)

    #Wave Control Goal
    async def set_dir(self,dir=None):
        if dir is None:
            dir = self._last_dir
        else:
            self._last_dir = dir
        await self.pi.write(self._dir_pin,1 if dir > 0 else 0)

    async def run_stop(self):
        self.v_cmd = 0   
        await self.sleep(self.control_interval)
                    

    #Saftey & FEEDBACK
    #safe bounds and references
    def update_const(self):
        self.dz_per_step = self.dz_per_rot / self.steps_per_rot
        self.dvref_range = self.upper_v - self.lower_v
        log.info(f'setting dzdv = {self.dz_range} <> [3.3/{self.dvref_range}]')
        self.dzdvref = self.dz_range/(self.v_max - self.v_min)

    def hwave_to_v(self,h_in):
        da = h_in/self.dz_range
        dvf = da * (self.v_max - self.v_min)

        ul = self.upper_v - self.lower_v
        vu = ul * self.upper_frac + self.lower_v
        vl = ul * self.lower_frac + self.lower_v        

        return min(max(dvf,vl),vu)


    @property
    def feedback_pct(self):
        fb = self.feedback_volts
        return (fb - self.lower_v)/ (self.upper_v - self.lower_v)

    @property
    def safe_upper_v(self):
        ul = self.upper_v - self.lower_v
        return ul * self.upper_frac + self.lower_v
    
    @property
    def safe_lower_v(self):
        ul = self.upper_v - self.lower_v
        return ul * self.lower_frac + self.lower_v
    
    @property
    def safe_range(self):
        return (int(self.lower_frac*100),int(self.upper_frac*100))
    
    @safe_range.setter
    def safe_range(self,inv):
        lv,uv = inv
        ck,lvs,uvs = editable_parmaters['z-range']
        #dont allow zero cross
        self.lower_frac = min(max(int(lv),lvs),50)/100.
        self.upper_frac = min(max(int(uv),50),uvs)/100.
            
    @property
    def safe_vref_0(self):
        ul = self.upper_v - self.lower_v
        lv = ul * self.lower_frac
        uv = ul * self.upper_frac
        return (uv-lv) * self.zero_frac + self.lower_v
    
    @property
    def vz0_ref(self):
        return int(self.zero_frac*100)

    @vz0_ref.setter
    def vz0_ref(self,inv):
        ck,lv,uv = editable_parmaters['z-ref']
        self.zero_frac = min(max(int(inv),lv),uv)/100.


    #to handle stepping controls
    def make_wave(self,pin,dt,dc:float=None,mindt:int=None,inc=1,dt_span=None):
        """if dc provided, dt_on=dt*dc and dt_off=dt*(1-dc), otherwise t_on=min_dt and t_off=dt-min_dt
        use dt_span to determine number of incriments max((dt_span/dt),1)
        if dt_span not specified a multiplier number of times via inc=10, for 10 waves. 
        """
        if mindt is None:
            mdt = self.pulse_dt
            mindt = self.min_dt

        if dt_span is not None:
            inc = min(max(int(dt_span/dt),1),1600) #socket limit otherwise
        
        assert dt > mindt, f'dt {dt} to small for min_dt {mdt}'

        if dc is None:
            toff = int(dt-mdt)
            ton = int(mdt)
            #log.info(ton,toff)
            wave = [asyncpio.pulse(1<<pin, 0, ton)]
            wave.append(asyncpio.pulse(0, 1<<pin, max(toff,mdt)))
            return wave*inc
        else:
            #duty cycle
            #log.info('dc',dc)
            wave = [asyncpio.pulse(1<<pin, 0, max(int(dt*dc),mdt))]
            wave.append(asyncpio.pulse(0, 1<<pin, max(int(dt*(1-dc)),mdt)))
            return wave*inc            


    async def step_wave(self,wave,dir=None):
        """places waveform on pin with appropriate callbacks, waiting for last wave to finish before continuing"""
        Nw = int(len(wave)/2)

        if dir is None:
            dir = self._last_dir

        if Nw > 0:
            self.wave_last = self.wave_next #push back
            #log.info(dir,len(wave))
            if self.wave_last is not None:
                
                sttime = await self.pi.wave_get_micros()
                
                if sttime > self.min_dt:
                    millis = int(sttime/1000)
                    if millis > 10: #asyncio can reliably do 1ms on
                        sttime = 10000 #10ms remaining
                        await self.sleep(max((millis-10)/1000,0.01))
                    
                    #Delay time
                    wave = [asyncpio.pulse(0, 0, sttime)] + wave
                
                try:
                    await self.pi.wave_add_generic(wave)
                    self.wave_next = await self.pi.wave_create()                
                    await self.pi.wave_send_once( self.wave_next)
                
                    while self.wave_last == await self.pi.wave_tx_at():
                        #log.info(f'waiting...')
                        await asyncio.sleep(0)

                except Exception as e:
                    log.info(f'wave create error: {e}| {self.wave_next}| {self.wave_next}| Np: {len(wave)}')
                    #wait on last wave
                    while self.wave_last == await self.pi.wave_tx_at():
                        await asyncio.sleep(0)  #1ms

                try:
                    await self.pi.wave_delete(self.wave_last)
                except Exception as e:
                    log.info(f'wave delete error: {e}')
                    pass

            else:
                #do it raw
                ##create the new wave
                await self.pi.wave_add_generic(wave)

                self.wave_next = await self.pi.wave_create()
                await self.pi.wave_send_once( self.wave_next)
            
            #keep tracks
            self.inx = self.inx + dir*Nw
        
        else:
            if self.wave_last:
                while self.wave_last == await self.pi.wave_tx_at():
                    if DEBUG: log.info(f'waiting...')
                    await asyncio.sleep(0.001)  #1ms
            else:
                if DEBUG: log.info(f'no last')
                await asyncio.sleep(0.001)  #1ms

    #SPEED CONTROL MODES:
    @property
    def v_command(self):
        """rate limited speed command"""
        if self.stopped:
            return 0
        
        vdmd = self.v_cmd
        
        #limit max speed
        Kspd = min(self.act_max_speed,abs(vdmd))
        vnew = Kspd*(1 if vdmd > 0 else -1)     
        return vnew   
        
        # v_cur = self.feedback_volts
        # if v_cur is None:
        #     return 0 #wait till feedback
        # 
        # dvl = (self.safe_upper_v-v_cur)
        # dvu = (v_cur-self.safe_lower_v) 
        
        # if dvl < self.v_active_tol or dvu < self.v_active_tol:
        #     Kspd = min(self.act_max_speed,abs(vdmd))
        #     vnew = Kspd*(1 if vdmd > 0 else -1)
        #     #log.info(f'{dvl} {dvu} {v_cur} limiting speed! {vnew} > {vdmd}')
        #     vdmd = vnew
    
    async def speed_control_off(self):
        while True:
            stc = self.speed_control_mode_changed
            while self.speed_control_mode == 'off' and self.speed_control_mode_changed is stc:
                await self.sleep(0.1)

            await self.speed_control_mode_changed


    async def step_speed_control(self):
        """uses pigpio waves hardware concepts to drive output"""
        log.info(f'setting up step speed control')
        if ON_RASPI: 
            await self.pi.write(self._dir_pin,1 if self._last_dir > 0 else 0)

        self.dt_st = 0.005
        self.max_wait = 100000 #0.1s
        it = 0
        while ON_RASPI:
            stc = self.speed_control_mode_changed
            print(f'steps top loop')
            try:        
                while self.speed_control_mode in ['step-pwm','step'] and self.speed_control_mode_changed is stc and not self.stopped:
                    self.ct_st = time.perf_counter()
                    v_dmd = self.v_command

                    if v_dmd != 0 and self.is_safe():
                        d_us = min(max( int(1E6 * self.dz_per_step / abs(v_dmd)) , self.min_dt),self.max_wait)
                        steps = True

                        #set directions
                        if v_dmd < 0 and self._last_dir < 0:
                            log.info(f'set bwk')
                            await self.set_dir(-1*vdir_bias)
                        elif v_dmd > 0 and self._last_dir > 0:
                            log.info(f'set fwd')
                            await self.set_dir(1*vdir_bias)
                        else:
                            log.info(f'v: {v_dmd} dir: {self._last_dir}')

                    else:
                        steps = False
                        d_us = int(self.max_wait) #no 

                    dt = max(d_us,self.min_dt*2) 



                    #define wave up for dt, then down for dt,j repeated inc
                    if steps:
                        if DEBUG or (it%10==0): 
                            log.info(f'steps={steps}| {d_us} | {dt} | {v_dmd} | {self.dz_per_step}')
                        waves = self.make_wave(self._step_pin,dt=dt,dt_span=int(self.dt_st*1E6))
                    else:
                        if DEBUG or (it%5000==0): 
                            log.info(f'no steps')
                        waves = [asyncpio.pulse(0, 1<<self._step_pin, dt)]

                    #print('waiting steps')
                    res = await self.step_wave(waves)

                    self.fail_st = False
                    self.dt_st = time.perf_counter() - self.ct_st
                    
                    it += 1

                #now your not in use
                log.info(f'exit step speed control inner loop')
                
                if ON_RASPI: 
                    await self.pi.write(self._step_pin,0)
                await self.speed_control_mode_changed

            except Exception as e:
                #kill PWM
                self.fail_st = True
                log.info(f'issue in speed step routine {e}')
                traceback.print_tb(e.__traceback__)
                if ON_RASPI: await self.pi.write(self._step_pin,0)


    async def setup_pwm_speed(self):
            log.info(f'setting up PWM Speed Mode')
            o = await self.pi.set_mode(self._vpwm_pin,asyncpio.OUTPUT)
            a = await self.pi.set_PWM_frequency(self._vpwm_pin,self.pwm_speed_freq)
            assert a == self.pwm_speed_freq, f'bad pwm freq result! {a}'
            b = await self.pi.set_PWM_range(self._vpwm_pin,self.pwm_speed_base)
            assert b == self.pwm_speed_base, f'bad pwm range result! {b}'
            await self.pi.write(self._vpwm_pin,0) #start null
            
            #Torque Control Pins
            a = await self.pi.set_PWM_frequency(self._tpwm_pin,self.pwm_speed_freq)
            assert a == self.pwm_speed_freq, f'bad pwm freq result! {a}'
            b = await self.pi.set_PWM_range(self._tpwm_pin,self.pwm_speed_base)
            assert b == self.pwm_speed_base, f'bad pwm range result! {b}'
            await self.pi.write(self._tpwm_pin,0) #start null          

    async def speed_pwm_control(self):
        """uses pigpio hw PWM to control pwm dutycycle"""
        #TODO: Set hardware PWM frequency and dutycycle on pin 12. This cancels waves
        log.info(f'setting pwm speed control')
        self.pwm_mid = int(self.pwm_speed_base/2)
        self.pwm_speed_k = self.pwm_mid / self.max_speed_motor 

        #PWM Frequency
        exited = True
        if ON_RASPI: 
            await self.setup_pwm_speed()
            exited = False

        log.info(f'PWM freq: {self.pwm_speed_freq} | range: {self.pwm_speed_base}')
        dc = 0
        it = 0
        maxit = self.pwm_speed_base-1
        while ON_RASPI:
            stc = self.speed_control_mode_changed
            await self.setup_pwm_speed()
            try:
                while self.speed_control_mode in ['pwm','step-pwm'] and self.speed_control_mode_changed is stc and not self.stopped:
                    self.ct_sc = time.perf_counter()

                    v_dmd = self.v_command

                    # if exited and v_dmd != 0:
                    #     await self.setup_pwm_speed()        
                    #     exited = False

                    dc = max(min(int(self.pwm_mid + (v_dmd*self.pwm_speed_k)),maxit),1)
                    await self.pi.set_PWM_dutycycle(self._vpwm_pin,dc)


                    # if DEBUG and (it%PR_INT==0): 
                    #     log.info(f'cntl speed: {v_dmd} | {dc} | / {self.pwm_speed_base}')

                    #TORQUE PWM
                    tdc = max(min(int(self.t_command*1000),1000-10),0)
                    if tdc == 0:
                        await self.pi.write(self._tpwm_pin,0)
                    else:
                        await self.pi.set_PWM_dutycycle(self._tpwm_pin,tdc)

                    self.fail_sc = False
                    self.dt_sc = time.perf_counter() - self.ct_sc
                    
                    it += 1

                #now your not in use
                exited = True
                log.info(f'exit pwm speed control inner loop')
                await self.pi.write(self._vpwm_pin,0)
                await self.speed_control_mode_changed

            except Exception as e:
                #kill PWM
                self.fail_sc = True
                log.info(f'issue in pwm speed : {dc} routine {e}')
                traceback.print_tb(e.__traceback__)
                #Set the appropriate pin config
                a = await self.pi.set_PWM_frequency(self._vpwm_pin,self.pwm_speed_freq)
                assert a == self.pwm_speed_freq, f'bad pwm freq result! {a}'
                b = await self.pi.set_PWM_range(self._vpwm_pin,self.pwm_speed_base)
                assert b == self.pwm_speed_base, f'bad pwm range result! {b}'
                await self.pi.write(self._vpwm_pin,0) #start null

        if ON_RASPI:
            #turn off safely
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
    sc = wave_control(4,6,12,7,13,11,10,19,wave=rw,force_cal='-fc' in sys.argv)
    sc.setup(i2c=True,cntl=True)
    sc.run() 
