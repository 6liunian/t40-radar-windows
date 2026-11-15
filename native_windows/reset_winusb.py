"""Cold-reset only the validated AR6004 adapter, after its service has stopped.

Wire command matches ath6kl/usb.c diag_write32 and init.c init_hw_reset.
Firmware lives in RAM; this does not change the installed Windows driver.
"""
import struct
from contextlib import closing
import usb1


def main():
    with usb1.USBContext() as context:
        handle = context.openByVendorIDAndProductID(0x0cf3, 0x1022, skip_on_error=False)
        if handle is None:
            raise RuntimeError('USBWLAN not present')
        with closing(handle), handle.claimInterface(0):
            command = struct.pack('<IIII', 1, 0x4000, 0x100, 0)
            count = handle.controlWrite(0x40, 3, 0, 0, command, timeout=3000)
            if count != len(command):
                raise RuntimeError('Short cold-reset command')
            print('COLD_RESET_SENT', flush=True)


if __name__ == '__main__':
    main()
