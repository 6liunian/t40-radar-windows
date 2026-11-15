#!/bin/bash
set -eu

IFACE="wlan0"
IP_ADDR="192.168.8.1/24"
CONF="/opt/t40-radar-windows/setup/hostapd.conf"
ACCEPT_LIST="/opt/t40-radar-windows/setup/radar_accept.list"
DRIVER_DIR="/opt/t40-radar-windows/ar1021x_driver/ath6kl"

# Files may be deployed from Windows. Remove CRLF carriage returns before
# hostapd parses values such as driver=nl80211 and hw_mode=a.
sed -i 's/\r$//' "$CONF"
sed -i 's/\r$//' "$ACCEPT_LIST"

find_usb_device() {
    for dev in /sys/bus/usb/devices/*; do
        [ -r "$dev/idVendor" ] || continue
        [ -r "$dev/idProduct" ] || continue
        if [ "$(cat "$dev/idVendor")" = "0cf3" ] && \
           [ "$(cat "$dev/idProduct")" = "1022" ]; then
            printf '%s\n' "$dev"
            return 0
        fi
    done
    return 1
}

load_driver() {
    modprobe cfg80211
    if ! lsmod | grep -q '^ath6kl_core'; then
        insmod "$DRIVER_DIR/ath6kl_core.ko"
    fi
    if ! lsmod | grep -q '^ath6kl_usb'; then
        insmod "$DRIVER_DIR/ath6kl_usb.ko"
    fi
}

# The radar USBWLAN uses a project-local ath6kl build that is not installed
# into the distro module tree. This service runs as root, so load it on every
# VM boot before waiting for the network interface.
if ! lsmod | grep -q '^ath6kl_usb'; then
    load_driver
fi

# VMware may preserve USB power across a guest reboot. The AR1021X then
# times out while the driver downloads firmware (-110). Re-authorizing the
# exact device forces a clean USB enumeration and another driver probe.
while ! ip link show "$IFACE" >/dev/null 2>&1; do
    usb_dev="$(find_usb_device || true)"
    if [ -n "$usb_dev" ]; then
        printf '0\n' > "$usb_dev/authorized"
        sleep 2
        printf '1\n' > "$usb_dev/authorized"
        sleep 8
    else
        sleep 2
    fi
done

if command -v nmcli >/dev/null 2>&1; then
    nmcli device set "$IFACE" managed no || true
fi
ip addr flush dev "$IFACE"
ip addr add "$IP_ADDR" dev "$IFACE"
ip link set "$IFACE" up
exec /usr/sbin/hostapd "$CONF"
