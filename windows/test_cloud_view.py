"""Geometry, stale-data and projection checks; no device I/O."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'radar_client'))
import numpy as np
from matplotlib.figure import Figure
from matplotlib import rcParams
rcParams['font.sans-serif'] = ['Microsoft YaHei', 'DejaVu Sans']
from matplotlib.backends.backend_agg import FigureCanvasAgg
from cloud_view import CloudView, display_xyz, live_layers


def snapshot():
    return dict(ground=[(2, -1, -3, 0, 0)], pcla=[(4, 3, 2, 1, 1)],
                wire=[(2, 1, 3, 0, 2)], udp_age=.1, layer_ages=dict(ground=.1,pcla=.1,wire=.1), frame_total=1)


class CloudTests(unittest.TestCase):
    def test_geometry_preserves_depth_and_removes_nonfinite(self):
        np.testing.assert_array_equal(display_xyz([(4,3,2,0,1), (np.nan,0,1,0,1)]), [[3,4,2]])
        self.assertEqual(display_xyz([]).shape, (0,3))

    def test_layer_expiry_independent_of_other_streams(self):
        state=snapshot()
        state['layer_ages']['pcla']=4
        state['layer_ages']['wire']=9
        self.assertEqual(live_layers(state)['pcla'], [])
        self.assertEqual(len(live_layers(state)['wire']),1)
        state['udp_age']=3
        self.assertTrue(all(not values for values in live_layers(state).values()))

    def test_three_projections_and_clear_after_disconnect(self):
        fig=Figure(figsize=(10,7))
        canvas=FigureCanvasAgg(fig)
        view=CloudView(fig)
        state=snapshot()
        for mode in ('3D','俯视','侧视'):
            view.set_mode(mode)
            view.update(state,force=True)
            canvas.draw()
            if mode=='3D':
                np.testing.assert_array_equal(np.array(view.scatters['pcla']._offsets3d).T, [[3,4,2]])
                view.ax.view_init(17,42)
                state['frame_total']+=1
                view.update(state)
                self.assertEqual(view.ax.azim,42)
            else:
                np.testing.assert_array_equal(view.scatters['pcla'].get_offsets(), [[4,2]] if mode=='侧视' else [[3,4]])
            view.set_color('distance')
            view.set_range(5)
            canvas.draw()
            state['udp_age']=5
            view.update(state)
            canvas.draw()
            data=view.scatters['pcla']._offsets3d[0] if mode=='3D' else view.scatters['pcla'].get_offsets()
            self.assertEqual(len(data),0)
            self.assertTrue(view.notice.get_visible())
            state['udp_age']=.1


if __name__=='__main__': unittest.main()
