import sys,struct,math,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'radar_client'))
from sector_cloud import decode_sectors,SIZE,STRIDE,DEGREES_PER_ENCODER,SectorReceiver
from unittest.mock import Mock
from radar_control_panel import Telemetry
from cloud_view import CloudView
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

def make_sector(blob,index,count,distance=3,stamp=1):
    off=index*STRIDE;blob[off]=1;blob[off+1]=count
    struct.pack_into('<I',blob,off+7,stamp)
    struct.pack_into('<H',blob,off+5,round(index*268/360))
    for j in range(count):struct.pack_into('<ffffHH',blob,off+15+j*20,distance,0,0,0,20,0)

class SectorTests(unittest.TestCase):
    def test_sector_connection_requires_explicit_source_and_running_motor(self):
        telemetry=Telemetry(last_can_at=time.monotonic(),actual_rpm=900,motor_running=True)
        receiver=SectorReceiver(telemetry)
        self.assertFalse(receiver.requested())
        telemetry.cloud_source='sectors'
        self.assertTrue(receiver.requested())
        telemetry.motor_running=False
        self.assertFalse(receiver.requested())
        telemetry.motor_running=True
        for rpm in (0,5,65531):
            telemetry.actual_rpm=rpm
            self.assertFalse(receiver.requested())
        telemetry.actual_rpm=900;telemetry.last_can_at=time.monotonic()-3
        self.assertFalse(receiver.requested())

    def test_default_worker_opens_no_ssh_connection(self):
        telemetry=Telemetry(last_can_at=time.monotonic(),actual_rpm=0)
        receiver=SectorReceiver(telemetry);receiver.connect=Mock()
        receiver.start()
        time.sleep(.1)
        receiver.close()
        receiver.connect.assert_not_called()

    def test_all_125_slots_in_all_directions(self):
        blob=bytearray(SIZE)
        for index in range(360):make_sector(blob,index,125)
        points,stats,_=decode_sectors(blob)
        self.assertEqual(len(points),45000);self.assertEqual(stats['beyond_old_limit'],360*118)
        self.assertTrue(all(n>=3500 for n in stats['angular_bins']))
        self.assertAlmostEqual(points[180*125][0],3);self.assertAlmostEqual(points[90*125][1],3)

    def test_bearing_comes_from_encoder_not_record_slot(self):
        blob=bytearray(SIZE)
        make_sector(blob,94,1);make_sector(blob,68,1)
        for index in (94,68):struct.pack_into('<H',blob,index*STRIDE+5,50)
        points,_,_=decode_sectors(blob)
        self.assertEqual(points[0][:3],points[1][:3])
        angle=math.radians(180-50*DEGREES_PER_ENCODER)
        self.assertAlmostEqual(points[0][0],3*math.cos(angle))

    def test_unchanged_snapshot_is_not_new_points(self):
        blob=bytearray(SIZE);make_sector(blob,15,10)
        _,_,last=decode_sectors(blob)
        points,stats,_=decode_sectors(blob,last)
        self.assertEqual(points,[]);self.assertEqual(stats['changed_sectors'],0)
        make_sector(blob,15,10,stamp=2)
        points,stats,_=decode_sectors(blob,last)
        self.assertEqual(len(points),10);self.assertEqual(stats['changed_sectors'],1)

    def test_invalid_range_rejected_far_range_retained(self):
        blob=bytearray(SIZE)
        for index,distance in enumerate([float('nan'),float('inf'),0,-1,200]):make_sector(blob,index,1,distance)
        points,stats,_=decode_sectors(blob)
        self.assertEqual(stats['invalid'],4);self.assertEqual(len(points),1)
        self.assertAlmostEqual(math.hypot(*points[0][:2]),200)

    def test_bad_layout_rejected(self):
        for invalid in [b'',bytes(SIZE-1),bytes([1,126])+bytes(SIZE-2),bytes([3,0])+bytes(SIZE-2)]:
            with self.assertRaises(ValueError):decode_sectors(invalid)

    def test_source_switch_and_stopped_data_not_live(self):
        t=Telemetry();now=time.monotonic()
        t.history.append('pcla',[(1,2,3,1,0)],now);t.pcla=t.history.latest['pcla'];t.last_udp_at=now;t.layer_updated['pcla']=now
        t.sector_history.append('pcla',[(4,5,0,1,90)],now);t.sector_at=now;t.sector_frames=1
        self.assertEqual(t.snapshot()['pcla'][0][:3],(1,2,3))
        t.cloud_source='sectors';self.assertIsNone(t.snapshot()['udp_age'])
        t.actual_rpm=650;t.last_can_at=now
        self.assertEqual(t.snapshot()['pcla'][0][:3],(4,5,0));self.assertLess(t.snapshot()['udp_age'],1)
        fig=Figure();view=CloudView(fig);view.set_mode('俯视');view.update(t.snapshot())
        self.assertEqual(view.last_stats['plotted'],1)
        self.assertIn('待校准',view.info.get_text())
        t.actual_rpm=0;view.update(t.snapshot())
        self.assertEqual(view.last_stats['plotted'],0)
