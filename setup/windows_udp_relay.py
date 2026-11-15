#!/usr/bin/env python3
"""Relay radar UDP and SSH between a Windows host and the radar AP subnet."""

from __future__ import annotations

import argparse
import errno
import json
import os
import select
import selectors
import socket
import threading
import time


TRANSIENT_SEND_ERRORS = {errno.EAGAIN, errno.EWOULDBLOCK, errno.ENOBUFS}
_last_drop_log: dict[str, float] = {}
HEALTH_PATH = "/tmp/dji-radar-relay-health.json"


def write_health(state: dict[str, float]) -> None:
    """Publish link activity for the independent USBWLAN watchdog."""
    temp_path = f"{HEALTH_PATH}.tmp"
    try:
        with open(temp_path, "w", encoding="ascii") as handle:
            json.dump(state, handle, separators=(",", ":"))
        os.replace(temp_path, HEALTH_PATH)
    except OSError:
        # Health reporting must never interrupt the packet relay.
        pass


def udp_socket(address: tuple[str, int]) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
    sock.bind(address)
    sock.setblocking(False)
    return sock


def safe_send(sock: socket.socket, data: bytes, destination: tuple[str, int], link: str) -> bool:
    """Drop a datagram under transient backpressure instead of killing the relay."""
    try:
        sock.sendto(data, destination)
        return True
    except OSError as exc:
        if exc.errno not in TRANSIENT_SEND_ERRORS:
            raise
        now = time.monotonic()
        if now - _last_drop_log.get(link, 0.0) >= 5.0:
            print(f"[relay] {link} temporarily unavailable; dropping queued UDP", flush=True)
            _last_drop_log[link] = now
        return False


def tcp_pipe(client: socket.socket, radar_ip: str, radar_port: int) -> None:
    upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        upstream.settimeout(4.0)
        upstream.connect((radar_ip, radar_port))
        upstream.settimeout(None)
        client.settimeout(None)
        peers = {client: upstream, upstream: client}
        while peers:
            readable, _, _ = select.select(list(peers), [], [], 30.0)
            if not readable:
                continue
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                peers[source].sendall(data)
    except OSError:
        return
    finally:
        client.close()
        upstream.close()


def tcp_proxy(listen_ip: str, listen_port: int, radar_ip: str, radar_port: int) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((listen_ip, listen_port))
    server.listen(8)
    print(f"[relay] SSH {listen_ip}:{listen_port} -> {radar_ip}:{radar_port}", flush=True)
    while True:
        client, _ = server.accept()
        threading.Thread(
            target=tcp_pipe,
            args=(client, radar_ip, radar_port),
            daemon=True,
        ).start()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows-ip", default="192.168.1.3")
    parser.add_argument("--lan-ip", default="192.168.1.100")
    parser.add_argument("--ap-ip", default="192.168.8.1")
    parser.add_argument("--radar-ip", default="192.168.8.2")
    parser.add_argument("--ssh-listen-port", type=int, default=10107)
    args = parser.parse_args()

    control_lan = udp_socket((args.lan_ip, 50007))
    control_ap = udp_socket((args.ap_ip, 50007))
    v2_lan = udp_socket((args.lan_ip, 40204))
    v2_ap = udp_socket((args.ap_ip, 40204))

    threading.Thread(
        target=tcp_proxy,
        args=(args.lan_ip, args.ssh_listen_port, args.radar_ip, 107),
        daemon=True,
    ).start()

    selector = selectors.DefaultSelector()
    for name, sock in (
        ("control_lan", control_lan),
        ("control_ap", control_ap),
        ("v2_lan", v2_lan),
        ("v2_ap", v2_ap),
    ):
        selector.register(sock, selectors.EVENT_READ, name)

    windows_control = (args.windows_ip, 50007)
    windows_v2 = (args.windows_ip, 40204)
    radar_control = (args.radar_ip, 50007)
    radar_v2 = (args.radar_ip, 40204)
    print(
        f"[relay] Windows {args.windows_ip} <-> {args.lan_ip} <-> "
        f"{args.ap_ip} <-> radar {args.radar_ip}",
        flush=True,
    )

    health = {
        "started_at": time.time(),
        "last_windows_control_at": 0.0,
        "last_radar_control_at": 0.0,
        "last_radar_v2_at": 0.0,
    }
    last_health_write = 0.0

    while True:
        for key, _ in selector.select(timeout=1.0):
            data, source = key.fileobj.recvfrom(65535)
            now = time.time()
            if key.data == "control_lan":
                windows_control = source
                health["last_windows_control_at"] = now
                safe_send(control_ap, data, radar_control, "control to radar")
            elif key.data == "control_ap":
                health["last_radar_control_at"] = now
                safe_send(control_lan, data, windows_control, "control to Windows")
            elif key.data == "v2_lan":
                windows_v2 = source
                safe_send(v2_ap, data, radar_v2, "V2 to radar")
            else:
                health["last_radar_v2_at"] = now
                safe_send(v2_lan, data, windows_v2, "V2 to Windows")
        now = time.time()
        if now - last_health_write >= 1.0:
            write_health(health)
            last_health_write = now


if __name__ == "__main__":
    main()
