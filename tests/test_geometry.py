#!/usr/bin/env python3
"""Derived card geometry and the fit resolver.

Run: python3 -m unittest discover -s tests -v

These are the pure parts of geometry.py - no browser, no footage. The measured
parts are exercised by build and verify on real projects.
"""
import sys,unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'skills/reelkit/scripts'))
import geometry as g  # noqa: E402

W=1080
def clear_at(y):
    """A head_clear_y stub: the lowest y a card may reach."""
    return lambda face: y


class ImageSlotBox(unittest.TestCase):
    """The box follows the CSS frame, not a number someone typed in a plan."""

    def test_frame_is_centred_at_its_css_width(self):
        x,y,w,h=g.image_slot_box('top',None,False,W)
        self.assertEqual(w,g.IMG_FRAME_W)
        self.assertEqual(x,(W-g.IMG_FRAME_W)//2)          # 130, not the old 70
        self.assertEqual(y,g.MODE_TOP['top'])
        self.assertEqual(h,round(w/g.IMG_ASPECT))

    def test_plate_pushes_the_slot_down(self):
        _,plain,_,_=g.image_slot_box('top',None,False,W)
        _,plated,_,_=g.image_slot_box('top',None,True,W)
        self.assertEqual(plated-plain,g.PLATE_PAD_T)

    def test_scale_narrows_and_recentres(self):
        x,_,w,h=g.image_slot_box('top',{'scale':0.5},False,W)
        self.assertEqual(w,g.IMG_FRAME_W//2)
        self.assertEqual(x,(W-w)//2)                       # still centred
        self.assertEqual(h,round(w/g.IMG_ASPECT))

    def test_explicit_top_wins_over_the_mode_default(self):
        self.assertEqual(g.image_slot_box('top',{'top':300},False,W)[1],300)
        self.assertEqual(g.image_slot_box('stage',None,False,W)[1],g.MODE_TOP['stage'])


class FitResolver(unittest.TestCase):
    def box(self,y,h): return {'x':93,'y':y,'w':894,'h':h}

    def test_card_already_clear_is_left_alone(self):
        lay,why=g.fit_layout(self.box(50,200),[1,1,1,1],{'top':50},clear_at(600))
        self.assertIsNone(lay); self.assertEqual(why,'')

    def test_overlapping_card_slides_up_without_shrinking(self):
        """Sliding costs nothing; shrinking costs readability, so slide first."""
        lay,why=g.fit_layout(self.box(120,400),[1,1,1,1],None,clear_at(500))
        self.assertEqual(why,''); self.assertEqual(lay,{'top':100})
        self.assertNotIn('scale',lay)

    def test_card_too_tall_to_slide_is_shrunk(self):
        lay,why=g.fit_layout(self.box(120,485),[1,1,1,1],None,clear_at(400))
        self.assertEqual(why,''); self.assertEqual(lay['top'],g.MIN_TOP)
        self.assertLess(lay['scale'],1); self.assertGreaterEqual(lay['scale'],g.SCALE_FLOOR)

    def test_existing_scale_compounds_rather_than_replaces(self):
        """box is measured WITH the current scale applied, so multiply."""
        lay,why=g.fit_layout(self.box(120,300),[1,1,1,1],{'scale':0.8},clear_at(292))
        self.assertEqual(why,'')
        self.assertAlmostEqual(lay['scale'],round(0.8*((292-g.MIN_TOP)/300),3))
        self.assertLess(lay['scale'],0.8)

    def test_unfittable_card_is_refused_not_squashed(self):
        """Below the readable floor this is an editorial call, not a layout one."""
        lay,why=g.fit_layout(self.box(120,485),[1,1,1,1],None,clear_at(325))
        self.assertIsNone(lay)
        self.assertIn('readable floor',why); self.assertIn("mode 'full'",why)

    def test_no_face_means_no_information_not_no_constraint(self):
        lay,why=g.fit_layout(self.box(120,900),None,None,clear_at(200))
        self.assertIsNone(lay); self.assertEqual(why,'')
        lay,why=g.fit_layout(self.box(120,900),[1,1,1,1],None,lambda f: None)
        self.assertIsNone(lay); self.assertEqual(why,'')


if __name__=='__main__': unittest.main()
