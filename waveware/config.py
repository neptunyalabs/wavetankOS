import logging
import diskcache
import logging
import pathlib
import os

import pytz
import datetime
import pigpio
import sys

import traceback
from math import cos,sin
from decimal import Decimal

DEBUG = os.environ.get('WAVEWARE_DEBUG','false').lower().strip()=='true'
base_log = logging.INFO
if DEBUG:
    base_log = logging.DEBUG

BASIC_LOG_FMT = "%(asctime)s|%(message)s"
logging.basicConfig(level=base_log,format=BASIC_LOG_FMT)
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

#positive vdir indicates positive velocity increases z.
vdir_bias = -1 

#MOCK Specifications
mock_mass_act = 2.5
mock_act_fric = -0.005


mock_bouy_awl = 0.01 #10cm2
mock_bouy2_awl = 0.0001 #10cm2
mock_bouy_bwl = -0.001
mock_bouy2_bwl = -0.01
mock_bouy_mass = 0.1
mock_bouy2_mass = 0.5

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

#S3 Happens by deault ON_RASPI=true or if WAVEWARE_FLDR_NAME==test
LOG_TO_S3 = os.environ.get('WAVEWARE_LOG_S3','true').lower().strip()=='true'
bucket = os.environ.get('WAVEWARE_S3_BUCKET',"nept-wavetank-data")
folder = os.environ.get('WAVEWARE_FLDR_NAME',"V1")
PLOT_STREAM = (os.environ.get('PLOT_STREAM','false')=='true')

FW_HOST = os.environ.get('FW_HOST','0.0.0.0' if ON_RASPI else '127.0.0.1')
embedded_srv_port = int(os.environ.get('WAVEWARE_PORT',"8777"))
REMOTE_HOST = os.environ.get('WAVEWARE_HOST',f'http://{FW_HOST}:{embedded_srv_port}')

WAVE_VCMD_DIR = os.environ.get('WAVEWARE_VWAVE_DIRECT','true').lower().strip()=='true'

drive_modes = ['stop','wave','center']
default_mode = 'wave'

speed_modes = ['step','pwm','off','step-pwm']
default_speed_mode = os.environ.get('WAVE_SPEED_DRIVE_MODE','pwm' if ON_RASPI else 'off').strip().lower()
assert default_speed_mode in speed_modes, f'bad speed mode, check WAVE_SPEED_DRIVE_MODE!'

print_interavl = 0.5 if not DEBUG else 0.1
graph_update_interval = float(os.environ.get('WAVEWARE_DASH_GRAPH_UPT','3.3'))
num_update_interval = float(os.environ.get('WAVEWARE_DASH_READ_UPT','1.5'))
#polling & data range
poll_rate = float(os.environ.get('WAVEWARE_POLL_RATE',1.0 / 33))
poll_temp = float(os.environ.get('WAVEWARE_POLL_TEMP',60))
window = float(os.environ.get('WAVEWARE_WINDOW',6))


log.info(f'Running AWS User: {aws_profile}| {REMOTE_HOST} S3: {bucket} fld: {folder}| DEBUG: {DEBUG}| RASPI: {ON_RASPI}')

path = pathlib.Path(__file__)
fdir = path.parent
cache = diskcache.Cache(os.path.join(fdir,'data_cache'))

def check_failure(typ):
    def f(res):
        try:
            res.result()
        except Exception as e:
            log.info(f'{typ} failure: {e}')
            traceback.print_tb(e.__traceback__) 
    return f

#PINS
encoder_pins = [(17,18),(27,22),(23,24),(25,5)]
encoder_sens = [{'sens':0.005*4}]*4
echo_pins = [16,26,20,21]

pins_kw = dict(dir_pin=4,step_pin=6,speedpwm_pin=12,adc_alert_pin=7,hlfb_pin=13,motor_en_pin=19,torque_pwm_pin=10,echo_trig_pin=8)

log.info(f'PIN SETTINGS:')
for i,(a,b) in enumerate(encoder_pins):
    log.info(f'ENCDR CH: {i} A: {a} B:{b}')

for i,ep in enumerate(echo_pins):
    log.info(f'ECHO CH: {i} A: {ep} TRIG: {pins_kw["echo_trig_pin"]}')

for k,p in pins_kw.items():
    log.info(f'{k.upper()}: {p}')


#PINS
#parameter groupings
z_wave_parms = ['z_cur','z_err','z_wave','v_cur','v_cmd','v_wave','wave_fb_pct','wave_fb_volt']
z_sensors = [f'z{i+1}' for i in range(4)]
e_sensors = [f'e{i+1}' for i in range(4)]

zgraph = ['z_cur','z_err','z_wave']
vgraph = ['v_cur','v_cmd','v_wave']
acclgryo = ['az','ax','ay','gx','gy','gz','mz']

