"""Separate targets, unsupported noise, degenerate geometry and stale overlays."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'radar_client'))
import numpy as np
from obstacle_outline import estimate_groups, convex_outline
from cloud_view import CloudView
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib import rcParams
rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans']

def cube(offset=(0,0,0)):
    return np.array([(x*.12,y*.12,z*.12) for x in range(3) for y in range(3) for z in range(3)])+offset

class OutlineTests(unittest.TestCase):
    def test_separate_groups_and_noise_not_merged(self):
        points=np.vstack((cube((1,2,0)),cube((4,2,1)),[[20,20,20]]))
        groups=estimate_groups(points)
        self.assertEqual(len(groups),2)
        for g in groups:self.assertEqual(len(g.points),27)
        self.assertLess(groups[0].distance,groups[1].distance)

    def test_duplicate_or_sparse_returns_cannot_form_object(self):
        self.assertEqual(estimate_groups(np.tile([[1,2,3]],(100,1))),[])
        self.assertEqual(estimate_groups([[i*2,0,0] for i in range(30)]),[])
        self.assertEqual(estimate_groups([[np.nan,1,2],[1,np.inf,2]]),[])

    def test_sparse_bridge_does_not_join_two_dense_objects(self):
        bridge=[[x,0,0] for x in np.arange(.8,3.5,.55)]
        groups=estimate_groups(np.vstack((cube(),cube((4,0,0)),bridge)),radius=.65)
        self.assertEqual(len(groups),2)

    def test_degenerate_and_planar_envelopes_stay_within_measured_bounds(self):
        self.assertEqual(len(convex_outline([[0,0],[1,0],[2,0],[0,0]])),2)
        plane=cube((1,2,3));plane[:,2]=3
        g=estimate_groups(plane)[0]
        faces,edges=g.envelope()
        coords=np.array(edges).reshape(-1,3)
        np.testing.assert_array_equal(coords[:,2],3)
        self.assertTrue(np.all(coords>=g.low) and np.all(coords<=g.high))

    def test_contours_survive_views_and_clear_on_expiry_or_toggle(self):
        fig=Figure(figsize=(10,7));canvas=FigureCanvasAgg(fig);view=CloudView(fig)
        state=dict(ground=[],wire=[],pcla=[(p[1],p[0],p[2],0,0) for p in cube((1,2,0))],
                   udp_age=.1,layer_ages={'pcla':.1},frame_total=1)
        for mode in ('3D','俯视','侧视'):
            view.set_mode(mode);view.update(state,force=True);canvas.draw()
            self.assertGreater(view.cell_count,0)
            self.assertTrue(view.outline_artists)
            state['layer_ages']['pcla']=4
            view.update(state);canvas.draw()
            self.assertEqual(view.outline_artists,[])
            state['layer_ages']['pcla']=.1
        view.outline_mode='仅点云';view.update(state,force=True)
        self.assertEqual(view.outline_artists,[])

if __name__=='__main__':unittest.main()
