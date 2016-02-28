import pykka

from mopidy import core
import Adafruit_CharLCD as LCD
import Adafruit_GPIO.SPI as SPI
import Adafruit_MCP3008
print LCD.__file__
from rotary_class import RotaryEncoder
import time,random, threading
UP_SWITCH = 17
DOWN_SWITCH = 18


class ADC(pykka.ThreadingActor):
	use_daemon_thread = True
	def __init__(self,core):
		super(ADC, self).__init__()
		SPI_PORT   = 0
		SPI_DEVICE = 0
		self.frontend = core
		self.mcp = Adafruit_MCP3008.MCP3008(spi=SPI.SpiDev(SPI_PORT, SPI_DEVICE))

	def on_start(self):
		k = 0
		self.actor_ref.tell({})
	def on_receive(self,message):
		new_volume = (self.mcp.read_adc(0) * 100 / 1023 - 5) * 101/94
		if new_volume < 0: new_volume = 0
		if new_volume > 100: new_volume = 100
		if abs(new_volume - self.frontend.core.playback.volume.get()) > 1:
			self.frontend.core.playback.volume = new_volume
			if new_volume == 0:
				self.frontend.core.mixer.set_mute(True)
			elif self.frontend.core.mixer.get_mute():
				self.frontend.core.mixer.set_mute(False)
		time.sleep(0.1)
		self.actor_ref.tell({})

	def on_stop(self):
		pass
class Waiter(pykka.ThreadingActor):
	"""
	Quick and dirty way to only change track after the rotary encoder has stopped for a bit
	"""
	def __init__(self,user_ref,seconds=0.5):
		super(Waiter, self).__init__()
		self.user_ref = user_ref
		self.seconds = seconds
		self.time = None
	def on_receive(self,message):
		time.sleep(self.seconds)
		if self.actor_inbox.empty():
			self.user_ref.ask({"encode-stopped":True})

class RotaryActor(pykka.ThreadingActor):
	def __init__(self,frontend):
		super(RotaryActor, self).__init__()
		self.frontend = frontend
		self.lcd = frontend.lcd
		self.current_track = None
		self.in_future = self.actor_ref.proxy()

	def on_start(self):
		self.knob = RotaryEncoder(UP_SWITCH,DOWN_SWITCH,25,self.encode_event,2)
		self.waiter = Waiter.start(self.actor_ref)

	def encode_event(self, event):
		self.actor_ref.tell({"encode-changed":event})

	def on_receive(self,message):
		if message.has_key("encode-changed"):
			self.waiter.tell({"time":time.clock()})
			event = message["encode-changed"]
			if event == RotaryEncoder.CLOCKWISE:
				self.current_track = self.frontend.core.tracklist.next_track(self.current_track).get()
			elif event == RotaryEncoder.ANTICLOCKWISE:
				self.current_track = self.frontend.core.tracklist.previous_track(self.current_track).get()			#self.core.playback.previous()
			self.lcd.set_cursor(0,1)
			print "%f coding %s" % (time.clock(), self.current_track.track.name)
			self.message(self.current_track.track.name.ljust(16))

			if event == RotaryEncoder.BUTTONDOWN:
				pass
		elif message.has_key("encode-stopped"):
			print "%f playing %s" % (time.clock(), self.current_track.track.name)
			self.frontend.core.playback.play(self.current_track)

	def message(self, msg):
		self.lcd.message(msg)
		#self.in_future.play_track(self.current_track)
	def on_stop(self):
		self.waiter.stop()

class FoobarFrontend(pykka.ThreadingActor, core.CoreListener):
	def __init__(self, config, core):
		super(FoobarFrontend, self).__init__()
		self.core = core
		self.n = 0
	def on_start(self):
		self.lcd = LCD.Adafruit_CharLCDPlate()
		self.lcd.set_color(1.0, 1.0, 1.0)
		self.lcd.clear()
		self.lcd.message('Mopidy started')
		self.core.tracklist.set_repeat(True)
		self.track = None
		self.time = None

		print "Frontend thread:",threading.current_thread()
		self.adc = ADC.start(self)
		self.encoder = RotaryActor.start(self)
			#self.n = 0
	def on_stop(self):
		self.lcd.clear()
		self.lcd.set_backlight(False)
		self.adc.stop(True)
		self.encoder.stop(True)
		#self.lcd.enable_display(False)
	# Your frontend implementation