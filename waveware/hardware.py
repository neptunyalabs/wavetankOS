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
import aiobotocore
from aiobotocore.session import get_session

from collections import deque
from expiringdict import ExpiringDict

import asyncpio

try:
    import pigpio
    ON_RASPI = True
except:
    ON_RASPI = False

import datetime
import time
import logging
import json


# BUCKET CONFIG
# Permissons only for this bucket so not super dangerous
bucket = "nept-wavetank-data"
folder = "TEST"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("data")

#TODO: default values to run system
LABEL_DEFAULT = {
    "title": "test"
    "hs_in": 1/1000., #m
    "ts-in": 1.0, #s
    "max-torque": None,
    "kp-gain":0,
    "ki-gain":0,
    "kd-gain":0,
}

FAKE_INIT_TIME = 60.

class hardware_control:
    
    #hw access
    pi = None

    #encoder output
    a_ch_z:int = None
    b_ch_z:int = None
    hz_1:int = None
    hz_2:int = None
    hz_3:int = None
    hz_4:int = None

    mpu_addr: hex = 0x68#0x69 #3.3v
    bmp_280: hex = 0x40

    #motor control
    en_pin: int = None
    a_ch: int = None
    b_ch: int = None
    hlfb_pin: int = None
    hlfb_mode: int = 'ppr'
    drive_mode: int = 'pos_input'
    drive_modes: int = ['pos_input','2pos']

    #config flags
    active = False
    poll_rate = 1.0 / 20.
    window = 60.0
    
    #Data Storage
    buffer: asyncio.Queue
    unprocessed: deque
    cache: ExpiringDict

    #TODO: pins_def
    def  __init__(self,a_ch_z:int,b_ch_z:int,hz_1:int,hz_2:int,hz_3:int,,hz_4:int,winlen = 1000,*args,**kwargs):
        self.start_time = time.time()
        self.is_fake_init = lambda: True if (time.time() - self.start_time) <  FAKE_INIT_TIME else False

        self.default_labels = LABEL_DEFAULT
        self.labels = self.default_labels.copy()
        
        #data storage
        self.buffer = asyncio.Queue(winlen)
        self.unprocessed = deque([], maxlen=winlen)
        self.cache = ExpiringDict(max_len=self.window * 2 / self.poll_rate, max_age_seconds=self.window * 2)

        self.last = {} #TODO: init pins as 0
        #pin_enc_A
        #pin_enc_B


    async def setup_hardware(self):
        self.pi = asyncpio.pi()
        await self.pi.connect()

        await self.setup_encoder()
        await self.setup_echo_sensors()
        await self.setup_motor_control()
        #await self.setup_i2c_sensors()
        #await self.setup_gpio_sensors()
        #await self.setup_adc_sensors()

    async def stop(self):
        """
        Cancel the rotary encoder decoder.
        """
        await self.cbA.cancel()
        await self.cbB.cancel()
        await self._cb_rise.cancel()
        await self._cb_fall.cancel()


    async def push_data(self):
        """Periodically looks for new data to upload 1/3 of window time"""
        while True:

            try:

                if self.active and self.unprocessed:

                    data_rows = {}
                    data_set = {
                        "data": data_rows,
                        "num": len(self.unprocessed),
                        "test": self.labels['title'],
                    }
                    #add items from deque
                    while self.unprocessed:
                        row_ts = self.unprocessed.pop()
                        if row_ts in self.cache:
                            row = self.cache[row_ts]
                            if row:
                                data_rows[row_ts] = row

                    # Finally try writing the data
                    if data_rows:
                        log.info(f"writing to S3")
                        await self.write_s3(data_set)
                    else:
                        log.info(f"no data, skpping s3 write")
                    # Finally Wait Some Time
                    await asyncio.sleep(self.window / 3.0)

                elif self.active:
                    log.info(f"no data")
                    await asyncio.sleep(self.window / 3.0)
                else:
                    log.info(f"not active")
                    await asyncio.sleep(self.window / 3.0)

            except Exception as e:
                log.error(str(e), exc_info=1)


    async def write_s3(self,data: dict,title=None):
        """writes the dictionary to the bucket
        :param data: a dictionary to write as json
        :param : default='data', use to log actions ect
        """
        if ON_RASPI:
            up_time = datetime.datetime.now(tz=datetime.timezone.utc)
            data["upload_time"] = str(up_time)
            date = up_time.date()
            time = f"{up_time.hour}-{up_time.minute}-{up_time.second}"
            if title is not None and title:
                key = f"{folder}/{self.labels['title']}/{date}/{title}_{time}.json"
            else:
                #data
                key = f"{folder}/{self.labels['title']}/{date}/data_{time}.json"

            session = get_session()
            async with session.create_client('s3',region_name='us-east-1',config='wavetank') as client:

                resp = await client.put_object(
                    Bucket=bucket, Key=key, Body=json.dumps(data)
                )
                log.info(f"success writing {key}")
                log.debug(f"got s3 resp: {resp}")
        else:
            log.info("mock writing s3...")


    async def setup_encoder(self):
        await self.pi.set_mode(self.pin_enc_A, asyncpio.INPUT)
        await self.pi.set_mode(self.pin_enc_B, asyncpio.INPUT)

        await self.pi.set_pull_up_down(self.pin_enc_A, asyncpio.PUD_UP)
        await self.pi.set_pull_up_down(self.pin_enc_B, asyncpio.PUD_UP)

        ee = asyncpio.EITHER_EDGE
        self.cbA = await self.pi.callback(self.pin_enc_A,ee , self._pulse)
        self.cbB = await self.pi.callback(self.pin_enc_B,ee , self._pulse)

    def _pulse(self, gpio, level, tick):

        self.last[gpio] = level

        if gpio != self.last[gpio]: # debounce
            self.last['enc_last_pin'] = gpio
            if gpio == self.pin_enc_A and level == 1:
                if self.last[self.pin_enc_B] == 1:
                    self.callback(1) #forward step
            elif gpio == self.pin_enc_B and level == 1:
                if self.last[self.pin_enc_A] == 1:
                    self.callback(-1) #reverse step



    #SONAR:
    async def setup_echo_sensors(self)
        #self.pi    = pi
        #self._trig = trigger
