import logging
import diskcache
import logging
import pathlib
import os

import pytz
import datetime
import pigpio
import sys

from math import cos,sin
from decimal import Decimal
from waveware.data import *

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("conf")

mm_accuracy_enc = Decimal('1e-3')
mm_accuracy_ech = Decimal('1e-4')

pst = pytz.timezone('US/Pacific')
utc = pytz.utc

def to_test_time(timestamp):
    dt = datetime.datetime.fromtimestamp(timestamp,tz=pytz.UTC)
    return dt.astimezone(pst)

def to_date(timestamp):
    return to_test_time(timestamp).date()

if 'AWS_PROFILE' not in os.environ:
    os.environ['AWS_PROFILE'] = aws_profile = 'wavetank'
else:
    aws_profile = os.environ.get('AWS_PROFILE','wavetank')

LOG_TO_S3 = os.environ.get('WAVEWARE_LOG_S3','true').lower().strip()=='true'
bucket = os.environ.get('WAVEWARE_S3_BUCKET',"nept-wavetank-data")
folder = os.environ.get('WAVEWARE_FLDR_NAME',"V1")
PLOT_STREAM = (os.environ.get('PLOT_STREAM','false')=='true')

embedded_srv_port = int(os.environ.get('WAVEWARE_PORT',"8777"))
REMOTE_HOST = os.environ.get('WAVEWARE_HOST',f'http://localhost:{embedded_srv_port}')


DEBUG = os.environ.get('WAVEWARE_DEBUG','false').lower().strip()=='true'

log.info(f'Running AWS User: {aws_profile} S3: {bucket} fld: {folder}| DEBUG: {DEBUG}')

path = pathlib.Path(__file__)
fdir = path.parent
cache = diskcache.Cache(os.path.join(fdir,'data_cache'))

#IMPORT GPIO / CONFIGURE RASPI
try:
    import RPi.GPIO as gpio
    ON_RASPI = True
    pigpio.exceptions = DEBUG #TODO: make false
    from imusensor.MPU9250 import MPU9250
    import smbus
except:
    ON_RASPI = False
    pigpio.exceptions = DEBUG
    smbus = None
    MPU9250 = None

#PINS
encoder_pins = [(17,18),(27,22),(23,24),(25,5)]
encoder_sens = [{'sens':0.005*4}]*4
echo_pins = [16,26,20,21]

pins_kw = dict(dir_pin=4,step_pin=6,speedpwm_pin=12,adc_alert_pin=7,hlfb_pin=13,motor_en_pin=19,torque_pwm_pin=10,echo_trig_pin=11)

log.info(f'PIN SETTINGS:')
for i,(a,b) in enumerate(encoder_pins):
    log.info(f'ENCDR CH: {i} A: {a} B:{b}')

for i,ep in enumerate(echo_pins):
    log.info(f'ECHO CH: {i} A: {ep} TRIG: {pins_kw["echo_trig_pin"]}')

for k,p in pins_kw.items():
    log.info(f'{k.upper()}: {p}')

#WAVE OBJ
class regular_wave:

    def __init__(self,Hs=0.01,Ts=5) -> None:
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
    
rw = regular_wave()
control_conf = dict(wave=rw,force_cal='-fc' in sys.argv)

#PINS
#parameter groupings
z_wave_parms = ['z_cur','z_cmd','z_wave','v_cur','v_cmd','v_wave']
z_sensors = [f'z{i+1}' for i in range(4)]
e_sensors = [f'e{i+1}' for i in range(4)]

wave_drive_modes = ['stop','center','wave']
M = len(wave_drive_modes)
mode_dict = {i:v.upper() for i,v in enumerate(wave_drive_modes)}

wave_inputs = ['mode','wave-ts','wave-hs','z-ref','z-range','trq-lim']
Ninputs = len(wave_inputs)

all_sys_vars = z_wave_parms+z_sensors+e_sensors #output only
all_sys_parms = z_wave_parms+z_sensors+e_sensors+wave_inputs

LABEL_DEFAULT = {
    "title": "test",
    "wave-hs": 0/1000., #m
    "wave-ts": 10.0, #s
    "z-ref": 50,
    "z-range": [33,66],
    "trq-lim": 0,
    "kp-gain":0,
    "ki-gain":0,
    "kd-gain":0,
}

#editable inputs are the difference of wave_inputs and label_defaults
prevent_edit = ['title'] #list to exclude from table edits
edit_inputs = {k:v for k,v in LABEL_DEFAULT.items() if k not in wave_inputs}

#list url/attr name lookups
#1 entry is basic lookup no lims
#3 entries is key,min,max
editable_parmaters = {
    'title': 'hw.title',
    'wave-hs': ('control.wave.hs',0,0.3),
    'wave-ts': ('control.wave.ts',1,10),
    'z-ref': ('control.vz0_ref',10,90),
    'z-range': ('control.safe_range',0,100),    
    'kp-gain': ('control.kp_zerr',-1000,1000),
    'ki-gain': ('control.ki_zerr',-1000,1000),
    'kd-gain': ('control.kd_zerr',-1000,1000),
    'trq-lim': ('control.t_command',0,100),

    #'cntl-dt': ('control.control_interval',1/1000.,1/100.),    
    #'poll-rate': ('hw.poll_rate',1/1000.,1/10.),
    #'temp-rate': ('hw.temp_rate',1,600),    
    #'dz-p-rot': 'control.dz_per_rot',
    #'step-p-rot': 'control.dz_per_rot',
    #dzdvref
}
_s_ep = set(editable_parmaters.keys())
_s_lp = set(LABEL_DEFAULT.keys())
su = set.union(_s_ep,_s_lp)
si = set.intersection(_s_ep,_s_lp)
assert _s_ep == _s_lp , f'Must Be Equal| Diff: {su.difference(si)}'