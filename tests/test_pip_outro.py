#!/usr/bin/env python3
"""PiP head inset and the branded outro (slice 6).

Run: python3 -m unittest discover -s tests -v

The doctrine matters more than the geometry: face full frame is the default and
PiP is the justified exception. A pip beat that cannot say what its B-roll shows
fails the build, in the same spirit as a profile key nothing reads - a cut nobody
can justify is decoration, and decoration is what the rule exists to keep out.
"""
import json,subprocess,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import cards,heavy,pip as pipmod,reelkit  # noqa: E402

W,H,CAP=1080,1920,1500
OK={'id':'b1','mode':'pip','broll':{'src':'a.mp4'},
    'justification':'B-roll shows the grill being named'}


class Geometry(unittest.TestCase):
    def test_the_inset_sits_inside_the_canvas(self):
        x,y,w,h=pipmod.inset_rect(W,H)
        self.assertGreaterEqual(x,0); self.assertGreaterEqual(y,0)
        self.assertLessEqual(x+w,W); self.assertLessEqual(y+h,H)

    def test_every_corner_resolves(self):
        for c in pipmod.CORNERS:
            x,y,w,h=pipmod.inset_rect(W,H,corner=c)
            self.assertTrue(w>0 and h>0)

    def test_an_unknown_corner_is_refused(self):
        with self.assertRaises(SystemExit): pipmod.inset_rect(W,H,corner='middle')

    def test_an_unreadable_or_pointless_scale_is_refused(self):
        with self.assertRaises(SystemExit): pipmod.inset_rect(W,H,scale=0.05)
        with self.assertRaises(SystemExit): pipmod.inset_rect(W,H,scale=0.9)

    def test_the_default_corner_clears_the_caption_band(self):
        """The caption band owns the bottom; an inset sharing it puts the face
        behind the words."""
        self.assertTrue(pipmod.clears_captions(W,H,CAP))
        self.assertEqual(pipmod.DEFAULT_CORNER[:3],'top')

    def test_a_bottom_corner_does_not(self):
        self.assertFalse(pipmod.clears_captions(W,H,CAP,corner='bottom-right'))


class JustificationIsMandatory(unittest.TestCase):
    def msgs(self,beat): return [m for _l,_i,m in pipmod.problems(beat,W,H,CAP)]

    def test_a_justified_beat_passes(self):
        self.assertEqual(pipmod.problems(OK,W,H,CAP),[])

    def test_a_missing_justification_blocks(self):
        b=dict(OK); b.pop('justification')
        self.assertTrue(any('justification' in m for m in self.msgs(b)))

    def test_a_placeholder_justification_blocks(self):
        b=dict(OK,justification='todo')
        self.assertTrue(any('placeholder' in m for m in self.msgs(b)))

    def test_a_pip_beat_without_broll_is_allowed_now(self):
        """broll.src used to be required here and read nowhere - the gate
        demanded a key the renderer ignored, which is the declared-but-unread
        key doctrine calls fatal. It is the full-frame ground now, so a beat
        whose own card IS the artifact does not need one. The justification is
        what stayed mandatory, because that is the doctrine."""
        b=dict(OK); b.pop('broll')
        self.assertEqual(pipmod.problems(b,W,H,CAP),[])
        b2=dict(b); b2.pop('justification')
        self.assertTrue(any('justification' in m for m in self.msgs(b2)))

    def test_an_inset_over_the_caption_band_blocks(self):
        b=dict(OK,pip={'corner':'bottom-right'})
        self.assertTrue(any('behind the words' in m for m in self.msgs(b)))

    def test_justification_may_live_on_the_pip_object(self):
        b={'id':'b1','mode':'pip','broll':{'src':'a.mp4'},
           'pip':{'justification':'B-roll shows the editor running the test'}}
        self.assertEqual(pipmod.problems(b,W,H,CAP),[])

    def test_the_build_refuses_an_unjustified_pip_beat(self):
        """End to end, not just the helper: the error has to reach the build."""
        src=(ROOT/'skills/reelkit/scripts/reelkit.py').read_text()
        self.assertIn('pipmod.problems(b, W, H',src)
        i=src.index('pipmod.problems(b, W, H')
        self.assertIn('die(',src[i:i+400],'the gate must stop the build, not warn')


class Tweens(unittest.TestCase):
    def tw(self,**kw):
        return pipmod.tweens('b1',W,H,4.0,8.0,cards.Anim(30),pip=kw or None)

    def test_it_shrinks_then_returns(self):
        t=self.tw(); self.assertEqual(len(t),2)
        self.assertIn('scale:0.3',t[0]); self.assertIn('scale:1',t[1])

    def test_both_directions_are_fromto_so_a_seek_lands_right(self):
        for x in self.tw(): self.assertIn('fromTo',x)

    def test_the_inset_is_a_rounded_rect(self):
        self.assertIn(f'borderRadius:{pipmod.RADIUS}',self.tw()[0])

    def test_it_targets_the_pip_wrapper_not_the_framing_element(self):
        """Framing scale lives on #video-wrap; the two must compose rather than
        overwrite each other."""
        self.assertIn('#pip-frame',self.tw()[0])
        self.assertNotIn('#video-wrap',self.tw()[0])


class Outro(unittest.TestCase):
    def build(self,data):
        br=dict(reelkit.DEFAULT_BRAND); br['_dir']='ltr'
        return cards.KINDS['outro']('o',data,br,cards.Anim(30),30.0,33.0)

    def test_the_full_end_card_renders(self):
        b,g=self.build({'product':'reelkit','type':'open source',
                        'url':'github.com/x/y','cta':'Try it'})
        for cls in ('oname','otype','opill','octa'): self.assertIn(cls,b)
        self.assertEqual(len(g),4)

    def test_only_the_product_is_required(self):
        b,g=self.build({'product':'reelkit'})
        self.assertIn('oname',b); self.assertNotIn('opill',b); self.assertEqual(len(g),1)

    def test_a_nameless_outro_is_refused(self):
        with self.assertRaises(SystemExit): self.build({'cta':'Try it'})

    def test_text_is_escaped(self):
        b,_=self.build({'product':'<x>','cta':'<y>'})
        self.assertIn('&lt;x&gt;',b); self.assertIn('&lt;y&gt;',b)

    def test_the_end_card_costs_nothing_from_the_heavy_budget(self):
        b,_=self.build({'product':'reelkit','url':'x.com','cta':'go'})
        self.assertEqual(heavy.count(f'<html><body>{b}</body></html>')[0],0)

    def test_the_gradient_is_linear_not_radial(self):
        """radial-gradient is in the pattern that turns a render black; linear
        is not. The end card is the one gradient in the system."""
        css=(ROOT/'skills/reelkit/scripts/reelkit.py').read_text()
        block=css[css.index('.outro{{'):css.index('.outro .octa')]
        self.assertIn('linear-gradient',block); self.assertNotIn('radial-gradient',block)


class LibraryDocs(unittest.TestCase):
    """Convention only - but the convention has to say the load-bearing part."""

    def setUp(self): self.doc=(ROOT/'docs/asset-library.md').read_text()

    def test_it_names_the_location_and_the_manifest(self):
        self.assertIn('assets/broll/',self.doc)
        self.assertIn('manifest.json',self.doc)

    def test_it_states_the_no_clip_no_cut_rule(self):
        self.assertIn('No clip, no cut',self.doc)

    def test_it_flags_that_the_segment_key_must_hash_the_manifest(self):
        """The same catch as assets/style/: swapping a clip changes pixels."""
        self.assertIn('segment_key()',self.doc)


if __name__=='__main__': unittest.main()
