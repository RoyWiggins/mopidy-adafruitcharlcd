import pykka

from mopidy import core
from mopidy.models import Track
import Adafruit_CharLCD as LCD
import Adafruit_GPIO.SPI as SPI
import Adafruit_MCP3008

from rotary_class import RotaryEncoder
import time,random, threading,os,subprocess
from mopidy_json_client import MopidyWSClient, MopidyWSListener
import signal,sys
from websocket import WebSocketConnectionClosedException
UP_SWITCH = 17
DOWN_SWITCH = 18


class ADC(pykka.ThreadingActor):
	use_daemon_thread = True
	def __init__(self,mopidy,lcd):
		super(ADC, self).__init__()
		SPI_PORT   = 0
		SPI_DEVICE = 0
		self.mopidy = mopidy
		self.mcp = Adafruit_MCP3008.MCP3008(spi=SPI.SpiDev(SPI_PORT, SPI_DEVICE))
		self.lcd = lcd
		# self.waiter = Waiter.start(self.actor_ref,0.1)
	def on_start(self):
		k = 0
		self.actor_ref.tell({})

	def on_receive(self,message):
		# if message.has_key("encode-changed"):
		# 	self.lcd.set_cursor(13,0)
		# 	self.lcd.message("   ",True)
		# 	return
		new_volume = (self.mcp.read_adc(0) * 100 / 1023 - 5) * 101/94
		if new_volume < 0: new_volume = 0
		if new_volume > 100: new_volume = 100
		if abs(new_volume - self.mopidy.playback.get_volume()) > 1:
			self.mopidy.playback.set_volume(new_volume)
			self.lcd.set_cursor(13,0)
			self.lcd.message("{:>3}".format(str(new_volume)),True)

			if new_volume == 0:
				self.mopidy.mixer.set_mute(True)
			elif self.mopidy.mixer.get_mute():
				self.mopidy.mixer.set_mute(False)
		time.sleep(0.1)
		self.actor_ref.tell({})

	def on_stop(self):
		self.waiter.stop()
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
			print "done"
			self.user_ref.ask({"encode-stopped":True})

class ThreadedLCD(LCD.Adafruit_CharLCDPlate):
	lock = threading.RLock() # This should probably be a pykka actor but I'm lazy

	def message(self,msg,fast=True):
		with ThreadedLCD.lock:
			message = super(LCD.Adafruit_CharLCDPlate, self).message
			if not fast:
				msg = "{:16}".format(msg)
			message(msg)

	def message_line(self,line,message,fast=False):
		if line not in [0,1]:
			raise Exception("oops")
		with ThreadedLCD.lock:
			self.set_cursor(0,line)
			self.message(message,fast)

	def set_cursor(self,a,b):
		with ThreadedLCD.lock:
			super(LCD.Adafruit_CharLCDPlate, self).set_cursor(a,b)

class RotaryActor(pykka.ThreadingActor):
	def __init__(self,mopidy,lcd):
		super(RotaryActor, self).__init__()
		self.mopidy = mopidy
		self.lcd = lcd
		self.current_track_i = 0
		self.in_future = self.actor_ref.proxy()

	def _display_track(self,track,fast=False):
		try:
			self.lcd.message_line(0,track['track']['artists'][0]['name'])
		except KeyError:
			self.lcd.message_line(0,"")
		try:
			self.lcd.message_line(1,track['track']['name'])
		except KeyError:
			self.lcd.message_line(1,"")

	def on_start(self):
		self.knob = RotaryEncoder(UP_SWITCH,DOWN_SWITCH,25,self.encode_event,2)
		self.waiter = Waiter.start(self.actor_ref)
		self.tracks = self.mopidy.tracklist.get_tl_tracks()
		first_track = self.mopidy.playback.get_current_tl_track()
		self._display_track(first_track)


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

			self.lcd.message_line(1,self.tracks[self.current_track_i]['track']['name']+" ",True)
			if event == RotaryEncoder.BUTTONDOWN:
				pass

		elif message.has_key("encode-stopped"):
			current_track = self.tracks[self.current_track_i]
			self.play(current_track)
			name = current_track['track']['name']
			self.lcd.set_cursor(len(name)+1,1)
			self.lcd.message(" "*(15-len(name)),True)

			try:
				artist = current_track['track']['artists'][0]['name'] 
			except KeyError:
				artist = ""
			self.lcd.message_line(0,artist)

		elif message.has_key("tracklist-changed"):
			self.tracks = self.mopidy.tracklist.get_tl_tracks()

	def play(self,track):
		print "%f playing %s" % (time.clock(), track['track']['name'])
		self.mopidy.playback.play(track)

	def message(self, msg):
		self.lcd.message(msg)

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
		self.lcd = ThreadedLCD()
		self.lcd.set_color(1.0, 1.0, 1.0)
		self.lcd.clear()
		self.lcd.message('Connecting...')
		self.mopidy = MopidyWSClient(ws_endpoint="ws://raspberrypi.local:6680/mopidy/ws",
										event_handler=self.on_event)
		try:
			self.mopidy.tracklist.set_repeat({"value":True})
		except WebSocketConnectionClosedException:
			self.lcd.message("Failed")
			self.stop()

		self.lcd.clear()
		self.lcd.message('Ready')
		self.track = None
		self.time = None
		self.adc = ADC.start(self.mopidy,self.lcd)
		self.encoder = RotaryActor.start(self.mopidy,self.lcd)

	def tracklist_changed(self):
		self.encoder.tell({"tracklist-changed":True})

	def on_stop(self):
		self.lcd.clear()
		self.lcd.set_backlight(False)
		self.adc.stop()
		self.encoder.stop()
		#self.lcd.enable_display(False)
	# Your frontend implementation

if __name__ == "__main__":
	def signal_handler(signal, frame):
		r.stop()
		sys.exit(0)
	signal.signal(signal.SIGINT, signal_handler)
	try:
		r = LCDFrontend().start()
	finally:
		signal.pause()
