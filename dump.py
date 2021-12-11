#!/usr/bin/python3

from flask import Flask
from flask import render_template
from bluepy import btle
import sys
import time
# TODO: You WILL need to change the mac address below to be the address of your bed's bluetooth module
DEVICE_MAC = "C8:D0:76:DD:C8:90"
# TODO: You WILL need to change the Local IP address below to be the address of your RPI
RPI_LOCAL_IP = "172.22.42.16"
# You do NOT need to change the below UUID if you have the same bed
DEVICE_UUID = "db801000-f324-29c3-38d1-85c0c2e86885"

dev = btle.Peripheral(DEVICE_MAC, "random")


def dump(obj):
   for attr in dir(obj):
       if hasattr( obj, attr ):
           print( "obj.%s (type = %s) = %s" % (attr, type(attr), getattr(obj, attr)))


# Device c8:d0:76:dd:c8:90 (random), RSSI=-67 dB
# 	 Flags = 06
# 	 Complete 128b Services = db801000-f324-29c3-38d1-85c0c2e86885
# 	 Complete Local Name = RevCB_A1
	 
for svc in dev.services:
	try:
		print(str(svc.uuid))

		#sys.exit()

		#dump(dev)
		#print()
		#dump(service)
		#print()

		service = dev.getServiceByUUID(svc.uuid)

		print (str(svc.uuid)[:4])
		if str(svc.uuid)[:4] != "0000":

			for i in service.getCharacteristics():
				#print(dir(i))
				#print(i.peripheral.getServices())
				#print(i)
				#dump(i)
				print(i.uuid, i.read().hex())
	except:
		print("Error reading UUID")
		pass

#print ( service.getCharacteristics(forUUID="db801041-f324-29c3-38d1-85c0c2e86885")[0].read().hex() )

#subService = service.getCharacteristics()[12]
# 00 [head] [foot] [lumbar/tilt] 00 00 00 00 00 00 00
# Other octets don't seem to have any function (on my bed)
# The tilt setting for "flat" is 0x24 
# i.e. Flat is:          "0000002400000000000000"
# My sleep position is:  "0000004100000000000000"
# My tv position is:     "00644f6400000000000000"
# Zero G is:             "0020482400000000000000"
# If the remote changes the position, the first octet is sometimes
# different.  I can't figure out what the value is for. Should I set
# to 13, since the remote does?
# Anti-Snore:13
# Flat:13
# Moving the head independently doesn't update db8010d0, so can't be used for status.
# db80102[0-2] seems to reflect the value of db80104[0-2]; [perhaps 20 is used for
# polling for current position.

#subService.write(bytes.fromhex("0000002400000000000000"))
#subService.write(bytes.fromhex("00"))

sys.exit()
