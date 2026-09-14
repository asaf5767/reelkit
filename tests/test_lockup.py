#!/usr/bin/env python3
"""The title lockup (slice 5).

Run: python3 -m unittest discover -s tests -v

Every reference reel opens on a title, at the first frame - not after a fade-in
from black. A `fromTo` starting at opacity 0 leaves frame 0 blank, and that
blank frame IS the lead-in the treatment exists to remove, so "frame one" is a
`set` and is tested as one.
"""
import json,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import cards,heavy,reelkit,style,verify  # noqa: E402


def build(data,st=0.0,en=3.6,dirn='ltr'):
    br=dict(reelkit.DEFAULT_BRAND); br['_dir']=dirn
    return cards.KINDS['lockup']('t',data,br,cards.Anim(30),st,en)


class FrameOne(unittest.TestCase):
    def test_the_first_line_is_on_screen_at_frame_zero(self):
        _,g=build({'main':'one file is the whole reel'})
        sets=[x for x in g if x.startswith('tl.set') and 'lw0' in x]
        self.assertEqual(len(sets),1,'no frame-0 set - the reel opens blank')
        self.assertIn('opacity:1',sets[0]); self.assertIn(',0.0)',sets[0])

    def test_the_rest_of_the_line_cascades(self):
        _,g=build({'main':'a b c d'})
        self.assertEqual(sum('fromTo' in x for x in g),3)

    def test_a_lockup_that_does_not_open_the_reel_animates_in_normally(self):
        """Only the opening beat gets the frame-0 treatment; a mid-reel lockup
        has no first frame to protect."""
        _,g=build({'main':'a b'},st=8.0)
        self.assertEqual([x for x in g if x.startswith('tl.set')],[])

    def test_word_order_is_preserved(self):
        b,_=build({'main':'one two three'})
        self.assertLess(b.index('one'),b.index('two')); self.assertLess(b.index('two'),b.index('three'))

    def test_an_empty_main_line_is_refused(self):
        with self.assertRaises(SystemExit): build({'main':'   '})
        with self.assertRaises(SystemExit): build({})


class OneAccent(unittest.TestCase):
    def test_the_highlighted_word_gets_the_accent_and_the_others_do_not(self):
        b,_=build({'main':'one file whole reel','highlight':'whole'})
        self.assertEqual(b.count('lw-accent'),1)

    def test_highlight_matching_is_case_insensitive(self):
        b,_=build({'main':'One FILE','highlight':'file'})
        self.assertIn('lw-accent',b)

    def test_no_highlight_means_no_accent_span(self):
        b,_=build({'main':'one file'})
        self.assertNotIn('lw-accent',b)

    def test_the_accent_is_flat_not_a_halo(self):
        """'NO neon boxes' - the accent is a colour, never a glow."""
        b,_=build({'main':'one file','highlight':'file'})
        for banned in ('box-shadow','text-shadow','blur(','radial-gradient'):
            self.assertNotIn(banned,b)

    def test_the_lockup_costs_nothing_from_the_heavy_budget(self):
        b,_=build({'main':'one file whole reel','script':'here is how','highlight':'whole'})
        self.assertEqual(heavy.count(f'<html><body>{b}</body></html>')[0],0)


class ScriptLine(unittest.TestCase):
    def test_the_script_line_renders_and_follows_the_main_line(self):
        b,g=build({'main':'a b','script':'here is how'})
        self.assertIn('lockscript',b)
        self.assertTrue(any('lscript' in x for x in g))

    def test_no_script_line_emits_no_markup_for_one(self):
        b,_=build({'main':'a b'})
        self.assertNotIn('lockscript',b)

    def test_text_is_escaped_in_both_lines(self):
        b,_=build({'main':'<x>','script':'<y>'})
        self.assertIn('&lt;x&gt;',b); self.assertIn('&lt;y&gt;',b)

    def test_rtl_direction_reaches_the_lockup(self):
        b,_=build({'main':'שלום עולם'},dirn='rtl')
        self.assertIn('dir="rtl"',b)


class ProfileControlled(unittest.TestCase):
    def test_house_opens_with_a_lockup_and_base_keeps_the_hero(self):
        self.assertTrue(style.load('assaf-v1')[0]['title']['lockup'])
        self.assertFalse(style.load('base')[0]['title']['lockup'])

    def test_schema_carries_the_treatment_not_the_words(self):
        self.assertIn('lockup',style.SCHEMA['title'])
        self.assertNotIn('main',style.SCHEMA['title'])

    def test_the_hook_is_still_mandatory_under_both(self):
        """The lockup changes what the hook LOOKS like, never whether it exists."""
        src=(ROOT/'skills/reelkit/scripts/reelkit.py').read_text()
        self.assertIn('"id": "reelkit-hook", "start": 0.0',src)



