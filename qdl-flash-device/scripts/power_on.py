#!/usr/bin/env python3
"""Power on the connected TAC device after flashing."""
import sys
import time
import os

os.chdir('/opt/qcom/Alpaca/examples/python/AutomationTestTAC')
import TACDev

WAIT_FOR_TAC = 15  # seconds max to wait for TAC to re-enumerate after EDL


def wait_for_tac() -> None:
    """Block until at least one TAC device re-enumerates (e.g. after EDL session)."""
    deadline = time.time() + WAIT_FOR_TAC
    while time.time() < deadline:
        if TACDev.GetDeviceCount() > 0:
            return
        time.sleep(1)
    print('ERROR: TAC device did not re-enumerate within '
          f'{WAIT_FOR_TAC}s.', file=sys.stderr)
    sys.exit(1)


def pick_device() -> object:
    """Return an opened TACDev device, prompting the user if multiple are present."""
    count = TACDev.GetDeviceCount()
    if count == 0:
        print('ERROR: No TAC device found.', file=sys.stderr)
        sys.exit(1)

    if count == 1:
        idx = 0
    else:
        print(f'\nMultiple TAC devices detected ({count}):')
        for i in range(count):
            dev = TACDev.GetDevice(i)
            label = getattr(dev, 'serial', None) or getattr(dev, 'name', None) or f'device {i}'
            print(f'  [{i + 1}] {label}')
        print()
        while True:
            raw = input(f'Select TAC device [1-{count}]: ').strip()
            if raw.isdigit() and 1 <= int(raw) <= count:
                idx = int(raw) - 1
                break
            print(f'Invalid choice. Enter a number between 1 and {count}.')

    dev = TACDev.GetDevice(idx)
    if dev is None or not dev.Open():
        print('ERROR: Could not open TAC device.', file=sys.stderr)
        sys.exit(1)
    return dev


wait_for_tac()
dev = pick_device()
dev.PowerOnButton()
print('Power on command sent.')
dev.Close()
