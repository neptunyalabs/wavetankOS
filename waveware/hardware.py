"""Module to control and gather data from raspberry system

#Motion Demand:
#Hs - significant wave height run
#Ts - significant wave period

#Data Input / Record:
#waterlevel - height from bottom
#comment 

#Calibration
#z_ref - test_reference point in absolute space

Control:
#mode 1: stepper position / velocity control
#mode 2: two position toggle
#enable - 1/0
#Ach - dir
#Bch - step

Data Aquired:
#t - time relative to start time
#Pa - atmospheric pressure (I2C)
#Ta - atmospheric temp (I2C)
#H_xi - wave height measured at distance xi 2-4 (echoPin/GPIO)
#z_pos - current encoder z height minus z_ref (A/B/GPIO)
#z_act - actuator height (ADC)
#ax,ay,az - current accelerations (I2C)
#gx,gy,gz - current gyro (I2C)
#hlfb - PPR / PWM speed (GPIO)

# DATA STORAGE:
Store Data in key:value pandas format in queue format
all items will have a `timestamp` that is use to orchestrate using `after` search, items are moved from the buffer to the cache after they have been processed, with additional calculations.
"""

import asyncio
import threading
import struct

from collections import deque

import sys
import asyncpio
asyncpio.exceptions = True

import pigpio

import datetime
import time
import logging
import json,os
import random


from waveware.control import wave_control
from waveware.data import *
from waveware.config import *


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hw")


FAKE_INIT_TIME = 60.

#SI07 temp sensor registers
HUMIDITY = 0xF5
TEMPERATURE = 0xF3
WRITE_HEATER_LEVEL = 0x51
READ_HEATER_LEVEL = 0x11
WRITE_HEATER_ENABLE = 0xE6
READ_HEATER_ENABLE = 0xE7
_RESET = 0xFE


#These exist to test calibration when not running on RPI
FAKE_BIAS = {
                'e1':0.1*(0.5-random.random()) + 0.2*random.random(),
                'e2':0.1*(0.5-random.random()) + 0.2*random.random(),
                'e3':0.1*(0.5-random.random()) + 0.2*random.random(),
                'e4':0.1*(0.5-random.random()) + 0.2*random.random(),
                'z1':1*(0.5-random.random()),
                'z2':1*(0.5-random.random()),
                'z3':1*(0.5-random.random()),
                'z4':1*(0.5-random.random()),
                }

FakeWaveMass = 2
FakeTorque = 5
Ao = 0.0001
Ah = 0.05
Bo = 0
Bh = 0.1
Zh = 0.1

#TODO: model / predict kinematics
def asub(z):
    if z>=0:
        return 0
    fh = min(abs(z)/Zh,1)
    return Ao*(1-fh) + Ah*fh

def bsub(z):
    if z>=0:
        return 0
    fh = min(abs(z)/Zh,1)
    return Bo*(1-fh) + Bh*fh

def fake_wave_stiffness(z):
    if z >= 0:
        return 0
    ah = asub(z)
    return ah * 1000 * 9.81

def fake_wave_damping(z):
    if z >= 0:
        return 0
    ah = asub(z)
    bh = bsub(z)
    return bh * ah * 1000 * 9.81    

