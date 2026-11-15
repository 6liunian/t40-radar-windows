import json
import os
import time
from pathlib import Path

runtime=Path(os.environ['LOCALAPPDATA'])/'T40Radar/runtime'
destination=Path(__file__).parent
started=time.time();pid=None;last_print=0;last_update=None
with (destination/'live-metrics.jsonl').open('a',encoding='utf-8',buffering=1) as output:
    while time.time()-started<180:
        try:
            state=json.loads((runtime/'status.json').read_text(encoding='utf-8'))
            panel=json.loads((runtime/'panel.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):time.sleep(.2);continue
        if 'usb_io' not in state or state.get('updated',0)<started-3:
            time.sleep(.2);continue
        if pid is None:pid=state['pid']
        if state['pid']!=pid:print('BACKEND_RESTARTED',flush=True);break
        if last_update!=state['updated']:
            row={'time':time.time(),'transport':state,'panel':{k:panel.get(k) for k in ('updated','actual_rpm','motor_running','rpm_age','fps','perception_age','sector_status')}}
            output.write(json.dumps(row,ensure_ascii=False)+'\n');last_update=state['updated']
        if time.time()-last_print>10:
            print(json.dumps({'pid':pid,'state':state['state'],'tap':state.get('tap_diagnostics'),'usb':state['usb_io'],'rx_gap_ms':state.get('rx_service_gap_max_ms')},ensure_ascii=False),flush=True)
            last_print=time.time()
        if state['state']=='error':
            (destination/'fault-metrics.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
            print('FIRST_FAILURE_CAPTURED',flush=True);break
        time.sleep(.2)
