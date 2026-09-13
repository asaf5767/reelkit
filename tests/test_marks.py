#!/usr/bin/env python3
"""The hand-drawn mark family (slice 3).

Run: python3 -m unittest discover -s tests -v

`doodle` was an escape hatch - paste inline SVG, list the tweens by element id -
so every annotation was a one-off and nothing looked like the same hand twice.
The family replaces that as the default way to annotate; the escape hatch stays,
because it is what covers anything the family does not.

Two properties matter beyond "it draws something": every mark points AT the
artifact by construction (no mark takes a free position, so none can point at
nothing), and the geometry is derived from the beat id rather than sampled, so
build stays a pure function of the plan.
"""
import sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import cards,marks,style  # noqa: E402


class Geometry(unittest.TestCase):
    def test_every_named_mark_builds(self):
        for n in marks.NAMES:
            path,length=marks.mark_svg('m',n,'seed')
            self.assertIn('<path',path); self.assertGreater(length,0)

    def test_unknown_mark_is_refused_not_substituted(self):
        with self.assertRaises(ValueError) as e: marks.mark_svg('m','squiggle','s')
        self.assertIn('squiggle',str(e.exception))

    def test_marks_are_deterministic_from_the_beat_id(self):
        """build is a pure function of the plan; a sampled wobble would break
        byte-identical rebuilds and every cached segment with them."""
        self.assertEqual(marks.mark_svg('m','circle-scribble','b01'),
                         marks.mark_svg('m','circle-scribble','b01'))

    def test_different_beats_get_different_hands(self):
        self.assertNotEqual(marks.mark_svg('m','circle-scribble','b01')[0],
                            marks.mark_svg('m','circle-scribble','b02')[0])

    def test_dash_length_covers_the_path(self):
        """The dasharray must be at least the path length or the stroke is
        partly visible before its draw-on starts."""
        for n in marks.NAMES:
            path,length=marks.mark_svg('m',n,'s')
            self.assertIn(f'stroke-dasharray="{length}"',path)
            self.assertIn(f'stroke-dashoffset="{length}"',path)

    def test_every_mark_stays_inside_the_card(self):
        for n in marks.NAMES:
            pts=marks.BUILDERS[n]('s',{})
            for x,y in pts:
                self.assertTrue(-marks.VIEW*0.02<=x<=marks.VIEW*1.02,f'{n} x={x} escapes')
                self.assertTrue(-marks.VIEW*0.02<=y<=marks.VIEW*1.02,f'{n} y={y} escapes')

    def test_the_ring_encloses_the_middle(self):
        """'always pointing AT the artifact' is geometry, not a convention."""
        pts=marks.circle_scribble('s')
        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        self.assertLess(min(xs),marks.VIEW/2); self.assertGreater(max(xs),marks.VIEW/2)
        self.assertLess(min(ys),marks.VIEW/2); self.assertGreater(max(ys),marks.VIEW/2)

    def test_the_arrow_starts_at_its_edge_and_ends_inward(self):
        import math
        mid=marks.VIEW/2
        for edge in marks.EDGES:
            pts=marks.curved_arrow('s',edge)
            start,tip=pts[0],pts[18]           # pts[18] is the curve's end, before the barbs
            self.assertGreater(math.dist(start,(mid,mid)),math.dist(tip,(mid,mid)),
                               f'{edge} arrow does not travel inward')

    def test_unknown_arrow_edge_is_refused(self):
        with self.assertRaises(ValueError): marks.curved_arrow('s','diagonal')

    def test_no_mark_spends_the_heavy_overlay_budget(self):
        """Plain strokes only - the family is supposed to be free."""
        import heavy
        for n in marks.NAMES:
            path,_=marks.mark_svg('m',n,'s')
            self.assertEqual(heavy.count(f'<html><body>{path}</body></html>')[0],0,
                             f'{n} costs heavy-overlay budget')


class InTheCard(unittest.TestCase):
    def build(self,data):
        import reelkit
        br=dict(reelkit.DEFAULT_BRAND); br['_dir']='ltr'
        return cards.KINDS['doodle']('b01',data,br,cards.Anim(30),0.6,3.8)

    def test_named_marks_render_and_draw_on(self):
        body,g=self.build({'marks':[{'mark':'circle-scribble'},{'mark':'sparkle'}]})
        self.assertIn('b01-mk0',body); self.assertIn('b01-mk1',body)
        self.assertEqual(sum('strokeDashoffset' in x for x in g),2)

    def test_a_beat_may_name_marks_and_author_nothing(self):
        """`svg` used to be required, so the family could not have been used
        without pasting an SVG beside it."""
        body,_=self.build({'marks':[{'mark':'underline'}]})
        self.assertIn('dmarks',body)

    def test_the_escape_hatch_still_works(self):
        body,g=self.build({'svg':'<circle id="c1" r="5"/>',
                           'anims':[{'id':'c1','anim':'pop','at':0.2}]})
        self.assertIn('<circle id="c1"',body); self.assertEqual(len(g),1)

    def test_marks_and_authored_svg_coexist(self):
        body,_=self.build({'svg':'<circle id="c1" r="5"/>','marks':[{'mark':'sparkle'}]})
        self.assertIn('<circle id="c1"',body); self.assertIn('b01-mk0',body)

    def test_no_marks_emits_no_mark_layer(self):
        body,_=self.build({'svg':'<circle id="c1" r="5"/>'})
        self.assertNotIn('dmarks',body)

    def test_draw_duration_is_the_profile_default(self):
        _,g=self.build({'marks':[{'mark':'underline'}]})
        self.assertIn('duration:0.4',g[0])

    def test_a_mark_may_override_its_own_timing(self):
        _,g=self.build({'marks':[{'mark':'underline','at':1.0,'dur':0.9}]})
        self.assertIn('duration:0.9',g[0]); self.assertIn('1.6',g[0])


class MarkBudget(unittest.TestCase):
    """One or two marks a moment; a third reads as clutter."""

    def plan(self,n):
        return {'beats':[{'id':'b01','data':{'marks':[{'mark':'sparkle'}]*n}}]}

    def test_two_is_fine(self):
        r,_=style.load('assaf-v1')
        self.assertEqual(style.doodle_findings(r,self.plan(2)),[])

    def test_three_is_an_error_under_the_house_profile(self):
        r,_=style.load('assaf-v1')
        f=style.doodle_findings(r,self.plan(3))
        self.assertEqual(len(f),1); self.assertEqual(f[0][0],'ERROR')

    def test_base_does_not_enforce(self):
        r,_=style.load('base')
        self.assertEqual(style.doodle_findings(r,self.plan(9)),[])

    def test_schema_carries_the_budget_not_the_choice_of_mark(self):
        """Which mark and where it points is the plan's business."""
        self.assertIn('maxMarks',style.SCHEMA['doodle'])
        self.assertNotIn('marks',style.SCHEMA['doodle'])


if __name__=='__main__': unittest.main()
