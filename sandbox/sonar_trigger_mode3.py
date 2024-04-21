#!/usr/bin/env python

import time
import sys
import pigpio

class ranger:
   """
   This class encapsulates a type of acoustic ranger.  In particular
   the type of ranger with separate trigger and echo pins.

   A pulse on the trigger initiates the sonar ping and shortly
   afterwards a sonar pulse is transmitted and the echo pin
   goes high.  The echo pins stays high until a sonar echo is
   received (or the response times-out).  The time between
   the high and low edges indicates the sonar round trip time.
   """

   def __init__(self, pi, trigger, echo):
      """
      The class is instantiated with the Pi to use and the
      gpios connected to the trigger and echo pins.
      """
      self.pi    = pi
      #self._trig = trigger
      self._echo = echo

      self._rising_time = None
      self._falling_time = None
      self._delta_tick = None


      #pi.set_mode(self._trig, pigpio.OUTPUT)
      pi.set_mode(self._echo, pigpio.INPUT)

      #self._cb = pi.callback(self._trig, pigpio.EITHER_EDGE, self._cbf)
      self._cb_rise = pi.callback(self._echo, pigpio.RISING_EDGE, self._rise)
      self._cb_fall = pi.callback(self._echo, pigpio.FALLING_EDGE, self._fall)


   def _rise(self, gpio, level, tick):
      self._rising_time = tick

   def _fall(self, gpio, level, tick):
      self._falling_time = tick    
      if self._rising_time is not None and self._rising_time < tick:
         self._delta_tick = self._falling_time - self._rising_time
      else:
         self._delta_tick = None

   def read(self):
      """
      Triggers a reading.  The returned reading is the number
      of microseconds for the sonar round-trip.

      round trip cms = round trip time / 1000000.0 * 34030
      """
      return self._delta_tick

   def cancel(self):
      """
      Cancels the ranger and returns the gpios to their
      original mode.
      """
      self._cb_rise.cancel()
      self._cb_fall.cancel()

if __name__ == "__main__":

   import time

   import pigpio

   pi = pigpio.pi()

   sonar = ranger(pi, 23, 18)

   end = time.time() + 600.0

   r = 1
   while time.time() < end:

      print("{} {} {}".format(r, sonar.read(),f'{sonar._falling_time}|{sonar._rising_time}'))
      r += 1
      time.sleep(0.03)

   sonar.cancel()

   pi.stop()

