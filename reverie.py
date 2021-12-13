#!/usr/bin/python3

from flask import Flask, render_template
from bluepy import btle
from bluepy.btle import Scanner, DefaultDelegate
import sys
import time
import math
import os
import signal

###############################################################################
#
# Reverie Powerbase Control API - Scott Garrett
# 
# Version 20211211-001
#
# This is a fork based on the Flask Purple Powerbase project by Jacob Byerline
# https://github.com/jbyerline/flask-purple-powerbase
#
# I used Jacob's project as a skeleton, and expanded it to handle positioning
# more cleanly, and handle some exceptions more gracefully.  I also renamed
# the variables and functions, so it will not drop in to the homebridge
# plugin he also wrote without modification.
#
# I have the Reverie R650 bed frame.  That is what I am testing against.
# The original project is tested against the "Purple Powerbase".  It seems
# to be the same controller, so should work with most Reverie bases.
#
# One major caveat, and a TODO is to handle lumbar controls as well as tilt.
# With tilt, the flat position is in the middle (36%), whereas with lumbar,
# it is zero.  Anyone who has a 650 and has tried to use the official App
# will know what I am talking about, as it does not properly recognize or
# handle tilt.
# 
# It's still not perfect.  When homekit spams it with requests, it usually
# works, but sometimes will miss a setting, or misfire one (for example,
# sometimes when I adjust the foot massage, the head massage will randomly
# start).  Using light dimmers is not the best way.  If I can find a better
# integration method on the homebridge side, I will update accordingly.
#
# This is also my very first python program.  Much thanks to Michael Zappe
# for his assistance in helping me understand the "python way" and for some
# of the math magic.
# 
###############################################################################

###############################################################################
#
# #     #                          #####
# #     #  ####  ###### #####     #     #  ####  #    # ###### #  ####
# #     # #      #      #    #    #       #    # ##   # #      # #    #
# #     #  ####  #####  #    #    #       #    # # #  # #####  # #
# #     #      # #      #####     #       #    # #  # # #      # #  ###
# #     # #    # #      #   #     #     # #    # #   ## #      # #    #
#  #####   ####  ###### #    #     #####   ####  #    # #      #  ####
#
###############################################################################

###############################################################################
# These values should be defined in /etc/default/reverie-powerbase.  Systemd
# will make them available to the script.  I have included some reasonable
# defaults in case the script is run manually, or nor defined externally.
###############################################################################

# The script will attempt to locate and connect to a Reverie Powerbase
# automatically. If you have more than one, you will need to find the MAC
# address of the bed you want to use and set DEVICE_MAC to the correct bed.  If
# you are not sure which is which, pick one and test it.  Repeat until you find
# the right one.
#
# To find your bed, you can use hcitool from the bluez package:
#
# hcitool lescan | grep RevCB_A1
#
# If you don't find anything, adjust your grep to maybe "Rev" instead (and, of
# course, make sure the bed has power).

DEVICE_MAC = os.environ.get("DEVICE_MAC", "Auto")
print("Using device MAC address " + DEVICE_MAC)

# If you are going to run this on the same device as homebridge, use 127.0.0.1
# If you running this on its own device, uncomment 0.0.0.0 to have it listen
# on the public interfaces

RPI_LOCAL_IP = os.environ.get("RPI_LOCAL_IP", "127.0.0.1")
if RPI_LOCAL_IP == "0.0.0.0":
	print("Listening interface set to all interfaces.")
else:
	print("Listening interface set to " + RPI_LOCAL_IP)

# This is the TCP port that the service will listen on.  You can use any
# unused port; it just needs to be set to the same one here and in the homebridge
# plugin.
RPI_LISTEN_PORT = os.environ.get("RPI_LISTEN_PORT", "8001")
print("Listening on port " + RPI_LISTEN_PORT)

# The factory set the fastest massage speed to 40% of what the motor
# will actually do.  I am using that limit because I don't know if it's
# an issue that can damage the bed, or just a comfort issue.
# In fact, the bed doesn't use percentages; it has 10 discrete settings, but
# it seems you can set it to the full range.  For reference, here are the values
# that the remote control uses:
#
# 1 - 0x04 (4)
# 2 - 0x08 (8)
# 3 - 0x0c (12)
# 4 - 0x10 (16)
# 5 - 0x14 (20)
# 6 - 0x18 (24)
# 7 - 0x1c (28)
# 8 - 0x20 (32)
# 9 - 0x24 (36)
# 10 - 0x28 (40)
#
# Set here what you want the maximum speed (decimal) of the motor to be.
# You can increase this at your own risk.  Should be set to any positive 
# integer value.
MAX_MASSAGE_SPEED = os.environ.get("MAX_MASSAGE_SPEED", 40)
MAX_MASSAGE_SPEED = int(MAX_MASSAGE_SPEED)
print("Maximum massage speed set to " + str(MAX_MASSAGE_SPEED))

