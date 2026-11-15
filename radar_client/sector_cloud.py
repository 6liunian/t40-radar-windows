"""Read-only, full-sector snapshots from the radar's existing process memory.

No firmware patch, uploaded executable, or motor command. Bearings use the
repository's provisional encoder convention; display is polar slant range,
not a calibrated XYZ reconstruction. Every record's 125 available slots
can be decoded, unlike the legacy 7-slot UDP exporter.
"""
import math
import socket
import struct
import threading
import time

BASE=0xC140DD8
STRIDE=2515
SECTORS=360
DEGREES_PER_ENCODER=360.0/268.0  # existing radar_streamer.c's 1.3433 deg/unit
SIZE=STRIDE*SECTORS


def decode_sectors(raw, previous=None):
    if len(raw)!=SIZE:raise ValueError('扇区快照长度错误')
    points=[];invalid=0;counts=[];signatures=[];fresh=0;truncated_old=0
    histogram=[0]*12;encoder_fields=[]
    for index in range(SECTORS):
        sector=raw[index*STRIDE:(index+1)*STRIDE]
        active,count=sector[:2]
        if active not in (0,1) or count>125:raise ValueError('扇区布局与此固件不匹配')
        signature=sector[:15]+sector[15:15+count*20]
        signatures.append(signature)
        changed=previous is None or signature!=previous[index]
        if changed:fresh+=1
        counts.append(count if active else 0)
        encoder=struct.unpack_from('<H',sector,5)[0]&1023
        encoder_fields.append(encoder)
        if not active or not changed:continue
        bearing=(180-encoder*DEGREES_PER_ENCODER)%360
        angle=math.radians(bearing)
        for j in range(count):
            distance=struct.unpack_from('<f',sector,15+j*20)[0]
            strength=struct.unpack_from('<H',sector,31+j*20)[0]
            if not math.isfinite(distance) or distance<=0:
                invalid+=1;continue
            points.append((distance*math.cos(angle),distance*math.sin(angle),0.,strength,index))
            histogram[int(bearing//30)]+=1
            if j>=7:truncated_old+=1
    return points,dict(points=len(points),invalid=invalid,sectors_with_returns=sum(n>0 for n in counts),
                       changed_sectors=fresh,reported_points=sum(counts),beyond_old_limit=truncated_old,
                       angular_bins=histogram,counts=counts,encoder_min=min(encoder_fields),encoder_max=max(encoder_fields),
                       degrees_per_encoder=DEGREES_PER_ENCODER),signatures


class SectorReceiver:
    def __init__(self,telemetry,host='192.168.8.2',local='192.168.8.1'):
        self.telemetry=telemetry;self.host=host;self.local=local
        self.stop=threading.Event();self.connection=None;self.channel=None
        self.thread=threading.Thread(target=self.run,name='sector-reader',daemon=True)

    def start(self):self.thread.start()

    def message(self,text):
        with self.telemetry.lock:self.telemetry.sector_status=text

    def requested(self):
        with self.telemetry.lock:
            return (self.telemetry.cloud_source=='sectors' and self.telemetry.motor_running
                    and 150 <= self.telemetry.actual_rpm <= 3600
                    and 0 <= time.monotonic()-self.telemetry.last_can_at < 2.5)

    def close(self):
        self.stop.set()
        if self.channel:
            try:self.channel.close()
            except Exception:pass
        if self.connection:
            try:self.connection.close()
            except Exception:pass
        self.thread.join(timeout=1)

    def connect(self):
        import paramiko
        sock=socket.socket();sock.settimeout(5)
        # Keep a full snapshot, but bound TCP bursts into the USB WLAN RX pipe.
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,8192)
        sock.bind((self.local,0))
        client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.connection=client
        try:
            sock.connect((self.host,107))
            client.connect(self.host,port=107,username='root',password='root',sock=sock,
                           timeout=5,banner_timeout=5,auth_timeout=5,look_for_keys=False,allow_agent=False)
            _,out,err=client.exec_command('pidof app.elf',timeout=5)
            pid=int(out.read().split()[0])
            return client,pid
        except Exception:
            sock.close();client.close();raise

    def read_snapshot(self,client,pid):
        # BusyBox dd uses lseek on /proc/PID/mem; gzip cuts >90% unused slots.
        block=4096;offset=BASE%block;count=(offset+SIZE+block-1)//block
        command=f'dd if=/proc/{pid}/mem bs={block} skip={BASE//block} count={count} 2>/dev/null | gzip -1'
        channel=client.get_transport().open_session(timeout=5,window_size=32768,max_packet_size=4096);self.channel=channel
        channel.settimeout(5);channel.exec_command(command)
        try:
            compressed=bytearray()
            deadline=time.monotonic()+8
            while True:
                if time.monotonic()>deadline:raise TimeoutError('扇区快照超过 8 秒，重新连接')
                part=channel.recv(32768)
                if not part:break
                compressed.extend(part)
                if len(compressed)>SIZE+65536:raise ValueError('扇区数据长度异常')
            import zlib
            decoder=zlib.decompressobj(31)
            full=decoder.decompress(compressed,count*block+1)
            if len(full)!=count*block or not decoder.eof:raise ValueError('扇区读取不完整')
            return full[offset:offset+SIZE]
        finally:channel.close();self.channel=None

    def run(self):
        while not self.stop.is_set():
            if not self.requested():
                self.message('完整扇区按需读取：选择扇区数据源并启动旋转后连接')
                if self.stop.wait(.5):break
                continue
            try:
                self.message('正在连接扇区读取通道…')
                client,pid=self.connect();previous=None
                with self.telemetry.lock:self.telemetry.sector_history.clear()
                while not self.stop.is_set():
                    if not self.requested():break
                    started=time.monotonic();raw=self.read_snapshot(client,pid)
                    points,stats,signatures=decode_sectors(raw,previous)
                    first=previous is None;previous=signatures
                    now=time.monotonic()
                    stats['read_seconds']=now-started
                    with self.telemetry.lock:
                        self.telemetry.sector_stats=stats
                        if first:
                            self.telemetry.sector_status='正在确认扇区更新，首张快照不作为实时点云'
                        elif stats['changed_sectors']:
                            self.telemetry.sector_history.append('pcla',points,now)
                            self.telemetry.sector_at=now;self.telemetry.sector_frames+=1
                            self.telemetry.sector_status=f"记录更新 {stats['changed_sectors']}/360；有回波 {stats['sectors_with_returns']}/360"
                        else:self.telemetry.sector_status='扇区记录未更新，等待新的扫描数据'
                    if self.stop.wait(max(.1,1.0-(time.monotonic()-started))):break
            except Exception as exc:
                if not self.stop.is_set():self.message('扇区连接待恢复：'+str(exc))
            finally:
                if self.connection:
                    try:self.connection.close()
                    except Exception:pass
                    self.connection=None
            if self.stop.wait(4):break