class hardware_control:
    
    #hw access
    pi = None

    #pinout / registers
    encoder_conf: list = None #[{sens:x,},...]
    encoder_pins: list = None  #[(A,B),(A2,B2)...]
    echo_pins: list = None #[1,2,3]
    
    #potentiometer_pin: int = None

    #i2c addr
    mpu_addr: hex = 0x68#0x69 #3.3v
    si07_addr: hex = 0x40
    
    #motor control
    control = None

    #config flags
    title: str
    active = False
    poll_rate = poll_rate
    poll_temp = poll_temp
    window = window

    
    #Data Storage
    buffer: asyncio.Queue
    unprocessed: deque
    cache: ExpiringDict
    active_mpu_cal = False

    #TODO: pins_def
    def  __init__(self,encoder_ch:list,echo_ch:list,dir_pin:int,step_pin:int,speedpwm_pin:int,adc_alert_pin:int,hlfb_pin:int,motor_en_pin:int,echo_trig_pin:int,torque_pwm_pin:int,winlen = 1000,enc_conf = None,cntl_conf=None):
        self.start_time = time.perf_counter()
        self.last_time = None

        self.title = f'Test At {datetime.datetime.now().isoformat()}'

        self.is_fake_init = lambda: True if (time.perf_counter() - self.start_time) <  FAKE_INIT_TIME else False

        self.default_labels = LABEL_DEFAULT
        self.labels = self.default_labels.copy()
        
        #data storage
        self.buffer = asyncio.Queue(winlen)
        self.unprocessed = deque([], maxlen=winlen)
        
        #TODO: move to global
        self.cache = memcache

        self.i2c_lock = threading.Lock()

        self.last = {} #last set of signals for GPIO
        self.record = {} #for i2c values
        self.echo_pins = echo_ch
        self.encoder_pins = encoder_ch
        if enc_conf is None:
            self.encoder_conf = [{'sens':0.005*4}]*len(self.encoder_pins)
        else:
            assert len(enc_conf) == len(self.encoder_pins), f'encoder conf mismatch'
            self.encoder_conf = enc_conf

        self._motor_en_pin = motor_en_pin
        #stepper
        self._dir_pin = dir_pin
        self._step_pin = step_pin
        #clearpath
        self._speedpwm_pin = speedpwm_pin
        self._torque_pwm_pin = torque_pwm_pin
        self._hlfb_pin = hlfb_pin #io HighLevelFeedback
    
        #adc_alert
        self._adc_alert_pin = adc_alert_pin
        self._echo_trig_pin = echo_trig_pin

        if cntl_conf is None: 
            cntl_conf = {} #empty
        
        self.pi = asyncpio.pi()
        self.control = wave_control(self._dir_pin,self._step_pin,self._speedpwm_pin,self._adc_alert_pin,self._hlfb_pin,self._torque_pwm_pin,motor_en_pin,pi=self.pi,**cntl_conf)

    #Run / Setup
    #Setup & Shutdown
    def setup(self):
        if ON_RASPI:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self._setup_hardware())    

        if ON_RASPI:
            self.setup_i2c()
        else:
            self.temp_ready = False
            self.imu_ready = False
            self.control.adc_ready = True

        self.control.setup()

    async def _setup_hardware(self):
        if not hasattr(self.pi,'connected'):
            log.info(f'control connecting to pigpio')  
            con = await self.pi.connect()
            self.pi.connected = True
        await self._start_sensors()
    
    async def _start_sensors(self):
        log.info(f'starting sensors')
        await self.setup_encoder()
        await self.setup_echo_sensors()        
             
    
    def setup_i2c(self):
        log.info(f'setup i2c')
        self.smbus = smbus.SMBus(1)

        #MPU
        self.mpu_cal_file = f"{fdir}/mpu_calib.json"
        try:
            log.info(f'setup mpu9250')
            self.imu = MPU9250.MPU9250(self.smbus, self.mpu_addr)
            log.info(f'mpu9250 begin')
            self.imu.begin()
            log.info(f'mpu9250 config')
            self.imu.setLowPassFilterFrequency("AccelLowPassFilter184")
            self.imu.setAccelRange("AccelRangeSelect2G")
            self.imu.setGyroRange("GyroRangeSelect250DPS")
            if os.path.exists(self.mpu_cal_file):
                log.info(f'loading calibration file!: {self.mpu_cal_file}')
                self.imu.loadCalibDataFromFile(self.mpu_cal_file)  
            self.imu_ready = True
        except Exception as e:
            log.error('issue setting up imu',exc_info=e)
            self.imu_ready = False
            
        try:
            self.control.setup_i2c(smbus=self.smbus,lock=self.i2c_lock)
            self.adc_ready = True
        except Exception as e:
            log.error('issue setting up control i2c',exc_info=e)
            self.adc_ready = False

        try:
            self.smbus.read_i2c_block_data(0x40, 0xE3,2)
            self.temp_ready = True
        except Exception as e:
            log.error('issue setting up temp',exc_info=e)
            self.temp_ready = False
            
        

    def create_sensor_tasks(self):
        """starts asyncio tasks for sensor peripherals"""
        loop = asyncio.get_event_loop()
        if self.imu_ready:
            self.imu_read_task = loop.create_task(self.imu_task())
        if self.temp_ready:
            self.temp_task = loop.create_task(self.temp_task())
        
        self.echo_trigger_task = loop.create_task(self.trigger_task())
        if DEBUG:
            self.print_task = loop.create_task(self.print_data())        

    def run(self):
        
        self.create_sensor_tasks()
        
        time.sleep(0.1) 
        #TODO: check everything ok
        self.control.setup_control()
        self.control.run()

    def stop(self):
        log.info(f'hw stopping')
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._stop())

    async def _stop(self):
        """
        Cancel the rotary encoder decoder.
        """
        log.info(f'hw stopping tasks..')
        for cba in self.cbA:
            await cba.cancel()
        for cbb in self.cbB:
            await cbb.cancel()
        
        #log.info(f'stopping echos')
        for cbr in self._cb_rise:
            await cbr.cancel()
        for cbf in self._cb_fall:
            await cbf.cancel()

        #log.info(f'stopping echos')
        self.imu_read_task.cancel() 
        self.print_task.cancel()
        self.echo_trigger_task.cancel()

    #MPU:
    #Interactive MPU Cal 
    def imu_calibrate(self):
        self.imu.caliberateAccelerometer()
        self.imu.caliberateGyro()
        self.imu.caliberateMagPrecise()
        self.imu.saveCalibDataToFile(self.mpu_cal_file)

    async def mpu_calibration_process(self):
        loop = asyncio.get_event_loop()
        self.active_mpu_cal = True

        try:
            self.setup_std_fake()
            task = asyncio.to_thread(self.imu_calibrate)
            task.add_done_callback(self.reset_std_in)
            for i in range(6):
                #TODO: add user control here vs 10 second blocks
                w = 10*(i + 1)
                loop.call_later(w,self.reset_stdin)
            await task
        except Exception as e:
            log.info('issue with mpu cal: {e}')
        
        if hasattr(self,'_old_stdin'):
            self.reset_std_in()

        self.active_mpu_cal = False

    def reset_stdin(self):
        self.wt.write('go\r\n'.encode())
        #do it live!
        self.wt.flush() 
        self.rt.flush()

    def setup_std_fake(self):
        r, w = os.pipe()
        self.rd = os.fdopen(r, 'rb')
        self.wt = os.fdopen(w, 'wb')
        self._old_stdin = sys.stdin
        sys.stdin = self.rd #this is what calibrateAccelerometer for input!

    def reset_std_in(self):
        log.info('reset stdin')
        sys.stdin = self._old_stdin
        del self._old_stdin

    async def imu_task(self):
        log.info(f'starting imu task')
        while ON_RASPI:
            try:
                await asyncio.to_thread(self._read_imu)
                await asyncio.sleep(self.poll_rate)
            except Exception as e:
                log.info(f'imu error: {e}')

    def _read_imu(self):
        """blocking call use in thread"""
        
        with self.i2c_lock:
            ts = time.perf_counter()
            self.imu.readSensor()
            #self.imu.computeOrientation()
        
        imu = self.imu
        ax,ay,az = imu.AccelVals[0], imu.AccelVals[1], imu.AccelVals[2]
        gx,gy,gz = imu.GyroVals[0], imu.GyroVals[1], imu.GyroVals[2]
        mx,my,mz = imu.MagVals[0], imu.MagVals[1], imu.MagVals[2]
        dct = dict(ax=ax,ay=ay,az=az,gx=gx,gy=gy,gz=gz,mx=mx,my=my,mz=mz,imutime=ts)
        self.record.update(dct)

    #TEMP Sensors
    async def temp_task(self):
        log.info(f'starting temp task')
        while ON_RASPI:
            try:
                await asyncio.to_thread(self._read_temp)
                await asyncio.sleep(self.poll_temp)
            except Exception as e:
                log.info(f'temp error: {e}')

    def _read_temp(self) -> None:
        log.info(f'read temp')
        #signal to read
        try:
            with self.i2c_lock:
                temp = self.smbus.read_i2c_block_data(0x40, 0xE3,2)
            #what really happens here is that master sends a 0xE3 command (measure temperature, hold master mode) and read 2 bytes back
            time.sleep(0.1)

            # Convert the data
            cTemp = ((temp[0] * 256 + temp[1]) * 175.72 / 65536.0) - 46.85
            self.record['temp'] = cTemp
            if cTemp > -50 and cTemp < 60:
                #no phoney baloney
                self.speed_of_sound = 20.05 * (273.16 + cTemp)**0.5
                self.sound_conv = self.speed_of_sound *1000 / 2000000 #2x

        except Exception as e:
            log.info(e)


    #Encoders
    async def setup_encoder(self):
        enccb = {}
        self.cbA = []
        self.cbB = []
        for i,(apin,bpin) in enumerate(self.encoder_pins):
            log.info(f'setting up encoder {i} on A:{apin} B:{bpin}')
            await self.pi.set_mode(apin, pigpio.INPUT)
            await self.pi.set_mode(bpin, pigpio.INPUT)

            await self.pi.set_pull_up_down(apin, pigpio.PUD_UP)
            await self.pi.set_pull_up_down(bpin, pigpio.PUD_UP)

            ee = pigpio.EITHER_EDGE

            self.last[apin] = 0
            self.last[bpin] = 0
            enccb[i] = self._make_pulse_func(apin,bpin,i)
            self.cbA.append(await self.pi.callback(apin, ee , enccb[i]))
            self.cbB.append(await self.pi.callback(bpin, ee , enccb[i]))

    def _make_pulse_func(self,apin,bpin,inx):
        """function to scope lambda"""
        enc_inx = f'enc_{inx}_last_pin'
        cbinx = f'pos_enc_{inx}'
        self.last[cbinx] = 0 #initalizes
        self.last[enc_inx] = 0 #
        sens = self.encoder_conf[inx]['sens']
        def cb(step):
            nxt = self.last[cbinx] + step*sens
            self.last[cbinx] = nxt
        f = lambda *args: self._pulse(*args,apin=apin,bpin=bpin,enc_inx=enc_inx,cb=cb)
        return f
        
    def _pulse(self, gpio, level, tick,apin,bpin,enc_inx,cb):
        self.last[gpio] = level

        if gpio != self.last[enc_inx]: # debounce
            self.last[enc_inx] = gpio
            if gpio == apin and level == 1:
                if self.last[bpin] == 1:
                    cb(1) #forward step
                    
            elif gpio == bpin and level == 1:
                if self.last[apin] == 1:
                    cb(-1) #reverse step

    #SONAR:
    async def setup_echo_sensors(self):
        """setup GPIO for reading from a list of sensor pins"""
        
        self.speed_of_sound = 343.0 #TODO: add temperature correction
        self.sound_conv = self.speed_of_sound *1000 / 2000000 #2x #to mm

        self._cb_rise = []
        self._cb_fall = []
        for i,echo_pin in enumerate(self.echo_pins):
            log.info(f'starting ecno sensors {i+1} on pin {echo_pin}')

            self.last[echo_pin] = {'dt':0,'rise':None}

            await  self.pi.set_mode(echo_pin, asyncpio.INPUT)

            self._cb_rise.append(await self.pi.callback(echo_pin, asyncpio.RISING_EDGE, self._rise))
            self._cb_fall.append(await self.pi.callback(echo_pin, asyncpio.FALLING_EDGE, self._fall))

    async def trigger_task(self,rate=0.1):
        #TODO: set a repeating waveform on trigger pin 20us on
        delay = int(rate*1E6)
        pulse_us = 50
        doff = delay-pulse_us
        trigger_100ms = [asyncpio.pulse(1<<self._echo_trig_pin,0,pulse_us),
                     asyncpio.pulse(0,1<<self._echo_trig_pin,doff)]
        log.info(f'running trigger on pin: {self._echo_trig_pin} | {pulse_us}us@1 > {doff}us@0')
        await self.pi.set_mode(self._echo_trig_pin, pigpio.OUTPUT)

        while True:
            log.info(f'starting trigger task')
            try:        
                await self.pi.wave_add_generic(trigger_100ms)
                self.trigger_wave = await self.pi.wave_create()
                await self.pi.wave_send_repeat(self.trigger_wave)

                while await self.pi.wave_tx_busy():
                    await asyncio.sleep(1)

            except Exception as e:
                log.error('issue in trigger task',exc_info=e)
            
            await asyncio.sleep(1)



    def _rise(self, gpio, level, tick):
        self.last[gpio]['rise'] = tick

    def _fall(self, gpio, level, tick):
        if self.last[gpio]['rise'] is not None:
            dt = tick -  self.last[gpio]['rise']
            if dt < 0:
                dt = 4294967295 + dt #wrap around
            self.last[gpio]['dt'] = dt
            self.last[gpio]['dt_tick'] = tick

    def read(self,gpio:int):
        """
        get the current reading
        round trip cms = round trip time / 1000000.0 * 34030
        """
        
        dobj = self.last.get(gpio,None)
        if dobj is not None:
            return dobj['dt'] * self.sound_conv
        return 0


    def set_parameters(self,**params):
        #labels holds all high level status
        kw = {k:v for k,v in params.items() if k in editable_parmaters}
        log.info(f"setting control info: {kw} from {params}")

        #longest to shortest first, ensure match on appropriate child first
        comps = {
        'control.wave' : self.control.wave,
        'control' : self.control,
        'hw' : self,
        }

        #create lambdas to set values at end, ensuring intermediate validation doesnt partial update
        set_procedures = {}

        def set_later(cmp,k,v):
            def cb(*a):
                setattr(cmp,k,v)
                return v
            return cb

        #TODO set parameters via editable dict
        for k,v in kw.items():
            #if isinstance(v,str):
            #    log.info(f'skippings str:{k}')
                #continue #bye, titles ect
            
            list_check = False
            str_check = False
            if isinstance(v,list):
                list_check = True
            elif isinstance(v,str):
                str_check = True
            elif not isinstance(v,(float,int,bool)):
                log.info(f'bad value for: {k}|{v}')
            
            ep = editable_parmaters[k]
            mn,mx = None,None
            if str_check and isinstance(ep,str):
                hwkey = ep
            elif len(ep) == 1:
                hwkey = ep
            elif len(ep) == 3:
                hwkey,mn,mx = ep #min and max, numeric
            else:
                return f'{k} parameter entry, wrong format, 1/3 items:  {ep}'
            
            cmp = None
            segs = hwkey.split('.')
            prm = segs[-1]
            pre = '.'.join(segs[:-1])
            if pre in comps:
                cmp = comps[pre]

            if cmp is None:
                raise ValueError(f'no component found! {k}| {hwkey} | ')

            #do validations
            if list_check:
                if mn is not None:
                    if mn > min(v):
                        return f'{k} value {v} is less than min: {mn}'
                if mx is not None:
                    if mx < max(v):
                        return f'{k} value {v} is greater than max: {mx}'
            else:
                if mn is not None:
                    if mn > v:
                        return f'{k} value {v} is less than min: {mn}'
                if mx is not None:
                    if mx < v:
                        return f'{k} value {v} is greater than max: {mx}'
            
            #finally determine which items to set
            log.info(f'setting cb later: {prm} = {v}')
            set_procedures[k] = set_later(cmp,prm,v)

        if not set_procedures and kw:
            raise ValueError(f'no procedures used for {kw}')

        log.info(f'setting {set_procedures}')
        for k,sp in set_procedures.items():
            v = sp()
            log.info(f'set {k}|{v}')
            

        #match raw update
        self.labels.update(kw)

        return True

    def parameters(self):
        out = {}
        
        #longest to shortest first, ensure match on appropriate child first
        comps = {
        'control.wave' : self.control.wave,
        'control' : self.control,
        'hw' : self,
        }

        for k,token in editable_parmaters.items():
            if len(token) == 1 or isinstance(token,str):
                hwkey = token
                mn,mx = None,None
            elif len(token) == 3:
                hwkey,mn,mx = token #min and max, numeric
            else:
                log.info(f'{k} parameter entry, wrong format, 1/3 items:  {token}')
                continue
            segs = hwkey.split('.')
            kv = segs[-1]
            pre = '.'.join(segs[:-1])
            if pre in comps:
                out[k] = getattr(comps[pre],kv)
            else:
                log.info(f'got bad pre: {pre} | {k} | {token}')

        return out

    def output_data(self,add_bias=True):
        out = {'timestamp':time.perf_counter()}
        if ON_RASPI:
            out.update(self.record) #these are latest from I2C

            #Add in GPIO Signals
            for i,echo_pin in enumerate(self.echo_pins):
                if echo_pin in self.last:
                    out[f'e{i+1}'] = self.read(echo_pin)
                    out[f'e{i+1}_ts'] = self.last[echo_pin].get('dt_tick',None)
                else:
                    out[f'e{i+1}'] = 0
                    out[f'e{i+1}_ts'] = 0

            for i,(enc_a,enc_b) in enumerate(self.encoder_pins):
                out[f'z{i+1}'] = self.last.get(f'pos_enc_{i}',0)

        else:
            #FAKENESS
            mock_sensors ={ 'e1':0.1*(0.5-random.random()),
                    'e2':0.1*(0.5-random.random()),
                    'e3':0.1*(0.5-random.random()),
                    'e4':0.1*(0.5-random.random()),
                    'z1':5*(0.5-random.random()),
                    'z2':5*(0.5-random.random()),
                    'z3':5*(0.5-random.random()),
                    'z4':5*(0.5-random.random()),
                    }
            out.update(mock_sensors)
            #echo ts
            now = time.perf_counter()
            for i,echo_pin in enumerate(self.echo_pins):
                out[f'e{i}_ts'] = now - 0.1*random.random()

            #they call it a bias for a reason :)
            for k,v in FAKE_BIAS.items():
                if k in out:
                    out[k] = out[k] + v

        #Add control info
        out['z_wave'] = self.control.v_wave
        out['z_cmd'] = self.control.z_cmd
        out['z_cur'] = self.control.z_cur
        out['v_cmd'] = self.control.v_command
        out['v_cur'] = self.control.v_cur
        out['v_wave'] = self.control.v_wave

        out['wave_fb_volt'] = self.control.feedback_volts
        out['coef_2'] = self.control.coef_2
        out['coef_10'] = self.control.coef_10
        out['coef_100'] = self.control.coef_100
        out['stuck'] = self.control.stuck

        out['maybe_stuck'] = self.control.maybe_stuck
        out['drive_mode'] = self.control.drive_mode
        out['speed_control_mode'] = self.control.speed_control_mode
        
        #mode check
        out['data_active'] = self.active
        out['ctrl_stopped'] = self.control.stopped
        out['ctrl_enabled'] = self.control.enabled


        #subtract the bias before it hits the system
        if add_bias and hasattr(self,'zero_biases'):
            for k,bs in self.zero_biases.items():
                if k in out:
                    out[k] = out[k] - bs                    

        #Add labels
        out.update(self.parameters())

        return out 

    async def print_data(self,intvl:int=1):
        while True:
            try:
                if not self.active:
                    await asyncio.sleep(intvl)
                    continue
                if PLOT_STREAM:
                    log.info(' '.join([f'{v:3.4f}' for k,v in self.output_data().items() if isinstance(v,(float,int))] )+'\r\n')
                else:
                    log.info({k:f'{v:3.3f}' for k,v in self.output_data().items() if isinstance(v,(float,int))})
                
                await asyncio.sleep(intvl)
            except Exception as e:
                log.info(e)

    async def process_data(self):
        """a simple function to provide efficient calculation of variables out of a queue before writing to S3"""
        while True:
            try:
                # #swap refs with namespace fancyness
                # last = locals().get('new',None)

                new = await self.buffer.get()
                ts = new["timestamp"]
                #no replace data
                good_lab ={k:v for k,v in self.labels.items() if k not in new}
                new.update(**good_lab)

                self.last_time = ts
                #This saves the data #TODO: sort out disk/exp memory data
                self.cache[ts] = new
                # if cache:
                #     cache[ts] = new
                self.unprocessed.append(ts) 

            except Exception as e:
                log.error(str(e), exc_info=1)

    async def poll_data(self):
        """polls the piplates for new data, and outputs the raw measured in real units"""
        alpha = 0.0
        inttime = 0
        while True:
            try:
                ts = time.perf_counter()
                if self.active:
                    #get the current record
                    data = self.output_data()
                    if data:
                        await self.buffer.put(data)

                    await asyncio.sleep(self.poll_rate)
                else:
                    await asyncio.sleep(1)

            except Exception as e:
                log.error(str(e), exc_info=1)

    async def mark_zero(self,cal_time=1,delay=1./1000.):
        """average zeros over a second"""
        lt = st = time.perf_counter()
        bs = {}
        while (ct:=time.perf_counter() - st) < cal_time:
            d = self.output_data(add_bias=False)
            tm = time.perf_counter()
            dt = tm-lt
            lt = tm
            #lowpass influence dt/(t-t_start)
            a = dt/ct
            b = 1-a 
            for k,rec in d.items():
                val = rec if rec is not None else 0
                if k not in FAKE_BIAS:
                    continue
                if k not in bs:
                    bs[k] = val
                else:
                    
                    bs[k] = bs[k]*b + val*a

            await asyncio.sleep(delay)
                
        self.zero_biases = bs

        return self.zero_biases

def main():
    from waveware.control import regular_wave
    import sys
    
    rw = regular_wave()
    hw = hardware_control(encoder_pins,echo_pins,cntl_conf=control_conf,**pins_kw)
    hw.setup()

    log.info(sys.argv)
    if '--do-mpu-cal' in sys.argv:
        hw.imu_calibrate()
    else:    
        hw.run()

    
if __name__ == '__main__':


        main()




    #cal = hw.run_calibration()
    #loop.run_until_complete(cal)
    
    #if hw.status_ok is not True:
    #    raise Exception(f'initial calibration didnt work!!!')

    # sensors = hw.start_data_acquisition()
    # controls = hw.start_controls()    
    






