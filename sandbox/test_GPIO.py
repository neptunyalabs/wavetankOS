#  Blink an LED with the LGPIO library
#  Uses lgpio library, compatible with kernel 5.11
#  Author: William Wilson & Rodrigo Griesi

import time
import lgpio

LED = int(input('GPIO to test:'))
WAIT = float(input('Wait time:'))

# open the gpio chip and set the LED pin as output
h = lgpio.gpiochip_open(0)
lgpio.gpio_claim_output(h, LED)

try:
    while True:
        # Turn the GPIO pin on
        lgpio.gpio_write(h, LED, 1)
        print('pin',LED,'ON')
        time.sleep(WAIT)

        # Turn the GPIO pin off
        lgpio.gpio_write(h, LED, 0)
        print('pin',LED,'OFF')
        time.sleep(WAIT)

except KeyboardInterrupt:
    lgpio.gpio_write(h, LED, 0)
    lgpio.gpiochip_close(h)
