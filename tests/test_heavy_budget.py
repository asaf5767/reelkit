#!/usr/bin/env python3
"""The heavy-overlay budget: the ceiling that stops a black render.

Run: python3 -m unittest discover -s tests -v

Past roughly 40 elements carrying `filter: blur`, `radial-gradient` or an
animated `clip-path`, the capture layer returns solid black for the first half
of the render and recovers near the end. Nothing errors, nothing warns; the file
is simply half black. That is why it is a gate and not a comment.

The count mirrors HyperFrames' own `composition_heavy_overlay_count_high` rule
so the two cannot disagree about what "heavy" means - verified against the CLI
itself: a composition with 30 injected heavy elements is reported as 30 by both.
The difference is severity, deliberately: upstream warns, reelkit refuses.
"""
import sys,unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'skills/reelkit/scripts'))
import heavy  # noqa: E402


def doc(body, css=''):
    return f'<html><head><style>{css}</style></head><body>{body}</body></html>'


class WhatCounts(unittest.TestCase):
    def test_inline_blur_counts(self):
        self.assertEqual(heavy.count(doc('<div style="filter:blur(4px)"></div>'))[0],1)

    def test_inline_radial_gradient_counts(self):
        self.assertEqual(heavy.count(
            doc('<div style="background:radial-gradient(circle,#000,#fff)"></div>'))[0],1)

    def test_inline_clip_path_counts(self):
        self.assertEqual(heavy.count(doc('<div style="clip-path:inset(10px)"></div>'))[0],1)

    def test_clip_path_none_is_not_heavy(self):
        """`clip-path:none` is how you turn one OFF; counting it would punish the fix."""
        self.assertEqual(heavy.count(doc('<div style="clip-path:none"></div>'))[0],0)

    def test_css_class_hook_counts_every_element_wearing_it(self):
        body=''.join('<div class="glow"></div>' for _ in range(5))
        self.assertEqual(heavy.count(doc(body,'.glow{filter:blur(6px)}'))[0],5)

    def test_css_id_hook_counts(self):
        self.assertEqual(heavy.count(doc('<div id="halo"></div>','#halo{filter:blur(2px)}'))[0],1)

    def test_plain_filter_without_blur_is_not_heavy(self):
        self.assertEqual(heavy.count(doc('<div style="filter:brightness(1.2)"></div>'))[0],0)

    def test_linear_gradient_is_not_heavy(self):
        """Only radial is implicated; a flat linear gradient is free."""
        self.assertEqual(heavy.count(
            doc('<div style="background:linear-gradient(#000,#fff)"></div>'))[0],0)

    def test_display_none_is_the_only_escape(self):
        """Presence is what costs: a hidden overlay still feeds the compositor.
        Only removal from the render tree helps."""
        self.assertEqual(heavy.count(doc('<div style="filter:blur(4px);display:none"></div>'))[0],0)
        self.assertEqual(heavy.count(doc('<div style="filter:blur(4px);opacity:0"></div>'))[0],1)
        self.assertEqual(heavy.count(doc('<div style="filter:blur(4px);visibility:hidden"></div>'))[0],1)

    def test_exempt_tags_do_not_count(self):
        self.assertEqual(heavy.count(doc('<video class="g"></video><script class="g"></script>',
                                         '.g{filter:blur(2px)}'))[0],0)

    def test_commented_out_css_does_not_hook(self):
        self.assertEqual(heavy.count(doc('<div class="g"></div>',
                                         '/* .g{filter:blur(2px)} */'))[0],0)

    def test_at_rule_headers_are_skipped(self):
        self.assertEqual(heavy.count(doc('<div class="g"></div>','@media screen{}'))[0],0)

    def test_descendant_selector_hooks_on_its_leftmost_compound(self):
        """Mirrors upstream and over-counts on purpose: for a budget whose
        failure mode is a black render, counting high is the safe direction."""
        self.assertEqual(heavy.count(doc('<div class="wrap"></div>','.wrap .inner{filter:blur(2px)}'))[0],1)

    def test_an_element_is_counted_once_however_many_ways_it_is_heavy(self):
        n,_=heavy.count(doc('<div class="g" style="filter:blur(1px)"></div>','.g{filter:blur(2px)}'))
        self.assertEqual(n,1)


class Thresholds(unittest.TestCase):
    def blurs(self,n): return doc(''.join('<div class="g"></div>' for _ in range(n)),'.g{filter:blur(4px)}')

    def test_below_the_warn_threshold_is_silent(self):
        n,f=heavy.findings(self.blurs(heavy.WARN_AT-1))
        self.assertEqual(n,heavy.WARN_AT-1); self.assertEqual(f,[])

    def test_warn_band_warns_but_does_not_block(self):
        """Lead time, not a cliff: upstream's own threshold sits below the repro."""
        _,f=heavy.findings(self.blurs(heavy.WARN_AT))
        self.assertEqual([x[0] for x in f],['WARN'])

    def test_at_the_ceiling_it_is_an_error(self):
        _,f=heavy.findings(self.blurs(heavy.MAX))
        self.assertEqual([x[0] for x in f],['ERROR'])

    def test_over_the_ceiling_is_an_error(self):
        n,f=heavy.findings(self.blurs(heavy.MAX+20))
        self.assertEqual(n,heavy.MAX+20); self.assertEqual(f[0][0],'ERROR')

    def test_thresholds_keep_their_sourced_order(self):
        """25 is HyperFrames' own warn threshold; 40 is the observed black
        render. Neither is a taste value, so neither may be quietly swapped."""
        self.assertEqual(heavy.WARN_AT,25)
        self.assertEqual(heavy.MAX,40)
        self.assertLess(heavy.WARN_AT,heavy.MAX)

    def test_the_error_names_the_offenders(self):
        _,f=heavy.findings(self.blurs(heavy.MAX))
        self.assertIn('.g',f[0][2])
        self.assertIn(str(heavy.MAX),f[0][2])


class GateWiring(unittest.TestCase):
    def test_heavy_error_blocks_the_render_gate(self):
        import reelkit
        v={'cardGeometry':True,'faceDetection':True,'compositionCheck':True,
           'findings':[{'level':'ERROR','id':'composition','message':'45 heavy overlay elements'}]}
        self.assertTrue(reelkit.gate_problems(v))

    def test_missing_composition_check_blocks(self):
        """A gate that could not run blocks delivery - the same rule Playwright
        and OpenCV already live under."""
        import reelkit
        v={'cardGeometry':True,'faceDetection':True,'compositionCheck':False,'findings':[]}
        p=reelkit.gate_problems(v)
        self.assertTrue(p); self.assertIn('npx hyperframes check',p[0])

    def test_worker_and_reelkit_share_one_capability_list(self):
        """These were two hardcoded tuples; adding a capability to one left the
        other accepting a gate that had not run."""
        import reelkit,worker
        self.assertIs(worker.GATE_DEPS,reelkit.GATE_DEPS)


if __name__=='__main__': unittest.main()