class MixedTypeface(unittest.TestCase):
    """Heavy bold sans base line, script-italic accent word. The contrast IS the
    lockup - a script line stacked under a sans line is two headlines."""

    def test_the_accent_word_takes_the_script_face(self):
        b,_=build({'main':'one file whole reel','highlight':'whole'})
        self.assertIn('lw-accent',b)

    def test_only_the_accent_word_does(self):
        b,_=build({'main':'one file whole reel','highlight':'whole'})
        self.assertEqual(b.count('lw-accent'),1)

    def test_marker_is_the_default_treatment(self):
        b,_=build({'main':'a whole b','highlight':'whole'})
        self.assertIn('lw-marker',b); self.assertNotIn('lwring',b)

    def test_circle_draws_a_ring_around_the_accent(self):
        b,g=build({'main':'a whole b','highlight':'whole','accentStyle':'circle'})
        self.assertIn('lwring',b)
        self.assertTrue(any('strokeDashoffset' in x for x in g),'the ring does not draw on')

    def test_a_circled_number_works(self):
        """Yuval's circled-number doodle is the same treatment on a numeral."""
        b,_=build({'main':'rule 3 always','highlight':'3','accentStyle':'circle'})
        self.assertIn('lwring',b)

    def test_the_two_treatments_are_exclusive(self):
        b,_=build({'main':'a whole b','highlight':'whole','accentStyle':'circle'})
        self.assertNotIn('lw-marker',b,'a ring AND a block is two treatments')

    def test_plain_takes_the_face_and_no_treatment(self):
        b,_=build({'main':'a whole b','highlight':'whole','accentStyle':'plain'})
        self.assertIn('lw-accent',b)
        self.assertNotIn('lw-marker',b); self.assertNotIn('lwring',b)

    def test_an_unknown_accent_style_is_refused(self):
        with self.assertRaises(SystemExit) as e:
            build({'main':'a whole b','highlight':'whole','accentStyle':'neon'})
        self.assertIn('neon',str(e.exception))

    def test_the_ring_costs_nothing_from_the_heavy_budget(self):
        b,_=build({'main':'a whole b','highlight':'whole','accentStyle':'circle'})
        self.assertEqual(heavy.count(f'<html><body>{b}</body></html>')[0],0)

    def test_the_highlight_colour_comes_from_the_profile(self):
        self.assertEqual(style.load('assaf-v1')[0]['title']['highlightColor'],'#FFD84D')
        self.assertIn('highlightColor',style.SCHEMA['title'])

    def test_hebrew_accent_keeps_its_place_in_an_rtl_line(self):
        b,_=build({'main':'קובץ אחד שלם','highlight':'אחד'},dirn='rtl')
        self.assertIn('dir="rtl"',b)
        self.assertLess(b.index('קובץ'),b.index('אחד'),'word order must stay logical')


class TheHookIsGated(unittest.TestCase):
    """The mandatory hook is materialised during build and never written back to
    plan.json, while verify read plan.json - so the one card on screen at frame 0
    of every reel was never measured against the head zone. Caught while wiring
    this slice; the gate reads the built beats now."""

    # These read the sidecar through verify's own resolver rather than grepping
    # the source. The grep version passed a rewrite that changed what the gate
    # measures, which is exactly the thing it was supposed to be watching.

    def _project(self, sidecar):
        d=tempfile.mkdtemp()
        if sidecar is not None:
            (Path(d)/'built-beats.json').write_text(sidecar)
        return d

    def test_verify_prefers_the_built_beats(self):
        plan={'beats':[{'id':'authored'}],'captions':{'top':1500}}
        d=self._project(json.dumps({'beats':[{'id':'reelkit-hook'},{'id':'b01'}],
                                    'captions':{'top':1587,'height':360}}))
        got=verify.gated_plan(d,plan)
        self.assertEqual([b['id'] for b in got['beats']],['reelkit-hook','b01'],
                         'the gate must measure the beats build materialised')
        self.assertEqual(got['captions']['top'],1587,
                         'the gate must measure the band build resolved, not the authored one')
        self.assertEqual(plan['beats'],[{'id':'authored'}],'the authored plan is not mutated')

    def test_no_sidecar_leaves_the_plan_alone(self):
        plan={'beats':[{'id':'authored'}]}
        self.assertEqual(verify.gated_plan(self._project(None),plan),plan)

    def test_a_damaged_sidecar_falls_back_rather_than_crashing(self):
        plan={'beats':[{'id':'authored'}],'captions':{'top':1500}}
        for junk in ('{"beats": [','','not json at all','{"beats": []}'):
            got=verify.gated_plan(self._project(junk),plan)
            self.assertEqual([b['id'] for b in got['beats']],['authored'],
                             f'a sidecar of {junk!r} must fall back, not crash or empty the gate')


if __name__=='__main__': unittest.main()
