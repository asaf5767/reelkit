#!/usr/bin/env python3
"""The container_overflow WARN #18 introduced, and reading check findings.

Run: python3 -m unittest discover -s tests -v

v32 on the runner reported, twice per segment:

    WARN check:layout container_overflow: Element extends outside a clipping
                                          layout container.

Triaged by reproducing it locally and reading the checker's own JSON, which
names what the WARN text does not:

    selector          #video-wrap
    containerSelector #pip-frame
    rect              1128.6 x 2006.4     (a 1.045 punch-in on a 1080x1920 frame)
    containerRect     1080 x 1920
    overflow          24.3 L / 24.3 R / 25.92 T / 60.48 B
    fixHint           "...or mark intentional overflow with
                       data-layout-allow-overflow."

Benign, and the render was right: a punch-in scales the footage past the frame
ON PURPOSE and #pip-frame crops it back. Nothing is lost that was not meant to
be cropped.

Why #18 introduced it: before the wrapper, #video-wrap hung directly off the
composition root, which the checker does not treat as a clipping container.
Confirmed by deleting the wrapper from the built HTML and re-running the check
on the same punch - 0 findings. The crop was always there; #18 made it
reportable.
"""
import json,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import reelkit,verify  # noqa: E402

ATTR=' data-layout-allow-overflow'

# The finding as the checker actually emitted it, captured from the repro.
FINDING={"code":"container_overflow","severity":"warning","time":4.655,
         "selector":"#video-wrap",
         "message":"Element extends outside a clipping layout container.",
         "rect":{"left":-24.3,"top":-25.92,"right":1104.3,"bottom":1980.48,
                 "width":1128.6,"height":2006.4},
         "containerSelector":"#pip-frame",
         "fixHint":"Resize/reposition the child or container, or mark intentional "
                   "overflow with data-layout-allow-overflow.",
         "containerRect":{"left":0,"top":0,"right":1080,"bottom":1920,
                          "width":1080,"height":1920},
         "overflow":{"left":24.3,"right":24.3,"top":25.92,"bottom":60.48},
         "firstSeen":4.655,"lastSeen":7.315,"occurrences":3}


class TheExemptionIsNarrow(unittest.TestCase):
    """Marking overflow intentional is a claim. It is only made where an
    intentional overflow is actually authored - a standing exemption would
    silence the next one here too, and that one might be real."""

    def test_the_punch_that_reported_is_marked(self):
        fr={'scale':1.0,'origin':'50% 30%',
            'punches':[{'at':4.0,'from':1.0,'to':1.045,'dur':0.28}]}
        self.assertEqual(reelkit.frame_overflow_attr(fr),ATTR)

    def test_a_reel_that_never_crops_is_not(self):
        for fr in ({},None,{'scale':1.0},{'scale':1.0,'punches':[]},
                   {'scale':1.0,'punches':[{'at':4.0,'from':1.0,'to':1.0}]}):
            self.assertEqual(reelkit.frame_overflow_attr(fr),'',
                             f'{fr} does not crop - the checker must stay live here')

    def test_a_punch_out_below_1_does_not_crop_either(self):
        self.assertEqual(reelkit.frame_overflow_attr(
            {'scale':1.0,'punches':[{'at':4.0,'from':1.0,'to':0.94}]}),'')

    def test_a_base_scale_above_1_crops_with_no_punch_at_all(self):
        self.assertEqual(reelkit.frame_overflow_attr({'scale':1.08}),ATTR)

    def test_a_punch_multiplies_the_base(self):
        """from/to are multipliers, so a punch can cross 1.0 that neither
        number does on its own."""
        self.assertEqual(reelkit.frame_overflow_attr(
            {'scale':0.98,'punches':[{'at':1.0,'from':1.0,'to':1.05}]}),ATTR)
        self.assertEqual(reelkit.frame_overflow_attr(
            {'scale':0.90,'punches':[{'at':1.0,'from':1.0,'to':1.05}]}),'')

    def test_unreadable_framing_marks_rather_than_guesses(self):
        """A plan we cannot measure gets the attribute: a spurious WARN on every
        segment trains people to ignore the checker, and the geometry gates that
        actually protect the face are elsewhere and unaffected."""
        for fr in ({'scale':'big'},{'scale':1.0,'punches':[{'to':'x'}]},
                   {'scale':1.0,'punches':'nope'}):
            self.assertEqual(reelkit.frame_overflow_attr(fr),ATTR)

    def test_the_attribute_is_the_one_the_checker_documents(self):
        self.assertIn(ATTR.strip(),FINDING['fixHint'],
                      "the escape hatch must be the checker's own, not one we invented")


class FindingsSayWhichElement(unittest.TestCase):
    """The upstream message is the RULE, not the instance: "Element extends
    outside a clipping layout container" names no element, so reading one cost a
    local re-run of the checker to get at the JSON. It is all in the finding
    already - the wrapper was throwing it away."""

    def test_the_element_and_its_container_are_named(self):
        w=verify._where(FINDING)
        self.assertIn('#video-wrap',w)
        self.assertIn('#pip-frame',w)

    def test_how_far_and_when(self):
        w=verify._where(FINDING)
        self.assertIn('B60',w); self.assertIn('L24',w)
        self.assertIn('4.66s',w)

    def test_zero_overflow_edges_are_not_listed(self):
        f=dict(FINDING,overflow={'left':0,'right':0,'top':0,'bottom':12.4})
        w=verify._where(f)
        self.assertIn('B12',w)
        for k in ('L0','R0','T0'):
            self.assertNotIn(k,w)

    def test_a_finding_with_nothing_to_add_adds_nothing(self):
        self.assertEqual(verify._where({'code':'x','message':'y'}),'')

    def test_it_never_throws_on_a_shape_it_has_not_seen(self):
        for f in ({'selector':None},{'overflow':'weird'},{'time':'soon'},
                  {'selector':'#a','overflow':{'left':None}},{}):
            verify._where(f)

    def test_the_line_a_reviewer_actually_reads(self):
        line=f"{FINDING['code']}: {FINDING['message']}{verify._where(FINDING)}"
        self.assertEqual(line,
            'container_overflow: Element extends outside a clipping layout '
            'container.  [#video-wrap in #pip-frame; over by B60/L24/R24/T26px; '
            'at 4.66s]')


if __name__=='__main__':
    unittest.main()