# My bed has 4 massage wave speeds.  Perhaps some other bases have more.
# Adjust to match your bed.
MAX_WAVES = os.environ.get("MAX_WAVES", 4)
MAX_WAVES = int(MAX_WAVES)
print("Number of wave settings is " + str(MAX_WAVES))

# If your bed has the tilt function, rather than lumbar support, set this to True.
# Set to False if you have lumbar adjustment.
USE_TILT = os.environ.get("USE_TILT", True)
print("Using tilt function rather than lumbar: " + str(USE_TILT))

# This is the (decimal) tilt position that reprents when the bed is flat.  On the
# Reverie R650, flat is 36 (0x24).
TILT_FLAT = os.environ.get("TILT_FLAT", 36)
TILT_FLAT = int(TILT_FLAT)
print("Bed's flat position tilt is " + str(TILT_FLAT))

###############################################################################
# End User Config
###############################################################################


###############################################################################
# Function/Service Declarations
###############################################################################

def findBed():
	class ScanDelegate(DefaultDelegate):
		def __init__(self):
			DefaultDelegate.__init__(self)

	print("Scanning for Reverie Powerbases...")

	scanner = Scanner().withDelegate(ScanDelegate())
	devices = scanner.scan(10.0)
	
	for device in devices:
		#print ("Device %s (%s), RSSI=%d dB" % (device.addr, device.addrType, device.rssi))
		for (adtype, desc, value) in device.getScanData():
			#print ("	 %s = %s" % (desc, value))
			if desc == "Complete Local Name" and value == "RevCB_A1":
				print("Detected Reverie Powerbase: %s" % (device.addr))
				return device.addr
	return "None"

# Take the individual position values, and construct the HEX string needed to
# send the command as one string.

def MakePosition(position):
	# Set the head, feet, and tilt into the correct part of the HEX string
	# to be sent to the bed.
	return "00"+position[0]+position[1]+position[2]+"00000000000000"

def getBedValue(getBedValue):
	return str(int.from_bytes(getBedValue.read(), byteorder=sys.byteorder))

def setBedPosition(setBedPosition,position):
	setBedPosition.write(bytes.fromhex(MakePosition(position)))
	return

def setBedValue(setBedValue,percentage):
	setBedValue.write(bytes.fromhex(percent2hex(percentage)))
	return

# Convert a percentage (0-100 decimal) to Hex (0x00-0x64 hex)

def percent2hex(percentage):
	percentage=int(percentage)

	if percentage > 100:
		percentage = 100
	if percentage < 0:
		percentage = 0

	# We need a zero padded 2 byte hex value
	hexformat="{value:02x}"

	return hexformat.format(value=percentage)

# This waits for the bed to read the desired postion (ish) by polling
# the position repeatedly until it gets close to the desired position.	Since
# the bed sometimes misses by 1 or 2, I couldn't test for the exact
# set value.  I just wait until it's within 2, and call it good.
# If it hasn't reached the value after TOOLONG probes, assume it's never going to
# and stop polling.

def moveWait(service,desired):
	TOOLONG=512
	deadmancheck=1

	# The timeout for the light object in homekit is VERY short, and if
	# you wait for the bed to reach its position, it causes homekit
	# to be unhappy, so we need to "fire and forget" and just tell it
	# that it made it to keep homekit happy.  When I find a better method
	# of interacting with homekit, I'll adjust this accordingly.
	return int(desired)
	
	def readService(service):
		return int.from_bytes(service.read(), byteorder=sys.byteorder)

	check=readService(service)
	while not math.isclose(check,int(desired),abs_tol=2):
		if deadmancheck > TOOLONG:
			break
		check=readService(service)
		deadmancheck += 1


###############################################################################
# Web API (flask) event loop definition
#
# All the @app.route() functions are URL calls to get or set values with the
# bed.  Flask creates and event loop that will wait for a call to the defined
# path, and return the appropriate value (the current setting, or what it did).
###############################################################################

