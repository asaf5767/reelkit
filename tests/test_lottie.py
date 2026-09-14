#!/usr/bin/env python3
"""Lottie badge overlays (slice 8).

Run: python3 -m unittest discover -s tests -v

Three things go wrong with Lottie specifically, and each is a gate here.

LICENCE: assets are vendored with their licence recorded, because this repo is
public and an asset nobody can account for is a legal problem. Nothing is
hotlinked - which is also the only way a render works on a kernel with no egress.

COST: a Lottie renders to SVG, and the heavy-overlay budget counts SVG like
anything else. Gradients, masks and mattes live INSIDE the JSON where the build
never sees them, so the document is inspected rather than trusted.

PLACEMENT: a badge is an overlay, so it obeys the same two boundaries as every
other overlay.
"""
import json,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import heavy,lottiefx as lf  # noqa: E402

SKILL=str(ROOT/'skills/reelkit')
W,H,CAP=1080,1920,1500


class Licensing(unittest.TestCase):
    def test_every_shipped_badge_records_a_licence(self):
        man=lf.manifest(SKILL)
        self.assertTrue(man)
        for name,meta in man.items():
            self.assertTrue(str(meta.get('license','')).strip(),f'{name} has no licence')

    def test_shipped_badges_are_cc0(self):
        for name,meta in lf.manifest(SKILL).items():
            self.assertTrue(meta['license'].startswith('CC0'),
                            f'{name} is {meta["license"]} - cannot ship in a public repo')

    def test_every_manifest_entry_has_a_file(self):
        for name in lf.manifest(SKILL):
            self.assertTrue((Path(SKILL)/'assets/lottie'/f'{name}.json').exists())

    def test_no_stray_asset_outside_the_manifest(self):
        man=lf.manifest(SKILL)
        for f in (Path(SKILL)/'assets/lottie').glob('*.json'):
            if f.name=='manifest.json': continue
            self.assertIn(f.stem,man,f'{f.name} is not in the manifest')

    def test_the_player_is_vendored_with_its_licence(self):
        v=Path(SKILL)/'assets/vendor'
        self.assertTrue((v/'lottie.min.js').exists(),'the player must be vendored, not fetched')
        self.assertTrue((v/'lottie-web.LICENSE.md').exists())
        self.assertIn('MIT',(v/'lottie-web.LICENSE.md').read_text()[:400])

    def test_an_unknown_manifest_key_is_fatal(self):
        man={'x':{'license':'CC0-1.0','sparkle':True}}
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'assets/lottie').mkdir(parents=True)
            (Path(d)/'assets/lottie/manifest.json').write_text(json.dumps(man))
            with self.assertRaises(SystemExit) as e: lf.manifest(d)
            self.assertIn('sparkle',str(e.exception))

    def test_an_unlicensed_entry_is_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'assets/lottie').mkdir(parents=True)
            (Path(d)/'assets/lottie/manifest.json').write_text(json.dumps({'x':{'author':'a'}}))
            with self.assertRaises(SystemExit) as e: lf.manifest(d)
            self.assertIn('licence',str(e.exception))


