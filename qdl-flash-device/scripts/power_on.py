#!/usr/bin/env python3
"""Power on the connected TAC device."""
import sys
import time
import os
os.chdir('/opt/qcom/Alpaca/examples/python/AutomationTestTAC')

import TACDev

WAIT_FOR_TAC = 15  # seconds max to wait for TAC to re-enumerate

deadline = time.time() + WAIT_FOR_TAC
while time.time() < deadline:
    if TACDev.GetDeviceCount() > 0:
        break
    time.sleep(1)
else:
    print('ERROR: TAC device did not re-enumerate in time.', file=sys.stderr)
    sys.exit(1)

tacDevice = TACDev.GetDevice(0)
if tacDevice is None or not tacDevice.Open():
    print('ERROR: Could not open TAC device.', file=sys.stderr)
    sys.exit(1)

tacDevice.PowerOnButton()
print('Power on command sent.')
tacDevice.Close()