app = Flask(__name__)





# # For the main API page, present a brief help message on usage.
# # The html is stored in a "templates" directory in the same location as
# # this script runs from.

@app.route('/')
@app.route('/index')
@app.route('/help')
def index():
	pagetitle = 'Reverie Controller'
	return render_template('help.html', title=pagetitle)

###############################################################################
# Functions to control vendor named fixed positions
###############################################################################

@app.route("/flat")
def setFlat():
	global position

	# head, feet, tilt
	position=FLAT

	setBedPosition(PositionBed, position)

# Since the moveWait function will pass through if the
# position is already reached, I use all three here so
# that it will wait on whichever one takes the longest.
#
# The 16 means base 16 i.e. hex

	moveWait(PositionHead,int(position[0],16))
	moveWait(PositionFeet,int(position[1],16))
	moveWait(PositionTilt,int(position[2],16))

	return 'Position Set to Flat'

@app.route("/zeroG")
def setZeroG():
	global position

	# head, feet, tilt
	position=ZEROG

	setBedPosition(PositionBed, position)

	# Since the moveWait function will pass through if the
	# position is already reached, I use all three here so
	# that it will wait on whichever one takes the longest.
	#
	# The 16 means base 16 i.e. hex

	moveWait(PositionHead,int(position[0],16))
	moveWait(PositionFeet,int(position[1],16))
	moveWait(PositionTilt,int(position[2],16))

	return 'Position Set to zeroG'

@app.route("/noSnore")
def setNoSnore():
	global position

	# head, feet, tilt
	position=NOSNORE

	setBedPosition(PositionBed, position)
	
	# Since the moveWait function will pass through if the
	# position is already reached, I use all three here so
	# that it will wait on whichever one takes the longest.
	#
	# The 16 means base 16 i.e. hex

	moveWait(PositionHead,int(position[0],16))
	moveWait(PositionFeet,int(position[1],16))
	moveWait(PositionTilt,int(position[2],16))

	return 'Position Set to noSnore'

###############################################################################
# Functions to control the movement functions
###############################################################################

@app.route("/setHead/<percentage>")
def setHead(percentage):
	global position

	# Just change the head postion.	 The other values were read at the start of the loop.

	# This is a real-world correction.  When you set the bed to 0, it sometimes
	# still shows 1 if you query it.  This allows Homekit to see it as flat, even
	# if the bed returns 1%.	
	percentage = int(percentage)
	if percentage == 1:
		percentage = 0

	position[0]=percent2hex(percentage)

	setBedPosition(PositionBed, position)

	moveWait(PositionHead,percentage)

	return 'Head Position Set to: '+str(percentage)

@app.route("/getHead")
def getHead():
	return getBedValue(PositionHead)

@app.route("/setFeet/<percentage>")
def setFeet(percentage):
	global position

	# Just change the feet postion.	 The other values were read at the start of the loop.

	# This is a real-world correction.  When you set the bed to 0, it sometimes
	# still shows 1 if you query it.  This allows Homekit to see it as flat, even
	# if the bed returns 1%.
	percentage = int(percentage)
	if percentage == 1:
		percentage = 0

	position[1]=percent2hex(percentage)

	setBedPosition(PositionBed, position)

	moveWait(PositionFeet,percentage)

	return 'Feet Position Set to: '+str(percentage)

@app.route("/getLumbar")
def getLumbar():
	return getBedValue(PositionLumbar)

@app.route("/setLumbar/<percentage>")
def setLumbar(percentage):
	global position

	# Just change the lumbar postion. The other values were read at the start of the loop.

	# This is a real-world correction.  When you set the bed to 0, it sometimes
	# still shows 1 if you query it.  This allows Homekit to see it as flat, even
	# if the bed returns 1%.
	percentage = int(percentage)
	if percentage == 1:
		percentage = 0

	position[2]=percent2hex(percentage)

	setBedPosition(PositionBed, position)

	moveWait(PositionLumbar,percentage)

	return 'Lumbar Position Set to: '+str(percentage)

@app.route("/getFeet")
def getFeet():
	return getBedValue(PositionFeet)

