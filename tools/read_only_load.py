"""Read /dev/zero over SSH, never alter target files or motor commands."""
import json
import os
import socket
import time
from pathlib import Path
import paramiko

root=Path(__file__).parent
runtime=Path(os.environ['LOCALAPPDATA'])/'T40Radar/runtime'
def require_stop():
    panel=json.loads((runtime/'panel.json').read_text(encoding='utf-8'))
    if panel.get('actual_rpm')!=0 or panel.get('motor_running') or panel.get('rpm_age',999)>2.5 or time.time()-panel.get('updated',0)>3:
        raise RuntimeError('Require fresh stopped motor telemetry')

rows=[];client=paramiko.SSHClient();sock=None;failure=None
try:
    require_stop()
    sock=socket.socket();sock.settimeout(8);sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,8192)
    sock.bind(('192.168.8.1',0));sock.connect(('192.168.8.2',107))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('192.168.8.2',107,username='root',password='root',sock=sock,timeout=8,allow_agent=False,look_for_keys=False)
    for index in range(6):
        require_stop();start=time.monotonic();count=0
        channel=client.get_transport().open_session(timeout=5,window_size=32768,max_packet_size=4096)
        channel.settimeout(5)
        try:
            channel.exec_command('dd if=/dev/zero bs=4096 count=64 2>/dev/null')
            while True:
                require_stop()
                if time.monotonic()-start>15:raise TimeoutError('Transfer deadline')
                block=channel.recv(16384)
                if not block:break
                if any(block):raise ValueError('Unexpected payload')
                count+=len(block)
            if count!=262144:raise ValueError('Incomplete transfer')
        finally:
            channel.close()
            row={'index':index,'bytes':count,'seconds':time.monotonic()-start,'time':time.time()}
            rows.append(row);print(json.dumps(row),flush=True)
        time.sleep(.5)
except Exception as exc:
    failure=repr(exc);print(failure,flush=True)
finally:
    client.close()
    if sock:sock.close()
    (root/'read-only-load-result.json').write_text(json.dumps({'rows':rows,'failure':failure},indent=2),encoding='utf-8')
