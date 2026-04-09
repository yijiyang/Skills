#!/usr/bin/env python3
"""Boot the connected TAC device into EDL mode and wait for it to enumerate."""
import sys
import time

# Must run from this directory for TACDev.GetDevice() to work
import os
os.chdir('/opt/qcom/Alpaca/examples/python/AutomationTestTAC')

import TACDev

WAIT_AFTER_EDL = 4  # seconds

count = TACDev.GetDeviceCount()
if count == 0:
    print('ERROR: No TAC device found.', file=sys.stderr)
    sys.exit(1)

tacDevice = TACDev.GetDevice(0)
if tacDevice is None or not tacDevice.Open():
    print('ERROR: Could not open TAC device.', file=sys.stderr)
    sys.exit(1)

tacDevice.BootToEDLButton()
print(f'EDL command sent. Waiting {WAIT_AFTER_EDL}s...')
time.sleep(WAIT_AFTER_EDL)
tacDevice.Close()
print('Done.')