@app.route("/setTilt/<percentage>")
def setTilt(percentage):
	global position

	# A little "magic" here to frame 50% around the value 36, which is the (decimal)
	# position of the tilt when the bed is flat.
	# i.e. 0-50% ranges 0-36, and 51-100% is 37-100.

	percentage=int(percentage)

	if percentage <= 50:
		tilt = TILT_FLAT * percentage / 50
	else:
		tilt = TILT_FLAT + ( 100 - TILT_FLAT ) * ( percentage - 50 ) / 50

	adjusted_percentage = round(int(tilt))

	# Just change the feet postion.	 The other values were read at the start of the loop.

	position[2]=percent2hex(adjusted_percentage)

	setBedPosition(PositionBed, position)

	moveWait(PositionTilt, adjusted_percentage)

	return 'Tilt Set to: '+str(percentage)

@app.route("/getTilt")
def getTilt():
	percentage = int(getBedValue(PositionTilt))

	# This reverses the "magic" done earlier to present the percentage so that
	# when the bed is flat, it will be 50%.
	if percentage <= TILT_FLAT:
		tilt = 50 * percentage / TILT_FLAT
	else:
		tilt = 50 + 50 * ( percentage - TILT_FLAT ) / ( 100 - TILT_FLAT )

	return str(round(tilt))

###############################################################################
# Functions to control the massager functions
###############################################################################

@app.route("/setHeadMassage/<percentage>")
def setHeadMassage(percentage):

	# Make sure that the specified value is an integer that falls into the range 0 - 100.
	percentage=int(percentage)

	if percentage > 100:
		percentage = 100
	if percentage < 0:
		percentage = 0

	# Adjust the percentage to the range 0 - MAX_MASSAGE_SPEED defined at the top
	adjusted_percentage = round(int(percentage) / 100 * MAX_MASSAGE_SPEED)

	setBedValue(MassageHead, adjusted_percentage)
	
	return 'Head Massage Set to: '+str(percentage)

@app.route("/getHeadMassage")
def getHeadMassage():
	# Simply return the massage speed, adjusted for the MAX_MASSAGE_SPEED range
	return str(round(int(getBedValue(MassageHead)) * 100 / MAX_MASSAGE_SPEED))

@app.route("/setFeetMassage/<percentage>")
def setFeetMassage(percentage):

	# Make sure that the specified value is an integer that falls into the range 0 - 100.
	percentage=int(percentage)

	if percentage > 100:
		percentage = 100
	if percentage < 0:
		percentage = 0

	# Adjust the percentage to the range 0 - MAX_MASSAGE_SPEED defined at the top
	adjusted_percentage = round(int(percentage) / 100 * MAX_MASSAGE_SPEED)
	
	setBedValue(MassageFeet, adjusted_percentage)

	return 'Feet Massage Set to: '+str(percentage)

@app.route("/getFeetMassage")
def getFeetMassage():
	# Simply return the massage speed, adjusted for the MAX_MASSAGE_SPEED range
	return str(round(int(getBedValue(MassageFeet)) * 100 / MAX_MASSAGE_SPEED))

@app.route("/setWaveMassage/<setting>")
def setWaveMassage(setting):
	# There are MAX_WAVE wave massage speeds + off (0)
	# Make sure we are dealing with an integer, and keep it within range.

	setting=int(setting)
	
	if setting < 0:
		setting = 0
	if setting > MAX_WAVES:
		setting =  MAX_WAVES

	setBedValue(MassageWave, setting)

	return 'Wave Massage Set to: '+str(setting)

@app.route("/getWaveMassage")
def getWaveMassage():
	return str(getBedValue(MassageWave))

@app.route("/stopMassage")
def setStopMassage():
	setBedValue(MassageHead, 0)
	setBedValue(MassageFeet, 0)
	setBedValue(MassageWave, 0)

	return "All Massages Stopped"

###############################################################################
# Functions to control the under-bed light
###############################################################################

@app.route("/light/on")
def setLightOn():
	# Must be 64.  All other values are off.
	setBedValue(Light, 64)
	return 'Light On'

@app.route("/light/off")
def setLightOff():
	setBedValue(Light, 0)
	return 'Light Off'

@app.route("/light/status")
def getLightStatus():
	# 0-63 are off, 64 is on
	if ( int.from_bytes(Light.read(), byteorder=sys.byteorder) == 64):
		return '1'
	else:
		return '0'

###############################################################################
# Main Program Starts
###############################################################################


if DEVICE_MAC == "Auto":
	DEVICE_MAC = findBed()

if DEVICE_MAC == "None":
	print("No Reverie Powerbase found.")
	sys.exit()

