import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'radar_client'))
import numpy as np
from cloud_buffer import PointHistory
from occupied_contour import occupied_cells, exposed_faces, projected_boundary
from radar_control_panel import PanelRadarClient, Telemetry
from cloud_view import CloudView
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg


class FullCloudTests(unittest.TestCase):
    def test_receive_keeps_high_low_far_points_and_counts_nonfinite(self):
        client=PanelRadarClient.__new__(PanelRadarClient);client.telemetry=Telemetry()
        entries=[dict(x_m=120,y_m=-60,z_m=z,id=0) for z in [-30,12,float('nan')]]
        with patch('radar_control_panel.parse_v2_frame',return_value=SimpleNamespace(msg_id=0x1E61,payload=b'')),patch('radar_control_panel.decode_perception_1e61_entries',return_value=(2,entries)):
            client.handle_v2_datagram(b'',('',0))
        self.assertEqual(len(client.telemetry.pcla),2)
        self.assertEqual(client.telemetry.history.received,3)
        self.assertEqual(client.telemetry.history.invalid,1)
        self.assertEqual(client.telemetry.pcla[0][2],-30)

    def test_every_received_frame_survives_slow_draws(self):
        h=PointHistory()
        for i in range(50):h.append('pcla',[(i,0,20,0,0)],100+i*.02)
        self.assertEqual(len(h.collect(101,5)['pcla']),50)
        self.assertEqual(len(h.collect(101,0)['pcla']),1)
        self.assertEqual(len(h.collect(112,5)['pcla']),0)

    def test_capacity_eviction_explicit_latest_frame_not_sampled(self):
        h=PointHistory(max_points=10)
        points=[(i,0,0,0,0) for i in range(12)]
        h.append('ground',points,100)
        self.assertEqual(len(h.collect(100,5)['ground']),10)
        self.assertEqual(h.evicted,2)
        self.assertEqual(len(h.collect(100,0)['ground']),12)

    def test_gap_does_not_blend_old_and_new_cloud(self):
        h=PointHistory();h.append('pcla',[(1,0,0,0,0)],100)
        h.append('pcla',[(2,0,0,0,0)],104)
        self.assertEqual(h.collect(104,10)['pcla'],[(2,0,0,0,0)])

    def test_voxels_keep_separate_components_and_holes(self):
        cells,step=occupied_cells([[.1,.1,.1],[3.1,.1,.1]],1)
        faces=exposed_faces(cells,step)
        self.assertEqual(len(faces),12)
        self.assertTrue(all(np.ptp(face,axis=0).max()<=1 for face in faces))
        # Eight occupied squares surrounding one empty square: preserve inner boundary.
        ring=np.array([(x,y,0) for x in range(3) for y in range(3) if (x,y)!=(1,1)])
        self.assertEqual(len(projected_boundary(ring,1)),16)

    def test_contour_adapts_resolution_without_discarding_occupied_areas(self):
        rng=np.random.default_rng(1);p=rng.uniform(-10,10,(20000,3))
        cells,step=occupied_cells(p,.15,max_cells=100)
        self.assertLessEqual(len(cells),100)
        self.assertGreater(step,.15)
        expected=set(map(tuple,np.floor(p/step).astype(np.int64)))
        self.assertEqual(set(map(tuple,cells)),expected)

    def test_all_views_fit_and_draw_every_point_no_fixed_height_limit(self):
        p=[(120,-60,-30,0,0),(-130,80,19,0,0),(2,3,4,0,0)]
        snap=dict(ground=[],wire=[],pcla=p,udp_age=.1,layer_ages={'pcla':.1},frame_total=1,latest_counts={'pcla':3})
        figure=Figure(figsize=(10,7));canvas=FigureCanvasAgg(figure);view=CloudView(figure)
        for mode in ('3D','俯视','侧视'):
            view.set_mode(mode);stats=view.update(snap,force=True);canvas.draw()
            self.assertEqual(stats['plotted'],3);self.assertEqual(stats['outside'],0)
            self.assertLess(view.zlimits[0],-30);self.assertGreater(view.zlimits[1],19)
        view.set_range(10);self.assertEqual(view.last_stats['outside'],2)
        view.fit_all();self.assertEqual(view.last_stats['plotted'],3)
        view.layers['pcla']=False;view.update(snap,force=True)
        self.assertEqual(view.last_stats['hidden'],3)
        self.assertEqual(view.outline_artists,[])

    def test_freeze_preserves_stale_snapshot_only_when_explicit(self):
        snap=dict(ground=[],wire=[],pcla=[(1,2,3,0,0)],udp_age=9,layer_ages={'pcla':9},frame_total=1)
        view=CloudView(Figure())
        self.assertEqual(view.update(snap)['plotted'],0)
        snap['frozen']=True
        self.assertEqual(view.update(snap)['plotted'],1)


if __name__=='__main__':unittest.main()