class CostIsAccounted(unittest.TestCase):
    def test_shipped_badges_carry_nothing_expensive(self):
        for name in lf.manifest(SKILL):
            doc,_=lf.load(SKILL,name)
            self.assertEqual(lf.heavy_features(doc),[],f'{name} costs heavy budget')

    def test_a_gradient_fill_is_detected_however_deep_it_sits(self):
        doc={'layers':[{'shapes':[{'it':[{'it':[{'ty':'gf'}]}]}]}]}
        self.assertIn('gradient fill',lf.heavy_features(doc))

    def test_masks_and_mattes_are_detected(self):
        self.assertIn('mask',lf.heavy_features({'layers':[{'hasMask':True}]}))
        self.assertIn('track matte',lf.heavy_features({'layers':[{'tt':1}]}))

    def test_a_heavy_asset_is_refused_at_load(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'assets/lottie'; a.mkdir(parents=True)
            (a/'manifest.json').write_text(json.dumps({'bad':{'license':'CC0-1.0'}}))
            (a/'bad.json').write_text(json.dumps(
                {'v':'5','fr':30,'op':30,'w':100,'h':100,'layers':[{'shapes':[{'ty':'gf'}]}]}))
            with self.assertRaises(SystemExit) as e: lf.load(d,'bad')
            self.assertIn('gradient fill',str(e.exception))

    def test_an_asset_referencing_external_files_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'assets/lottie'; a.mkdir(parents=True)
            (a/'manifest.json').write_text(json.dumps({'x':{'license':'CC0-1.0'}}))
            (a/'x.json').write_text(json.dumps(
                {'v':'5','fr':30,'op':30,'w':10,'h':10,'layers':[],'assets':[{'p':'img.png'}]}))
            with self.assertRaises(SystemExit) as e: lf.load(d,'x')
            self.assertIn('external assets',str(e.exception))

    def test_a_badge_adds_nothing_to_the_composition_budget(self):
        html,_=lf.markup('b1','tick-in',{},W,H)
        self.assertEqual(heavy.count(f'<html><body>{html}</body></html>')[0],0)

    def test_an_unknown_badge_is_refused_by_name(self):
        with self.assertRaises(SystemExit) as e: lf.load(SKILL,'sparkles')
        self.assertIn('sparkles',str(e.exception))


class Placement(unittest.TestCase):
    def test_a_top_corner_clear_of_both_passes(self):
        self.assertEqual(lf.problems('b',W,H,CAP,None,{}),[])

    def test_a_badge_over_the_head_blocks(self):
        p=lf.problems('b',W,H,CAP,[300,0,480,300],{})
        self.assertTrue(p); self.assertIn('touches the face',p[0][2])

    def test_a_badge_inside_the_caption_band_blocks(self):
        """An earlier version asked whether the badge CROSSED the boundary,
        which let one sitting entirely inside the band through."""
        p=lf.problems('b',W,H,CAP,None,{'corner':'bottom-right'})
        self.assertTrue(p); self.assertIn('caption band',p[0][2])

    def test_captions_off_removes_that_constraint(self):
        self.assertEqual(lf.problems('b',W,H,CAP,None,{'corner':'bottom-right'},cap_on=False),[])

    def test_an_unknown_corner_is_refused(self):
        p=lf.problems('b',W,H,CAP,None,{'corner':'middle'})
        self.assertTrue(p); self.assertIn('middle',p[0][2])

    def test_the_rect_stays_inside_the_canvas(self):
        for c in lf.CORNERS:
            x,y,w,h=lf.badge_rect(W,H,corner=c)
            self.assertGreaterEqual(x,0); self.assertGreaterEqual(y,0)
            self.assertLessEqual(x+w,W); self.assertLessEqual(y+h,H)


class Wiring(unittest.TestCase):
    def test_the_player_never_autoplays_or_loops(self):
        """HyperFrames SEEKS the player; one that plays itself renders a
        different frame than a seek to the same time."""
        _,js=lf.markup('b1','tick-in',{},W,H)
        self.assertIn('autoplay:false',js); self.assertIn('loop:false',js)

    def test_the_instance_is_registered_for_the_adapter(self):
        _,js=lf.markup('b1','tick-in',{},W,H)
        self.assertIn('__hfLottie',js)

    def test_the_asset_path_is_local(self):
        _,js=lf.markup('b1','tick-in',{},W,H)
        self.assertIn('"lottie/tick-in.json"',js)
        self.assertNotIn('http',js)

    def test_build_refuses_unknown_badge_keys(self):
        src=(ROOT/'skills/reelkit/scripts/reelkit.py').read_text()
        self.assertIn('unknown badge key(s)',src)

    def test_build_stages_the_player_rather_than_fetching_it(self):
        src=(ROOT/'skills/reelkit/scripts/reelkit.py').read_text()
        self.assertIn('vendor/lottie.min.js',src)
        self.assertIn('the player is vendored, never fetched at render time',src)


if __name__=='__main__': unittest.main()