# If this is set to 0 or a negative number(which technically makes no sense), 
# it will be invalid or cause a divide by zero and explode.

if MAX_MASSAGE_SPEED <= 0:
	MAX_MASSAGE_SPEED = 1
	
# Open a connection to the bed.  This might fail, as the bed has no security and
# only allows one device connection at a time.  So, for example, if you have used the
# bed's remote and it hasn't closed its connection yet, this one will fail.  Just
# re-run until you get a connection.

connected=False
MAXTRIES = 5
check = 1
while (MAXTRIES >= check and connected == False):
	try:
		print("Attempting to connect to "+DEVICE_MAC+" (Try "+str(check)+"/"+str(MAXTRIES)+")")
		dev = btle.Peripheral(DEVICE_MAC, "random")
		# Since service UUIDs that begin with 0000 are supposed to be reserved,
		# I am looking for a UUID that is anything else.  This will assign the
		# first UUID it finds.  With the Reverie beds, this SHOULD be adequate.
		for primary in dev.services:
			if str(primary.uuid)[:4] != "0000":
				service=dev.getServiceByUUID(primary.uuid)
		connected = True
	except:
		check += 1
		time.sleep(5)
		pass

if connected == False:
	print("Error connecting to device "+DEVICE_MAC+" after "+str(MAXTRIES)+" tries.")
	sys.exit()

# This is a list of the services by UUID to controlling the bed

PositionBed=service.getCharacteristics(forUUID="db8010d0-f324-29c3-38d1-85c0c2e86885")[0]

PositionHead=service.getCharacteristics(forUUID="db801041-f324-29c3-38d1-85c0c2e86885")[0]
PositionFeet=service.getCharacteristics(forUUID="db801042-f324-29c3-38d1-85c0c2e86885")[0]

# You'll notice that Tilt and Lumbar use the same UUID.  This is on purpose.  The 
# beds have either tilt or lumbar.  Lumbar (I assume) is a straight 0-100 setting
# where you have no lumbar lift to the maximum lift.  Tilt, however is "flat" at 
# 36% (raw decimal).  I have logic to convert it to a straight 0-100, where 50% is flat.
#
# Obviously, use only one function or the other.
PositionTilt=service.getCharacteristics(forUUID="db801040-f324-29c3-38d1-85c0c2e86885")[0]
PositionLumbar=service.getCharacteristics(forUUID="db801040-f324-29c3-38d1-85c0c2e86885")[0]

MassageHead=service.getCharacteristics(forUUID="db801061-f324-29c3-38d1-85c0c2e86885")[0]
MassageFeet=service.getCharacteristics(forUUID="db801060-f324-29c3-38d1-85c0c2e86885")[0]
MassageWave=service.getCharacteristics(forUUID="db801080-f324-29c3-38d1-85c0c2e86885")[0]

Light=service.getCharacteristics(forUUID="db8010A0-f324-29c3-38d1-85c0c2e86885")[0]

# Get the current positions of the bed components.	We keep these values
# so that when an adjustment of one is changed, the other values can be
# maintained and it won't interrupt if you make another change before
# the first is finished.  In the functions below, you have to set position
# as a global variable so that the changes will persist across events.
#
# position is defined as a list where [ 0, 1, 2 ] are [ head, feet, tilt ]
#
# i.e. to get/set the position of the feet would be position[1]

position=[ PositionHead.read().hex(), PositionFeet.read().hex(), PositionTilt.read().hex() ]

if USE_TILT == True:
	# head, feet, tilt (raw hex values)
	FLAT=["00", "00", "24"]
	ZEROG=["1f", "46", "24"]
	NOSNORE=["0b", "00", "24"]
else:
	# head, feet, lumbar (raw hex values)
	FLAT=["00", "00", "00"]
	ZEROG=["1f", "46", "00"]
	NOSNORE=["0b", "00", "00"]

# I haven't yet figured out how to get the exception out of the Flask thread
# to have it re-connect to the bed.  If it's run as a service, having it kill
# itself here, systemd will restart it for you.
@app.errorhandler(Exception)
def special_exception_handler(error):
	print("Bluetooth Connection Lost.  Exiting.")
	os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))
	return 'Bluetooth Connection Lost', 500

if __name__ == '__main__':
	app.run(host=RPI_LOCAL_IP, port=RPI_LISTEN_PORT, debug=False)