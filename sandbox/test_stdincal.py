import time
import asyncio
import os,sys
class obj:
    def test(self):
        attempts = 0
        strt = time.time()
        while attempts < 5:
            sys.stdin.flush()
            got = input('need input pls')
            attempts += 1
            print(f'\nthanks got: {got} @ {time.time() - strt} | {attempts}')
            time.sleep(1)
            
        
    async def testcoro(self):
        loop = asyncio.get_event_loop()
        self.setup_std_fake()
        tsk = asyncio.to_thread(self.test)
        for i in range(10):
            wt = 2*(1+i)
            loop.call_later(wt,self.reset_stdin)
        return await tsk
        
    def reset_stdin(self):
        self.wt.write('gogogogogo\r\n'.encode())
        self.wt.flush() #make read happy
        sys.stdin.flush()
        time.sleep(0.5) #cal accel takes 3second wait so allow margin before destroying pipe
        #self.setup_std_fake()

    def setup_std_fake(self):
        r, w = os.pipe()
        self.rd = os.fdopen(r, 'rb')
        self.wt = os.fdopen(w, 'wb')
        self._old_stdin = sys.stdin
        sys.stdin = self.rd #this is what calibrateAccelerometer for input!

    def reset_std_in(self,*args):
        print('reset stdin')
        sys.stdin = self._old_stdin
        del self._old_stdin

o = obj()    
loop = asyncio.get_event_loop()
tsk = loop.create_task(o.testcoro())
tsk.add_done_callback(o.reset_std_in)

loop.run_until_complete(tsk)
