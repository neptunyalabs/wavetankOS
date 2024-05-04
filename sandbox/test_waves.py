import asyncpio
import asyncio
import time


class test:
    _step_pin = 6
    _dir_pin = 4
    _last_dir = 1

    def __init__(self) -> None:
        self.pi = asyncpio.pi()

    async def _setup(self):
        await self.pi.connect()
        await self.pi.set_mode(self._step_pin,asyncpio.OUTPUT)
        await self.pi.set_mode(self._dir_pin,asyncpio.OUTPUT)
        await self.pi.wave_clear()        

        #await self.pi.wave_clear()

    def setup(self):
        self.start = time.perf_counter()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._setup())

    async def step_wave(self,wave,dir=None):
        """places waveform on pin with appropriate callbacks"""

        if dir is None:
            dir = self._last_dir
        elif self._last_dir != dir:
            dv = 1 if dir >= 0 else 0
            await self.pi.write(self._dir_pin,dv)
            self._last_dir = dir

        await self.pi.wave_add_generic(wave)

        self.wave_next = await self.pi.wave_create()
        await self.pi.wave_send_once( self.wave_next)
        while self.wave_next == await self.pi.wave_tx_at():
            print(f'waiting...')
            await asyncio.sleep(0)      



    async def loop(self):
        dir = 1
        await self.pi.write(self._step_pin,1)
        await self.sleep(1)
        await self.pi.write(self._step_pin,0)
        await self.sleep(1)        
        await self.pi.write(self._step_pin,1)
        await self.sleep(1)
        await self.pi.write(self._step_pin,0)

        while True:
            dir = -1 if dir == 1 else 1
            for i in range(10):
                for j in range(10):
                    t_on = 10+i*100
                    t_off= 10+j*100
                    wave = [asyncpio.pulse(1<<self._step_pin, 0, t_on)]
                    wave.append(asyncpio.pulse(0, 1<<self._step_pin, t_off))
                    wave = wave * 100
                    await self.step_wave(wave,dir=dir)

          

t = test()
t.setup()
loop = asyncio.get_event_loop()

async def main(t):
    await t.loop()

asyncio.run(main())




#     async def step_wave(self,wave,dir=None):
#         """places waveform on pin with appropriate callbacks"""
# 
#         if dir is None:
#             dir = self._last_dir
#         elif self._last_dir != dir:
#             dv = 1 if dir >= 0 else 0
#             await self.pi.write(self._dir_pin,dv)
#             self._last_dir = dir
# 
#         
#         self.wave_last = self.wave_next #push back
#         print(dir,len(wave))
#         if self.wave_last is not None:
#             ##create the new wave
#             pad_amount = await self.pi.wave_get_micros()
#             
#             #TODO: make sure this is a good idea
#             wave = [asyncpio.pulse(0, 0, pad_amount)] + wave
#             await self.pi.wave_add_generic(wave)
# 
#             self.wave_next = await self.pi.wave_create()
#             await self.pi.wave_send_once( self.wave_next)              
#             while self.wave_last == await self.pi.wave_tx_at():
#                 #print(f'waiting...')
#                 await asyncio.sleep(0)
# 
#             await self.pi.wave_delete(self.wave_last)
# 
#         else:
#             #do it raw
#             ##create the new wave
#             await self.pi.wave_add_generic(wave)
# 
#             self.wave_next = await self.pi.wave_create()
#             await self.pi.wave_send_once( self.wave_next)
#             while self.wave_next == await self.pi.wave_tx_at():
#                 #print(f'waiting...')
#                 await asyncio.sleep(0)      