#         self._echo = echo
# 
#         #TODO: structure for these items. put in last dict per gpio
#         self._rising_time = None
#         self._falling_time = None
#         self._delta_tick = None

        self.speed_of_sound = 343.0 #TODO: add temperature correction
        self.sound_conv = self.speed_of_sound / 2000000 #2x

        #TODO: loop over pins, put callbacks in dict
        await  self.pi.set_mode(self._echo, pigpio.INPUT)

        #self._cb = await pi.callback(self._trig, pigpio.EITHER_EDGE, self._cbf)
        self._cb_rise = self.pi.callback(self._echo, pigpio.RISING_EDGE, self._rise)
        self._cb_fall = self.pi.callback(self._echo, pigpio.FALLING_EDGE, self._fall)

    def _rise(self, gpio, level, tick):
        self._rising_time = tick 

    def _fall(self, gpio, level, tick):
        if self._rising_time is not None:
            self._falling_time = tick
            dt = self._falling_time - self._rising_time
            if dt < 0:
            dt = 4294967295 + dt #wrap around
            self.last[gpio] = dt

    def read(self,gpio:int):
        """
        Triggers a reading.  The returned reading is the number
        of microseconds for the sonar round-trip.

        round trip cms = round trip time / 1000000.0 * 34030
        """
        return self.last[gpio] * self.sound_conv
# 
# def cancel(self):
#     """
#     Cancels the ranger and returns the gpios to their
#     original mode.
#     """

#IMU MPU9250
# from imusensor.MPU9250 import MPU9250
# 
# address = 0x68
# bus = smbus.SMBus(1)
# imu = MPU9250.MPU9250(bus, address)
# imu.begin()
# # imu.caliberateGyro()
# # imu.caliberateAccelerometer()
# # or load your own caliberation file
# #imu.loadCalibDataFromFile("/home/pi/calib_real_bolder.json")
# 
# while True:
# 	imu.readSensor()
# 	imu.computeOrientation()
# 
# 	#print ("Accel x: {0} ; Accel y : {1} ; Accel z : {2}".format(imu.AccelVals[0], imu.AccelVals[1], imu.AccelVals[2]))
# 	#print ("Gyro x: {0} ; Gyro y : {1} ; Gyro z : {2}".format(imu.GyroVals[0], imu.GyroVals[1], imu.GyroVals[2]))
# 	#print ("Mag x: {0} ; Mag y : {1} ; Mag z : {2}".format(imu.MagVals[0], imu.MagVals[1], imu.MagVals[2]))
# 	print ("roll: {0} ; pitch : {1} ; yaw : {2}".format(imu.roll, imu.pitch, imu.yaw))
# 	time.sleep(0.1)

#TEMP SENSOR
# import board
# import adafruit_si7021
# sensor = adafruit_si7021.SI7021(board.I2C())


#TODO: dont poll data with software, use async pigpio
#Poll Data:
# if data:
#     await buffer.put(data)    
#Process Data:
# ts = new["timestamp"]
# new.update(**LABEL_SET)
# LAST = ts
# cache[LAST] = new
# self.unprocessed.append(ts)


#test

if __name__ == '__main__':

    loop = asyncio.get_event_loop()

    hw = hardware_control()#TODO: pins =)
    cal = hw.run_calibration()
    loop.run_until_complete(cal)
    
    if hw.status_ok is not True:
        raise Exception(f'initial calibration didnt work!!!')

    sensors = hw.start_data_acquisition()
    controls = hw.start_controls()

