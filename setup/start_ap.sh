#!/bin/bash

IFACE="wlan0"
IP_ADDR="192.168.8.1/24"
CONF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/hostapd.conf"

airmon-ng check kill
sed -i "s/^interface=.*/interface=$IFACE/" "$CONF"
ip addr flush dev "$IFACE"
ip addr add "$IP_ADDR" dev "$IFACE"
ip link set "$IFACE" up
hostapd -B "$CONF"
