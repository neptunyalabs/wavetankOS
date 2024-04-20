#!/usr/bin/env python

import time

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

   def __init__(self, trigger, echo):
      """
      The class is instantiated with the gpios connected to
      the trigger and echo pins.
      """
      self._trig = trigger
      self._echo = echo

      self._ping = False
      self._high = None
      self._time = None

      self._trig_mode = pigpio.get_mode(self._trig)
      self._echo_mode = pigpio.get_mode(self._echo)

      pigpio.set_mode(self._trig, pigpio.OUTPUT)
      pigpio.set_mode(self._echo, pigpio.INPUT)

      self._cb = pigpio.callback(self._echo, pigpio.EITHER_EDGE, self._cbf)

      self._inited = True

   def _cbf(self, gpio, level, tick):
      if level == 1:
         self._high = tick
      else:
         if self._high is not None:
            self._time = tick - self._high
            self._high = None
            self._ping = True

   def read(self):
      """
      Triggers a reading.  The returned reading is the number
      of microseconds for the sonar round-trip.

      round trip cms = round trip time / 1000000.0 * 34030
      """
      if self._inited:
         self._ping = False
         pigpio.gpio_trigger(self._trig)
         while not self._ping:
            time.sleep(0.001)
         return self._time
      else:
         return None

   def cancel(self):
      """
      Cancels the ranger and returns the gpios to their
      original mode.
      """
      if self._inited:
         self._inited = False
         self._cb.cancel()
         pigpio.set_mode(self._trig, self._trig_mode)
         pigpio.set_mode(self._echo, self._echo_mode)

if __name__ == "__main__":

   import time

   import pigpio

   import sonar_trigger_echo

   pigpio.start()

   sonar = sonar_trigger_echo.ranger(7, 8)

   end = time.time() + 60.0

   while time.time() < end:

      print(sonar.read())
      time.sleep(0.03)

   sonar.cancel()

   pigpio.stop()

