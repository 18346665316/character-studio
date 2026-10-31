"""Temporal sampling quality uses screen motion, duration and short peaks."""
import math
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from motion_sampling import analyze


def probe(duration=2,amplitude=.01,frequency=1,weapon=False):
    times=np.linspace(0,duration,math.ceil(duration*120)+1)
    positions=np.zeros((len(times),4+int(weapon),3))
    positions[:,:4,0]=(amplitude*np.sin(times*frequency*2*math.pi))[:,None]
    positions[:,1,1]=.05;positions[:,2,2]=.05;positions[:,3,1]=1
    if weapon:positions[:,-1,0]=.4*np.sin(times*3*2*math.pi)
    return {'times':times.tolist(),'positions':positions.tolist(),'duration':duration,'probe_hz':120,'bone_names':['body'],'weapon_marker_count':int(weapon)}


class MotionSamplingTests(unittest.TestCase):
    def test_slow_motion_prefers_lower_rate_and_keeps_duration(self):
        p=probe(duration=9.9333334)
        r=analyze(p,64,2,'front')
        self.assertEqual(r['recommended']['target_fps'],12)
        self.assertEqual(r['recommended']['frame_count'],120)
        self.assertEqual(r['reference_frame_count'],298)
        self.assertEqual(r['duration_seconds'],p['duration'])

    def test_long_animation_is_not_limited_to_120_frames(self):
        r=analyze(probe(duration=20),64,2,'front')
        self.assertEqual(r['recommended']['frame_count'],240)
        self.assertEqual(r['reference_frame_count'],600)

    def test_weapon_peaks_are_not_averaged_into_idle_torso(self):
        slow=analyze(probe(),64,2,'front')
        armed=analyze(probe(weapon=True),64,2,'front')
        self.assertGreater(armed['recommended']['target_fps'],slow['recommended']['target_fps'])
        self.assertEqual(armed['candidates'][0]['peak_marker'],'weapon_bounds')
        self.assertGreater(armed['candidates'][0]['peak_extra_pixels'],2.5)

    def test_larger_sprite_cannot_get_less_sampling(self):
        p=probe(amplitude=.14,frequency=2)
        small=analyze(p,64,2,'front');large=analyze(p,128,2,'front')
        self.assertGreaterEqual(large['recommended']['target_fps'],small['recommended']['target_fps'])
        self.assertEqual(large['candidates'][-1]['peak_extra_pixels'],0)

    def test_brief_extreme_is_checked_in_addition_to_p95(self):
        p=probe(amplitude=0)
        for i,t in enumerate(p['times']):
            p['positions'][i][0][0]=max(0,1-abs(t-.358)/.012)*.8
        r=analyze(p,128,2,'front')
        first=r['candidates'][0]
        self.assertLess(first['p95_extra_pixels'],.75)
        self.assertGreater(first['peak_extra_pixels'],2.5)
        self.assertFalse(first['passes'])

    def test_seam_warning_does_not_change_sample_density(self):
        p=probe(amplitude=0)
        for i,t in enumerate(p['times']):
            for marker in p['positions'][i]:marker[0]=t*.06
        r=analyze(p,128,2,'front')
        self.assertTrue(r['loop_requires_review'])
        self.assertGreater(r['loop_endpoint_max_pixels'],2.5)

    def test_hidden_weapon_markers_are_masked_but_bones_must_exist(self):
        p=probe(weapon=True)
        for frame in p['positions']:frame[-1]=None
        r=analyze(p,64,2,'front')
        self.assertEqual(r['recommended']['target_fps'],12)
        p['positions'][0][0]=None
        with self.assertRaises(ValueError):analyze(p,64,2,'front')

    def test_raster_comparison_ignores_transparent_rgb(self):
        from sampling_compare import raster_error
        from PIL import Image
        a=Image.new('RGBA',(4,4),(0,0,0,0));a.putpixel((1,1),(200,30,40,255))
        b=Image.new('RGBA',(4,4),(250,250,250,0));b.putpixel((1,1),(200,30,40,255))
        self.assertEqual(raster_error(a,b),(0,0))
        b.putpixel((1,1),(0,0,0,0));b.putpixel((2,1),(200,30,40,255))
        self.assertEqual(raster_error(a,b)[0],1)
        with self.assertRaises(ValueError):raster_error(Image.new('RGBA',(4,4)),Image.new('RGBA',(4,4)))

    def test_missing_probe_or_invalid_projection_fails(self):
        p=probe();p['times'][-1]=p['times'][-2]
        with self.assertRaises(ValueError):analyze(p,64,2)
        for size,camera in ((32,2),(64,float('nan')),(64,0)):
            with self.assertRaises(ValueError):analyze(probe(),size,camera)
        p=probe();p['positions'][0][0][0]=float('inf')
        with self.assertRaises(ValueError):analyze(p,64,2)


if __name__=='__main__':unittest.main()
