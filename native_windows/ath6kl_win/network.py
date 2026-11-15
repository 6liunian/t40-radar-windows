"""Small diagnostic Ethernet responder, not a general Windows IP interface."""
import struct

HOST_IP = bytes([192, 168, 8, 1])

def unpack_frames(payload):
    """Decode WMI RX metadata and AP A-MSDU subframes, with four-byte padding.

    Layout follows ath6kl txrx.c / aggr.c. Firmware supplies an outer
    Ethernet header before the aggregate, even for a single subframe.
    Validate the entire aggregate before returning any packet.
    """
    if len(payload)<6:raise ValueError('Short WMI data frame')
    _,info,info2,info3=struct.unpack_from('<bBHH',payload)
    if info & 0xc0 or info3 & 15:raise ValueError('Unsupported WMI data format')
    metadata=info2>>13
    if metadata not in (0,1,2):raise ValueError('Unsupported WMI RX metadata')
    offset=6+(info3>>8)+{0:0,1:6,2:3}[metadata]
    data=payload[offset:]
    def ethernet(frame):
        if len(frame)<22 or frame[14:20]!=bytes.fromhex('aaaa03000000'):
            raise ValueError('Unsupported LLC SNAP')
        length=struct.unpack_from('!H',frame,12)[0]
        if length<8 or length>len(frame)-14:raise ValueError('Invalid 802.3 length')
        return frame[:12]+frame[20:14+length]
    if not info2 & 0x1000:return [ethernet(data)]
    if len(data)<14:raise ValueError('Short A-MSDU outer header')
    data=data[14:];packets=[];pos=0
    while pos<len(data):
        if len(data)-pos<14:raise ValueError('Short A-MSDU subframe')
        length=struct.unpack_from('!H',data,pos+12)[0]+14
        if pos+length>len(data):raise ValueError('Truncated A-MSDU subframe')
        packets.append(ethernet(data[pos:pos+length]))
        pos+=length
        if pos<len(data):
            pos+=(-length)%4
            if pos>=len(data):raise ValueError('Trailing A-MSDU padding')
    if not packets:raise ValueError('Empty A-MSDU')
    return packets

def unpack_data(payload):
    if len(payload) < 28:
        raise ValueError('Short WMI data frame')
    _, info, info2, info3 = struct.unpack_from('<bBHH', payload)
    if info & 0xc0 or info2 & 0xf000 or info3 & 15:
        raise ValueError('Unsupported WMI data format')
    data = payload[6 + (info3 >> 8):]
    if len(data) < 22 or data[14:20] != bytes.fromhex('aaaa03000000'):
        raise ValueError('Unsupported LLC SNAP')
    length = struct.unpack_from('!H', data, 12)[0]
    if length < 8 or length > len(data) - 14:
        raise ValueError('Invalid 802.3 length')
    return data[:12] + data[20:14 + length]

def pack_data(ethernet):
    if len(ethernet) < 14:
        raise ValueError('Short Ethernet frame')
    ethernet = limit_radar_tcp_mss(ethernet)
    snap = bytes.fromhex('aaaa03000000') + ethernet[12:]
    return bytes(6) + ethernet[:12] + struct.pack('!H', len(snap)) + snap


def limit_radar_tcp_mss(ethernet, maximum=384):
    """Advertise a small TCP segment to keep radar RX frames below USB 512 B.

    Only the dedicated radar IPv4 TCP SYN is changed. Recompute its checksum;
    leave data, acknowledgments, non-radar packets and invalid options alone.
    """
    if len(ethernet)<54 or ethernet[12:14]!=b'\x08\x00':return ethernet
    ip=ethernet[14:]
    ihl=(ip[0]&15)*4
    total=struct.unpack_from('!H',ip,2)[0]
    if (ip[0]>>4!=4 or ihl<20 or total>len(ip) or total<ihl+20 or ip[9]!=6
            or ip[16:20]!=bytes([192,168,8,2]) or struct.unpack_from('!H',ip,6)[0]&0x3fff):
        return ethernet
    tcp=bytearray(ip[ihl:total]);header=(tcp[12]>>4)*4
    if not tcp[13]&2 or header<20 or header>len(tcp):return ethernet
    pos=20;changed=False
    while pos<header:
        kind=tcp[pos]
        if kind==0:break
        if kind==1:pos+=1;continue
        if pos+2>header:return ethernet
        length=tcp[pos+1]
        if length<2 or pos+length>header:return ethernet
        if kind==2:
            if length!=4:return ethernet
            value=struct.unpack_from('!H',tcp,pos+2)[0]
            if value>maximum:
                struct.pack_into('!H',tcp,pos+2,maximum);changed=True
        pos+=length
    if not changed:return ethernet
    tcp[16:18]=b'\0\0'
    pseudo=ip[12:20]+struct.pack('!BBH',0,6,len(tcp))
    struct.pack_into('!H',tcp,16,checksum(pseudo+tcp))
    print(f'RADAR_TCP_MSS {maximum}',flush=True)
    return ethernet[:14+ihl]+bytes(tcp)+ethernet[14+total:]

def checksum(data):
    data += bytes(len(data) & 1)
    total = sum(struct.unpack('!' + 'H' * (len(data) // 2), data))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return (~total) & 65535

def respond(ethernet, mac):
    if len(ethernet) < 14:
        return None
    kind = ethernet[12:14]
    packet = ethernet[14:]
    if kind == b'\x08\x06':
        if len(packet) < 28 or packet[:8] != bytes.fromhex('0001080006040001') or packet[24:28] != HOST_IP:
            return None
        sender_mac, sender_ip = packet[8:14], packet[14:18]
        reply = bytes.fromhex('0001080006040002') + mac + HOST_IP + sender_mac + sender_ip
        return sender_mac + mac + kind + reply
    if kind == b'\x08\x00' and len(packet) >= 28:
        ihl = (packet[0] & 15) * 4
        total = struct.unpack_from('!H', packet, 2)[0]
        if packet[0] >> 4 != 4 or ihl < 20 or total < ihl + 8 or total > len(packet):
            return None
        if packet[9] != 1 or packet[16:20] != HOST_IP or checksum(packet[:ihl]) or struct.unpack_from('!H', packet, 6)[0] & 0x3fff:
            return None
        icmp = packet[ihl:total]
        if icmp[:2] != b'\x08\0' or checksum(icmp):
            return None
        reply = b'\0\0\0\0' + icmp[4:]
        reply = reply[:2] + struct.pack('!H', checksum(reply)) + reply[4:]
        ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(reply), 0, 0, 64, 1, 0, HOST_IP, packet[12:16])
        ip = ip[:10] + struct.pack('!H', checksum(ip)) + ip[12:]
        return ethernet[6:12] + mac + kind + ip + reply
    return None