wave_drive_modes = ['stop','center','wave']
M = len(wave_drive_modes)
mode_dict = {i:v.upper() for i,v in enumerate(wave_drive_modes)}

wave_inputs = ['mode','wave-steep','wave-hs','z-ref','z-range','trq-lim']
Ninputs = len(wave_inputs)

all_sys_vars = z_wave_parms+z_sensors+e_sensors #output only
all_sys_parms = z_wave_parms+z_sensors+e_sensors+wave_inputs

LABEL_DEFAULT = {
    "title": "test",
    'mode':'stop',
    "wave-hs": 0/1000., #m
    "wave-steep": 80, #s
    "z-ref": 50,
    "z-range": [33,66],
    "trq-lim": 0,
    "kp-gain":0.1,
    "ki-gain":0,
    "kd-gain":0,
    "vz-max": 0.1,
    'dz-dvolt':0,
    "act-zrange":0.3,
    "dz-p-rot": 0.05,
    "step-p-rot": 360/1.8,
    "echo_x1":0,
    "echo_x2":0,
    "echo_x3":0,
    "echo_x4":0,
}

#editable inputs are the difference of wave_inputs and label_defaults
prevent_table = ['title'] #list to exclude from table edits
edit_inputs = {k:v for k,v in LABEL_DEFAULT.items() if k not in wave_inputs}

#list url/attr name lookups
#1 entry is basic lookup no lims
#3 entries is key,min,max
editable_parmaters = {
    'title': ('hw.title',),
    'mode': ('control.drive_mode',),
    'wave-hs': ('control.wave.hs',0,0.1),
    'wave-steep': ('control.wave.steepness',7,80), #wave period scales w/ sqrt
    'z-ref': ('control.vz0_ref',10,90),
    'z-range': ('control.safe_range',0,100),    
    'kp-gain': ('control.kp_zerr',-1000,1000),
    'ki-gain': ('control.ki_zerr',-1000,1000),
    'kd-gain': ('control.kd_zerr',-1000,1000),
    'trq-lim': ('control.t_command',0,100),
    "vz-max": ('control.act_max_speed',0.01,1),
    "dz-dvolt": ('control.dzdvref',-1,1),
    "act-zrange": ('control.dz_range',0.001,1),
    'dz-p-rot': ('control.dz_per_rot',1E-6,0.1),
    'step-p-rot': ('control.steps_per_rot',1,360),
    "echo_x1":('hw.echo_x1',0,2),
    "echo_x2":('hw.echo_x2',0,2),
    "echo_x3":('hw.echo_x3',0,2),
    "echo_x4":('hw.echo_x4',0,2),
}

_s_ep = set(editable_parmaters.keys())
_s_lp = set(LABEL_DEFAULT.keys())
su = set.union(_s_ep,_s_lp)
si = set.intersection(_s_ep,_s_lp)
assert _s_ep == _s_lp , f'Must Be Equal| Diff: {su.difference(si)}'

table_parms = {k:v for k,v in edit_inputs.items() if k not in prevent_table}

here = pathlib.Path(__file__).parent.parent
config_file = os.path.join(here,'saved_config.json')
print(f'looking for {config_file}')

#TODO: load parms from config

control_parms = ['wave-hs','wave-steep','z-ref','trq-lim']

mock_noise_fb = 0.033

#WAVE OBJ
center_time = 5
N_phases_in = 5

class regular_wave:

    full_wave_time: float
    ts: float = 2.5
    steepness: float = 50

    def __init__(self,Hs=editable_parmaters['wave-hs'][1],steepness=editable_parmaters['wave-steep'][-1]) -> None:
        self.hs = Hs
        self.steepness = steepness
        self.update()

    def update(self):
        self.ts = max((self.steepness*self.hs*3.14159/9.81)**0.5,0.025)
        self.omg = (2*3.14159)/self.ts
        self.a = self.hs/2

        self.full_wave_time = center_time + N_phases_in*self.ts

    #wave interface
    def z_pos(self,t):
        if t < center_time:
            return 0 #allow PID to work
        elif t< self.full_wave_time:
            return vdir_bias*self.a*((t-center_time)/self.full_wave_time)*sin(self.omg*t)
        return vdir_bias*self.a*sin(self.omg*t)

    def z_vel(self,t):
        if t < center_time:
            return 0 #allow PID error to work
        elif t< self.full_wave_time:
            Tfw =self.full_wave_time
            return self.a*((t-center_time)/Tfw)*self.omg*cos(self.omg*t) + self.a*sin(self.omg*t)/Tfw
        return self.a*self.omg*cos(self.omg*t)
    
rw = regular_wave()
control_conf = dict(wave=rw)