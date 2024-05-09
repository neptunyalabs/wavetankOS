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
from expiringdict import ExpiringDict

from imusensor.MPU9250 import MPU9250
import sys
import asyncpio
asyncpio.exceptions = True

import pigpio
import smbus

import datetime
import time
import logging
import json,os
import random

from waveware.control import wave_control
from waveware.config import *


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data")


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
                'e1':0.1*(0.5-random.random()) + 0.2,
                'e2':0.1*(0.5-random.random()) + 0.2,
                'e3':0.1*(0.5-random.random()) + 0.2,
                'e4':0.1*(0.5-random.random()) + 0.2,
                'z1':1*(0.5-random.random()),
                'z2':1*(0.5-random.random()),
                'z3':1*(0.5-random.random()),
                'z4':1*(0.5-random.random()),
                }


class hardware_control:
    
    #hw access
    pi = None

    #pinout / registers
    encoder_conf: list = None #[{sens:x,},...]
    encoder_pins: list = None  #[(A,B),(A2,B2)...]
    echo_pins: list = None #[1,2,3]
    #potentiometer_pin: int = None
    # #i2c addr
    mpu_addr: hex = 0x68#0x69 #3.3v
    si07_addr: hex = 0x40
    # #motor control
    control = None

    #config flags
    active = False
    poll_rate = 1.0 / 100
    poll_temp = 60
    window = 60.0
    
    #Data Storage
    buffer: asyncio.Queue
    unprocessed: deque
    cache: ExpiringDict
    active_mpu_cal = False

    #TODO: pins_def
    def  __init__(self,encoder_ch:list,echo_ch:list,dir_pin:int,step_pin:int,speedpwm_pin:int,adc_alert_pin:int,hlfb_pin:int,motor_en_pin:int,echo_trig_pin:int,torque_pwm_pin:int,winlen = 1000,enc_conf = None,cntl_conf=None):
        self.start_time = time.time()
        self.is_fake_init = lambda: True if (time.time() - self.start_time) <  FAKE_INIT_TIME else False

        self.default_labels = LABEL_DEFAULT
        self.labels = self.default_labels.copy()
        
        #data storage
        self.buffer = asyncio.Queue(winlen)
        self.unprocessed = deque([], maxlen=winlen)
        self.cache = ExpiringDict(max_len=self.window * 2 / self.poll_rate, max_age_seconds=self.window * 2)

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

        self.control = wave_control(self._dir_pin,self._step_pin,self._speedpwm_pin,self._adc_alert_pin,self._hlfb_pin,self._torque_pwm_pin,**cntl_conf)

    #Run / Setup
    #Setup & Shutdown
    def setup(self):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._setup_hardware())    

        if ON_RASPI:
            self.setup_i2c()
            self.control.setup_i2c(smbus=self.smbus,lock=self.i2c_lock)

        self.control.setup()


    async def _setup_hardware(self):
        self.pi = asyncpio.pi()
        con =  await self.pi.connect()

        await self.setup_encoder()
        await self.setup_echo_sensors()        
        
        #TODO: functionality
        #await self.setup_motor_control()
        #await self.setup_i2c_sensors()
        #await self.setup_gpio_sensors()
        #await self.setup_adc_sensors()        
    
    def setup_i2c(self):
        print(f'setup i2c')
        self.smbus = smbus.SMBus(1)

        #MPU
        print(f'setup mpu9250')
        self.imu = MPU9250.MPU9250(self.smbus, self.mpu_addr)
        print(f'mpu9250 begin')
        self.imu.begin()
        print(f'mpu9250 config')
        self.imu.setLowPassFilterFrequency("AccelLowPassFilter184")
        self.imu.setAccelRange("AccelRangeSelect2G")
        self.imu.setGyroRange("GyroRangeSelect250DPS")


        if os.path.exists(f"{fdir}/mpu_calib.json"):
            self.imu.loadCalibDataFromFile(f"{fdir}/mpu_calib.json")
        self.setup_adc()
        
    def _get_adc(self,ch:int)->float:
        data = self.smbus.read_i2c_block_data(0x48, 0x00, 2)
        # Convert the data
        raw_adc = data[0] * 256 + data[1]

        if raw_adc > 32767:
                raw_adc -= 65535
        return raw_adc / 32767.

    def run(self):
        loop = asyncio.get_event_loop()
        self.imu_read_task = loop.create_task(self.imu_task())
        self.temp_task = loop.create_task(self.temp_task())
        self.print_task = loop.create_task(self.print_data())
        
        time.sleep(0.1) 
        #TODO: check everything ok
        self.control.setup_control()
        self.control.run()

    def stop(self):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._stop())

    async def _stop(self):
        """
        Cancel the rotary encoder decoder.
        """
        for cba in self.cbA:
            await cba.cancel()
        for cbb in self.cbB:
            await cbb.cancel()

        for cbr in self._cb_rise:
            await cbr.cancel()
        for cbf in self._cb_fall:
            await cbf.cancel()

        self.imu_read_task.cancel()
        self.print_task.cancel()

    #MPU:
    #Interactive MPU Cal 
    def imu_calibrate(self):
        self.imu.caliberateAccelerometer()
        self.imu.caliberateGyro()
        self.imu.caliberateMagPrecise()
        self.imu.saveCalibDataToFile(f"{fdir}/mpu_calib.json")

    async def mpu_calibration_process(self):
        loop = asyncio.get_event_loop()
        self.active_mpu_cal = True

        try:
            self.setup_std_fake()
            task = asyncio.to_thread(self.imu_calibrate)
            task.add_done_callback(self.reset_std_in)
            for i in range(6):
                #TODO: add user control here vs 10second blocks
                w = 10*(i + 1)
                loop.call_later(w,self.reset_stdin)
            await task
        except Exception as e:
            print('issue with mpu cal: {e}')
        
        if hasattr(self,'_old_stdin'):
            self.reset_std_in()

        self.active_mpu_cal = False
        
        print(f'saving calibration file')
        self.imu.saveCalibDataToFile(f"{fdir}/mpu_calib.json")

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
        print('reset stdin')
        sys.stdin = self._old_stdin
        del self._old_stdin

    async def imu_task(self):
        print(f'starting imu task')
        while ON_RASPI:
            try:
                await asyncio.to_thread(self._read_imu)
                await asyncio.sleep(self.poll_rate)
            except Exception as e:
                print(f'imu error: {e}')

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
        print(f'starting temp task')
        while ON_RASPI:
            try:
                await asyncio.to_thread(self._read_temp)
                await asyncio.sleep(self.poll_temp)
            except Exception as e:
                print(f'temp error: {e}')

    def _read_temp(self) -> None:
        print(f'read temp')
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
            print(e)


    #Encoders
    async def setup_encoder(self):
        enccb = {}
        self.cbA = []
        self.cbB = []
        for i,(apin,bpin) in enumerate(self.encoder_pins):
            print(f'setting up encoder {i} on A:{apin} B:{bpin}')
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
        for echo_pin in self.echo_pins:
            print(f'starting ecno sensors on pin {echo_pin}')

            self.last[echo_pin] = {'dt':0,'rise':None}

            #TODO: loop over pins, put callbacks in dict
            await  self.pi.set_mode(echo_pin, asyncpio.INPUT)

            self._cb_rise.append(await self.pi.callback(echo_pin, asyncpio.RISING_EDGE, self._rise))
            self._cb_fall.append(await self.pi.callback(echo_pin, asyncpio.FALLING_EDGE, self._fall))

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

    def output_data(self,add_bias=True):
        out = {}
        if ON_RASPI:
            out.update(self.record) #these are latest from I2C

            #Add in GPIO Signals
            for i,echo_pin in enumerate(self.echo_pins):
                out[f'e{i}'] = self.read(echo_pin)
                out[f'e{i}_ts'] = self.last[gpio].get('dt_tick',None)

            for i,(enc_a,enc_b) in enumerate(self.encoder_pins):
                out[f'z{i}'] = self.last.get(f'pos_enc_{i}',None)

        else:
            #FAKENESS
            out = { 'e1':0.1*(0.5-random.random()) + 0.2,
                    'e2':0.1*(0.5-random.random()) + 0.2,
                    'e3':0.1*(0.5-random.random()) + 0.2,
                    'e4':0.1*(0.5-random.random()) + 0.2,
                    'z1':10*(0.5-random.random()),
                    'z2':10*(0.5-random.random()),
                    'z3':10*(0.5-random.random()),
                    'z4':10*(0.5-random.random()),
                    }
            #echo ts
            now = time.time()
            for i,echo_pin in enumerate(self.echo_pins):
                out[f'e{i}_ts'] = now - self.poll_rate*random.random()

            #they call it a bias for a reason :)
            for k,v in FAKE_BIAS.items():
                if k in out:
                    out[k] = out[k] + v

        #Add control info
        out['z_wave'] = self.control.z_cur
        out['wave_fb_volt'] = self.control.feedback_volts
        out['coef_2'] = self.control.coef_2
        out['coef_10'] = self.control.coef_10
        out['coef_100'] = self.control.coef_100
        out['stuck'] = self.control.stuck
        out['maybe_stuck'] = self.control.maybe_stuck
        out['drive_mode'] = self.control.drive_mode
        out['speed_control_mode'] = self.control.speed_control_mode


        #subtract the bias before it hits the system
        if add_bias and hasattr(self,'zero_biases'):
            for k,bs in self.zero_biases.items():
                if k in out:
                    out[k] = out[k] - bs                    

        return out 

    async def print_data(self,intvl:int=1):
        while True:
            try:
                if PLOT_STREAM:
                    print(' '.join([f'{v:3.4f}' for k,v in self.output_data().items() if isinstance(v,(float,int))] )+'\r\n')
                else:
                    print({k:f'{v:3.3f}' for k,v in self.output_data().items() if isinstance(v,(float,int))})
                
                await asyncio.sleep(intvl)
            except Exception as e:
                print(e)

    async def process_data(self):
        """a simple function to provide efficient calculation of variables out of a queue before writing to S3"""
        while True:
            try:
                #swap refs with namespace fancyness
                last = locals().get('new',None)

                new = await self.buffer.get()

                ts = new["timestamp"]
                #no replace data
                good_lab ={k:v for k,v in self.labels.items() if k not in new}
                new.update(**good_lab)

                self.last_time = ts
                #This saves the data
                self.cache[ts] = new
                self.unprocessed.append(ts) 

            except Exception as e:
                log.error(str(e), exc_info=1)

    async def poll_data(self):
        """polls the piplates for new data, and outputs the raw measured in real units"""
        alpha = 0.0
        inttime = 0
        while True:
            try:
                ts = time.time()
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

    async def mark_zero(self):
        """average zeros over a second"""
        mark_zero = {}
        lt = st = time.time()
        bs = {}
        while (ct:=time.time() - st) < 1:
            d = self.output_data(add_bias=False)
            tm = time.time()
            dt = tm-lt
            lt = tm
            a = dt/ct
            b = 1-a
            for k,rec in d.items():
                if k in FAKE_BIAS:
                    bs[k] = bs[k]*b + rec*a
        self.zero_biases = bs

def main():
    from waveware.control import regular_wave
    import sys
    

    rw = regular_wave()
    hw = hardware_control(encoder_pins,echo_pins,cntl_conf=control_conf,**pins_kw)
    hw.setup()
    hw.run()

    
if __name__ == '__main__':
    main()




    #cal = hw.run_calibration()
    #loop.run_until_complete(cal)
    
    #if hw.status_ok is not True:
    #    raise Exception(f'initial calibration didnt work!!!')

    # sensors = hw.start_data_acquisition()
    # controls = hw.start_controls()    
    






