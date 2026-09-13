#!/usr/bin/env python3
"""Segment boundaries and resume safety.

Run: python3 -m unittest discover -s tests -v

Both cases here shipped: boundaries computed in the wrong unit, and a resume
check that kept a file it should have rejected. Neither is visible without
rendering, so they get tests instead.
"""
import subprocess,sys,tempfile,unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'skills/reelkit/scripts'))
import segmentrender as sr  # noqa: E402

PLAN={'meta':{'fps':30},'beats':[{'end':3.8},{'end':7.8},{'end':11.6}]}


class Boundaries(unittest.TestCase):
    """Everything in boundaries() is seconds. It used to mix in frames."""

    def check(self,dur,target):
        b=sr.boundaries(PLAN,dur,target)
        self.assertEqual(b[0],0)
        self.assertLessEqual(b[-1],dur+0.05,'boundary runs past the end of the media')
        self.assertTrue(all(b[i]<b[i+1] for i in range(len(b)-1)),'not monotonic')
        return b

    def test_short_clip_is_not_shredded(self):
        """12s at a 5s target is 3 segments. The unit bug made it 34."""
        self.assertEqual(len(self.check(12.0,5))-1,3)

    def test_target_longer_than_clip_is_one_segment(self):
        self.assertEqual(len(self.check(12.0,12))-1,1)

    def test_real_reel_lengths(self):
        self.assertEqual(len(self.check(47.43,12))-1,4)
        self.assertEqual(len(self.check(90.0,12))-1,8)

    def test_boundaries_prefer_beat_ends(self):
        """A boundary mid-overlay would cut a card in half."""
        b=self.check(12.0,5)
        ends={x['end'] for x in PLAN['beats']}
        for x in b[1:-1]: self.assertIn(x,ends)

    def test_boundaries_land_on_the_shared_frame_grid(self):
        """Integral frame counts at 10fps and 30fps, so joins cannot drift."""
        for x in self.check(47.43,12):
            self.assertAlmostEqual(x*10,round(x*10),places=6)


class ResumeSafety(unittest.TestCase):
    """valid_video decides whether rendered work can be reused."""

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); d=Path(cls.tmp.name)
        cls.good=d/'good.mp4'
        subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc=size=640x480:rate=10:duration=2',
                        '-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(cls.good)],check=True)
        cls.trunc=d/'trunc.mp4'
        cls.trunc.write_bytes(cls.good.read_bytes()[:11000])  # over the size floor, still broken
        cls.tiny=d/'tiny.mp4'; cls.tiny.write_bytes(b'x'*100)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_complete_segment_is_reusable(self):
        self.assertTrue(sr.valid_video(self.good,20))

    def test_wrong_frame_count_is_rejected(self):
        """A 10fps preview segment must never satisfy a 30fps full segment."""
        self.assertFalse(sr.valid_video(self.good,60))

    def test_truncated_segment_is_rejected(self):
        """It keeps its moov and still advertises the full frame count."""
        self.assertFalse(sr.valid_video(self.trunc,20))

    def test_no_expectation_can_only_check_decodability(self):
        """Which is why every caller passes an expected frame count."""
        self.assertTrue(sr.valid_video(self.good))
        self.assertFalse(sr.valid_video(self.tiny))

    def test_stub_file_is_rejected(self):
        self.assertFalse(sr.valid_video(self.tiny)); self.assertFalse(sr.valid_video(Path('/nope.mp4')))


if __name__=='__main__': unittest.main()
