import pykka

from mopidy import core
from mopidy.models import Track
import Adafruit_CharLCD as LCD
import Adafruit_GPIO.SPI as SPI
import Adafruit_MCP3008
print LCD.__file__
from rotary_class import RotaryEncoder
import time,random, threading,os,subprocess
from mopidy_json_client import MopidyWSClient, MopidyWSListener

UP_SWITCH = 17
DOWN_SWITCH = 18


class ADC(pykka.ThreadingActor):
	use_daemon_thread = True
	def __init__(self,mopidy):
		super(ADC, self).__init__()
		SPI_PORT   = 0
		SPI_DEVICE = 0
		self.mopidy = mopidy
		self.mcp = Adafruit_MCP3008.MCP3008(spi=SPI.SpiDev(SPI_PORT, SPI_DEVICE))

	def on_start(self):
		k = 0
		self.actor_ref.tell({})

	def on_receive(self,message):
		new_volume = (self.mcp.read_adc(0) * 100 / 1023 - 5) * 101/94
		if new_volume < 0: new_volume = 0
		if new_volume > 100: new_volume = 100
		if abs(new_volume - self.mopidy.playback.get_volume()) > 1:
			self.mopidy.playback.set_volume(new_volume)
			if new_volume == 0:
				self.mopidy.mixer.set_mute(True)
			elif self.mopidy.mixer.get_mute():
				self.mopidy.mixer.set_mute(False)
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
	def __init__(self,mopidy,lcd):
		super(RotaryActor, self).__init__()
		self.mopidy = mopidy
		self.lcd = lcd
		self.current_track_i = 0
		self.in_future = self.actor_ref.proxy()

	def on_start(self):
		self.knob = RotaryEncoder(UP_SWITCH,DOWN_SWITCH,25,self.encode_event,2)
		self.waiter = Waiter.start(self.actor_ref)
		self.tracks = self.mopidy.tracklist.get_tl_tracks()

	def encode_event(self, event):
		self.actor_ref.tell({"encode-changed":event})

	def on_receive(self,message):
		if message.has_key("encode-changed"):
			self.waiter.tell({"time":time.clock()})
			event = message["encode-changed"]
			if event == RotaryEncoder.CLOCKWISE:
				self.current_track_i = (self.current_track_i+1) % len(self.tracks)
			elif event == RotaryEncoder.ANTICLOCKWISE:
				self.current_track_i = (self.current_track_i-1) % len(self.tracks)
			current_track = self.tracks[self.current_track_i]
			self.lcd.set_cursor(0,1)
			self.message(current_track['track']['name']+" ")

			if event == RotaryEncoder.BUTTONDOWN:
				pass
		elif message.has_key("encode-stopped"):
			current_track = self.tracks[self.current_track_i]
			self.play(current_track)
			name = current_track['track']['name']
			self.lcd.set_cursor(len(name)+1,1)
			self.message(" "*(15-len(name)))
			self.lcd.set_cursor(0,0)
			self.message(current_track['track']['artists'][0]['name']+" ")
			
	def play(self,track):
		print "%f playing %s" % (time.clock(), track['track']['name'])
		self.mopidy.playback.play(track)
	def message(self, msg):
		self.lcd.message(msg)
		#self.in_future.play_track(self.current_track)
	def on_stop(self):
		self.waiter.stop()

class FoobarFrontend(pykka.ThreadingActor, core.CoreListener):
	def __init__(self, config, core):
		super(FoobarFrontend, self).__init__()
		os.chdir("/home/pi/dev/mopidy-adafruitcharlcd/mopidy_adafruitcharlcd/")
		subprocess.call(["python","frontend.py"])

class LCDFrontend(pykka.ThreadingActor, MopidyWSListener):
	def __init__(self):
		super(LCDFrontend, self).__init__()

	def on_start(self):
		self.lcd = LCD.Adafruit_CharLCDPlate()
		self.lcd.set_color(1.0, 1.0, 1.0)
		self.lcd.clear()
		self.mopidy = MopidyWSClient(ws_endpoint="ws://raspberrypi.local:6680/mopidy/ws")
		self.mopidy.tracklist.set_repeat({"value":True})
		self.lcd.message('Ready')
		self.track = None
		self.time = None

		# self.adc = ADC.start(self.mopidy)
		self.encoder = RotaryActor.start(self.mopidy,self.lcd)
		
	def on_stop(self):
		self.lcd.clear()
		self.lcd.set_backlight(False)
		#self.adc.stop(True)
		self.encoder.stop(True)
		#self.lcd.enable_display(False)
	# Your frontend implementation

if __name__ == "__main__":
	LCDFrontend().start()