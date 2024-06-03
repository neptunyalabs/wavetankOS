
import smbus
import time
import sys
# Get I2C bus
bus = smbus.SMBus(1)


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

res = []
start = time.perf_counter()

pin = 0
cb = config_bit(pin,fvinx = fv_inx)
db = int(f'{dr}00011',2)
data = [cb,db]
bus.write_i2c_block_data(0x48, 0x01, data)

last_print = None

while True:
    dt = time.perf_counter() - start    
    time.sleep(wait_factor/dr_inx)

    data = bus.read_i2c_block_data(0x48, 0x00, 2)

    # Convert the data
    raw_adc = data[0] * 256 + data[1]

    if raw_adc > 32767:
        raw_adc -= 65535

    v = (raw_adc/32767)*volt_ref[fv_inx]

    if last_print is None or (dt - last_print) > 0.025:
        sys.stdout.write(f'{v:3.4f} \n')
        last_print = dt















        # Output data to screen
        #print( f"Digital Value: AN{i} of Analog Input : {raw_adc} >> {v:3.2f}v" )
    #print(d)
# 
# pandas.options.plotting.backend = 'plotly'
# df = pandas.DataFrame(res)
# #df.plot()
# print(df.describe())

# #PLOT ALL 4 items
# # Distributed with a free-will license.
# # Use it any way you want, profit or free, provided it fits in the licenses of its associated works.
# # ADS1115
# # This code is designed to work with the ADS1115_I2CADC I2C Mini Module available from ControlEverything.com.
# # https://www.controleverything.com/content/Analog-Digital-Converters?sku=ADS1115_I2CADC#tabs-0-product_tabset-2
# #from matplotlib.pylab import *
# import pandas
# import smbus
# import time
# 
# # Get I2C bus
# bus = smbus.SMBus(1)
# 
# # ADS1115 address, 0x48(72)
# # Select configuration register, 0x01(01)
# #               0x8483(33923)   AINP = AIN0 and AINN = AIN1, +/- 2.048V
# #                               Continuous conversion mode, 128SPS
# 
# p_adc = {0:'100',1:'101',2:'110',3:'111'}
# 
# fv_ref = {6:'000',4:'001',2:'010',1:'011'}
# volt_ref = {6:6.144,4:4.096,2:2.048,1:1.024}
# 
# 
# dr_ref = {8:'000',16:'001',32:'010',64:'011',128:'100',250:'101',475:'110',860:'111'}
# 
# 
# def config_bit(pinx,fvinx=4):
#     dv = p_adc[pinx]
#     vr = fv_ref[fvinx]
#     return int(f'1{dv}{vr}0',2)
# 
# wait_factor = 2
# fv_inx = 4
# dr_inx = 860
# dr = dr_ref[dr_inx]
# 
# res = []
# start = time.perf_counter()
# for t in range(100):
#     dt = time.perf_counter() - start
#     d = {'time':dt}
#     res.append(d)
#     for i in range(4):
#         
#         cb = config_bit(i,fvinx = fv_inx)
#         db = int(f'{dr}00011',2)
#         data = [cb,db]
#         bus.write_i2c_block_data(0x48, 0x01, data)
#         time.sleep(wait_factor/dr_inx)
# 
#         # ADS1115 address, 0x48(72)
#         # Read data back from 0x00(00), 2 bytes
#         # raw_adc MSB, raw_adc LSB
#         data = bus.read_i2c_block_data(0x48, 0x00, 2)
# 
#         # Convert the data
#         raw_adc = data[0] * 256 + data[1]
# 
#         if raw_adc > 32767:
#             raw_adc -= 65535
# 
#         v = (raw_adc/32767)*volt_ref[fv_inx]
# 
#         d[i] = v
# 
#         # Output data to screen
#         #print( f"Digital Value: AN{i} of Analog Input : {raw_adc} >> {v:3.2f}v" )
#     print(d)
# 
# pandas.options.plotting.backend = 'plotly'
# df = pandas.DataFrame(res)
# #df.plot()
# print(df.describe())
