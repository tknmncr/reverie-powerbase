#!/usr/bin/python3

# scan.py - Scott Garrett
#
# Version 20211210-001
#
# This is a quick scan to locate Reverie Powerbases with bluetooth interfaces. 
# It will retuurn the MAC address that you specify in the reverie.py script. It
# assumes the local name will be "RevCB_A1".  If there are any other strings for
# other models, I can add them here.  I only have a model 650 to test against.

from bluepy.btle import Scanner, DefaultDelegate

class ScanDelegate(DefaultDelegate):
	def __init__(self):
		DefaultDelegate.__init__(self)

print("Scanning for Reverie Powerbases:")

scanner = Scanner().withDelegate(ScanDelegate())
devices = scanner.scan(10.0)

for dev in devices:
	#print ("Device %s (%s), RSSI=%d dB" % (dev.addr, dev.addrType, dev.rssi))
	for (adtype, desc, value) in dev.getScanData():
		#print ("	 %s = %s" % (desc, value))
		
		if desc == "Complete Local Name" and value == "RevCB_A1":
			print("Detected Reverie Powerbase: %s" % (dev.addr))