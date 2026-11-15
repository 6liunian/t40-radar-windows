"""Persistent AP receive diagnostics. Stop gracefully by creating runtime/stop."""
import json
import os
import struct
import time
import threading
from collections import deque
from .htc import decode, frame
from .network import unpack_frames, pack_data, respond
from .udp_bridge import UdpBridge

def publish_status(directory, state):
    """Windows readers may briefly deny replacement; telemetry is best effort."""
    try:
        temporary = directory / 'status.tmp'
        temporary.write_text(json.dumps(state), encoding='utf-8')
        temporary.replace(directory / 'status.json')
        return True
    except OSError:
        return False

def classify(endpoint, payload, control_endpoint, mac):
    if endpoint != control_endpoint:
        return {'kind': 'data', 'endpoint': endpoint, 'bytes': len(payload), 'sample': payload[:96].hex()}
    if len(payload) < 6:
        raise ValueError('Truncated WMI header')
    event = struct.unpack_from('<H', payload)[0]
    result = {'kind': 'event', 'event': hex(event), 'bytes': len(payload)}
    if event == 0x1002 and len(payload) >= 25:
        peer = payload[8:14]
        result.update(kind='ap_started' if peer == mac else 'station_associated', mac=peer.hex(':'))
        if peer != mac:
            result['aid'] = payload[7]
    elif event == 0x1003:
        result.update(kind='disconnect', sample=payload[:48].hex())
    elif event == 0x1005:
        result.update(kind='command_error', sample=payload.hex())
    return result

def serve(bulk, endpoints, mac, directory, tap_guid=None, tap_ip=None, tap_direct=False, read_bulk=None):
    read_bulk = read_bulk or bulk
    directory.mkdir(exist_ok=True)
    stop = directory / 'stop'
    if stop.exists():
        raise RuntimeError('Remove runtime/stop before starting a new session')
    state = {'pid': os.getpid(), 'started': time.time(), 'state': 'running', 'data_frames': 0, 'replies': 0, 'events': 0, 'stations': [],
             'udp_rx': 0, 'udp_tx': 0, 'udp_dropped': 0, 'replies_sent': 0, 'tap_direct': tap_direct,
             'parse_errors': 0, 'tcp_rx': 0, 'htc_dropped': 0}
    invalid_times = deque()
    last_publish = 0.0
    def publish(force=False):
        nonlocal last_publish
        now = time.monotonic()
        if not force and now - last_publish < 1:
            return
        state['updated'] = time.time()
        if publish_status(directory, state):
            last_publish = now
    publish()
    print('AP_SERVING', os.getpid(), flush=True)
    bridge = UdpBridge(bulk, endpoints[0x101], mac, tap_guid=tap_guid, tap_ip=tap_ip, tap_direct=tap_direct)
    tx_stop = threading.Event()
    tx_errors = []
    def transmit():
        try:
            while not tx_stop.is_set():
                bridge.poll()
                tx_stop.wait(0.005)
        except Exception as exc:
            tx_errors.append(exc)
            print('TX_FAILED', repr(exc), flush=True)
    tx_worker = threading.Thread(target=transmit, name='radar-usb-tx')
    tx_worker.start()
    try:
        with (directory / 'events.jsonl').open('a', encoding='utf-8', buffering=1) as log:
            while not stop.exists():
                if tx_errors:
                    raise tx_errors[0]
                state.update(udp_rx=bridge.rx, udp_tx=bridge.tx, udp_dropped=bridge.dropped,
                             replies_sent=bridge.replies_sent)
                if bridge.tap:
                    state.update(tap_rx=bridge.tap.rx, tap_tx=bridge.tap.tx)
                try:
                    packet = read_bulk(0x82, 4096)
                except TimeoutError:
                    publish()
                    continue
                if not packet:
                    # USB zero-length completion is not an HTC packet.
                    publish()
                    continue
                try:
                    endpoint, payload = decode(packet)
                    if endpoint not in (0, *endpoints.values()):
                        raise ValueError('Unknown HTC endpoint')
                except ValueError as exc:
                    # Preserve evidence before a bounded launcher recovery.
                    name = f'bad-htc-{os.getpid()}.bin'
                    state['htc_dropped'] += 1
                    if state['htc_dropped'] <= 3:
                        try:
                            (directory / name).write_bytes(packet)
                        except OSError:
                            pass
                    state['bad_htc'] = {'file': name, 'bytes': len(packet), 'header': packet[:32].hex()}
                    print('HTC_INVALID', state['bad_htc'], flush=True)
                    now = time.monotonic()
                    while invalid_times and now-invalid_times[0] > 10:
                        invalid_times.popleft()
                    invalid_times.append(now)
                    if len(invalid_times) > 8:
                        raise RuntimeError('Repeated invalid HTC packets in 10 seconds') from exc
                    # Like ath6kl's free_skb path, discard the damaged transfer.
                    # Do not splice arbitrary bytes into fabricated HTC frames.
                    publish(force=True)
                    continue
                if not payload:
                    continue
                record = classify(endpoint, payload, endpoints[0x100], mac)
                record['time'] = time.time()
                state['events'] += 1
                if record['kind'] == 'data':
                    state['data_frames'] += 1
                    try:
                        decoded = unpack_frames(payload)
                        for ethernet in decoded:
                            bridge.receive(ethernet)
                            record['ethertype'] = ethernet[12:14].hex()
                            if len(ethernet)>=34 and ethernet[12:14]==b'\x08\x00' and ethernet[23]==6:
                                state['tcp_rx'] += 1
                                record['tcp'] = ethernet[:96].hex()
                            reply = None if tap_direct else respond(ethernet, mac)
                            if reply and bridge.enqueue_reply(reply):
                                state['replies'] += 1
                                print('NETWORK_REPLY_QUEUED', state['replies'], record['ethertype'], flush=True)
                    except ValueError as exc:
                        record['parse_error'] = str(exc)
                        state['parse_errors'] += 1
                    diagnostic = ('parse_error' in record and state['parse_errors']<=20) or ('tcp' in record and state['tcp_rx']<=30)
                    if not diagnostic and state['data_frames'] > 20 and state['data_frames'] % 1000:
                        continue
                if record['kind'] == 'station_associated':
                    if record['mac'] not in state['stations']:
                        state['stations'].append(record['mac'])
                if record['kind'] == 'disconnect':
                    state['last_disconnect'] = record
                log.write(json.dumps(record) + '\n')
                print(json.dumps(record), flush=True)
                publish()
    except BaseException as exc:
        state['state'] = 'error'
        state['error'] = repr(exc)
        raise
    finally:
        tx_stop.set()
        tx_worker.join()
        bridge.close()
        if state['state'] == 'running':
            state['state'] = 'stopped'
        publish(force=True)
