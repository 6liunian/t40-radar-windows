"""Native WinUSB/libusb alternative. Requires WinUSB binding on 0cf3:1022.

Defaults to read-only BMI chip identification. --boot starts the RAM firmware;
--services --ap --serve progressively enable the existing higher layers.
"""
import argparse
import os
import socket
from contextlib import closing
from pathlib import Path
import usb1
from ath6kl_win.protocol import build_bmi_get_target_info, parse_target_info, EndpointMap
from ath6kl_win.boot import boot
from ath6kl_win.htc import connect_services, decode, HtcUsbTransport
from ath6kl_win.ap import start_ap
from ath6kl_win.monitor import serve
from ath6kl_win.usb_bulk import UsbBulk

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('boot', 'services', 'ap', 'serve'):
        parser.add_argument('--' + flag, action='store_true')
    parser.add_argument('--tap-guid', help='Optional existing TAP adapter for 192.168.8.3 diagnostics')
    parser.add_argument('--tap-ip', choices=('192.168.8.1', '192.168.8.3'), default='192.168.8.3')
    parser.add_argument('--tap-direct', action='store_true', help='Forward UDP through Windows IP stack too')
    args = parser.parse_args()
    if args.tap_direct and (not args.tap_guid or args.tap_ip != '192.168.8.1'):
        parser.error('--tap-direct requires --tap-guid and --tap-ip 192.168.8.1')
    if args.services and not args.boot or args.ap and not args.services or args.serve and not args.ap:
        parser.error('--serve requires --ap --services --boot')
    base = Path(__file__).parent
    firmware_dir = Path(os.environ.get('RADAR_FIRMWARE_DIR', str(base / 'firmware')))
    runtime_dir = Path(os.environ.get('RADAR_RUNTIME_DIR', str(base / 'runtime')))
    with usb1.USBContext() as context:
        handle = context.openByVendorIDAndProductID(0x0cf3, 0x1022, skip_on_error=False)
        if handle is None:
            raise RuntimeError('USBWLAN 0CF3:1022 unavailable. Check physical connection and WinUSB binding.')
        with closing(handle):
            with handle.claimInterface(0):
                device = handle.getDevice()
                endpoints = [ep.getAddress() for config in device for interface in config
                             for setting in interface if setting.getNumber() == 0 and setting.getAlternateSetting() == 0
                             for ep in setting]
                EndpointMap().validate(endpoints)
                def control(incoming, request, payload):
                    if incoming:
                        data = handle.controlRead(0xc0, request, 0, 0, payload, timeout=3000)
                        if len(data) != payload:
                            raise RuntimeError('Short control read')
                        return bytes(data)
                    count = handle.controlWrite(0x40, request, 0, 0, payload, timeout=3000)
                    if count != len(payload):
                        raise RuntimeError('Short control write')
                bulk = UsbBulk(handle)
                control(False, 1, build_bmi_get_target_info())
                info = parse_target_info(control(True, 2, 12))
                print(info, flush=True)
                if args.boot:
                    if not info.is_expected_ar6004_hw30:
                        raise RuntimeError('Unsupported chip')
                    boot(control, firmware_dir)
                    bulk = HtcUsbTransport(bulk)
                    ready = bulk(0x82, 4096)
                    ep, payload = decode(ready)
                    if ep or len(payload) != 10 or payload[:2] != b'\x01\0':
                        raise RuntimeError('Invalid HTC ready')
                    print('HTC_READY', ready.hex(), flush=True)
                    if args.services:
                        services, mac = connect_services(bulk, ready)
                        if args.ap:
                            start_ap(bulk, services, mac)
                            if args.serve:
                                serve(bulk, services, mac, runtime_dir, tap_guid=args.tap_guid,
                                      tap_ip=socket.inet_aton(args.tap_ip), tap_direct=args.tap_direct)

if __name__ == '__main__':
    main()
