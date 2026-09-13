#!/usr/bin/env python3
"""Caption emphasis, keyword detonation, emoji - and the four rules they must
not break.

Run: python3 -m unittest discover -s tests -v

The rules come from a review of what a template tool got wrong on real footage:
it put a sticker over the speaker's face, reversed and clipped the RTL captions,
and put a glowing box around everything. Those are review failures here, so they
are enforced by construction rather than by convention.
"""
import json,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import captionfx as cfx, heavy, style  # noqa: E402


class Emphasis(unittest.TestCase):
    def rules(self,*rs): return cfx.normalise(list(rs))

    def test_a_plain_word_gets_no_treatment_class(self):
        self.assertNotIn('cw-',cfx.word_span('w0','hello',None))

    def test_highlight_and_serif_are_type_not_containers(self):
        r=self.rules({'word':'free','style':'highlight'})
        self.assertIn('cw-highlight',cfx.word_span('w0','free',cfx.rule_for('free',r)))
        r=self.rules({'word':'free','style':'serif'})
        self.assertIn('cw-serif',cfx.word_span('w0','free',cfx.rule_for('free',r)))

    def test_matching_is_case_and_space_insensitive(self):
        r=self.rules({'word':'  Free ','style':'highlight'})
        self.assertIsNotNone(cfx.rule_for('free',r))
        self.assertIsNotNone(cfx.rule_for('FREE',r))

    def test_unknown_style_is_refused_not_ignored(self):
        with self.assertRaises(SystemExit) as e: self.rules({'word':'x','style':'glow'})
        self.assertIn('glow',str(e.exception))

    def test_a_rule_with_no_word_is_dropped_not_applied_to_everything(self):
        self.assertEqual(self.rules({'style':'highlight'}),{})

    def test_word_text_is_escaped(self):
        self.assertIn('&lt;script&gt;',cfx.word_span('w0','<script>',None))


class EmojiIsPartOfTheLine(unittest.TestCase):
    """Emoji belong to the caption line, not to a separate pop layer."""

    def test_emoji_rides_inside_its_word_span(self):
        """Appended to the LINE it would strand itself at whichever edge the
        paragraph direction chose - which is the RTL bug this avoids."""
        r=cfx.normalise([{'word':'חינם','style':'highlight','emoji':'⚡'}])
        span=cfx.word_span('w0','חינם',cfx.rule_for('חינם',r))
        self.assertLess(span.index('חינם'),span.index('⚡'),'emoji escaped its word')
        self.assertIn('cemo',span)
        self.assertEqual(span.count('<span'),2)   # the word and its emoji, nothing else

    def test_no_emoji_means_no_emoji_markup(self):
        r=cfx.normalise([{'word':'x','style':'highlight'}])
        self.assertNotIn('cemo',cfx.word_span('w0','x',cfx.rule_for('x',r)))

    def test_emoji_is_escaped_like_any_other_text(self):
        r=cfx.normalise([{'word':'x','emoji':'<b>'}])
        self.assertIn('&lt;b&gt;',cfx.word_span('w0','x',cfx.rule_for('x',r)))


class DetonationCannotOverflowOrClip(unittest.TestCase):
    """'NO reversed or clipped RTL captions' - enforced by geometry."""

    def svg(self,text='אוטומטית',emoji=''):
        return cfx.detonation_svg('d0',text,emoji,1080,360,'#fff','#05060A',9,'Heebo')

    def test_text_is_fitted_to_an_exact_width(self):
        s=self.svg()
        self.assertIn('lengthAdjust="spacingAndGlyphs"',s)
        self.assertIn('textLength="993"',s)      # 92% of 1080, so it cannot reach the edge

    def test_a_very_long_keyword_still_fits(self):
        """textLength condenses the glyphs instead of running off the canvas -
        no measurement, no clipping, either direction."""
        s=self.svg('מילה'*12)
        self.assertIn('textLength="993"',s)

    def test_it_is_centred_not_anchored_to_an_edge(self):
        self.assertIn('text-anchor="middle"',self.svg())

    def test_the_keyword_is_escaped(self):
        self.assertIn('&amp;',self.svg('a&b'))

    def test_emoji_rides_with_the_detonated_word(self):
        self.assertIn('⚡',self.svg('חינם','⚡'))


class NoGlowingBoxes(unittest.TestCase):
    """'NO neon boxes around every element' - emphasis is type, weight and one
    accent. Nothing here may spend the heavy-overlay budget."""

    def test_no_treatment_emits_a_shadow_blur_or_gradient(self):
        r=cfx.normalise([{'word':'x','style':'highlight','emoji':'⚡'}])
        html=(cfx.word_span('w0','x',cfx.rule_for('x',r))
              + cfx.detonation_svg('d','x','⚡',1080,360,'#fff','#000',9,'Heebo')
              + f'<style>{cfx.stroke_css({"strokeWidth":9})}</style>')
        for banned in ('blur(','radial-gradient','box-shadow','filter:','text-shadow'):
            self.assertNotIn(banned,html,f'caption treatment emits {banned}')

    def test_treatments_cost_nothing_from_the_heavy_budget(self):
        html=('<html><body>'
              + cfx.detonation_svg('d','x','',1080,360,'#fff','#000',9,'Heebo')
              + '</body></html>')
        self.assertEqual(heavy.count(html)[0],0)

    def test_the_stroke_keeps_the_letterform_intact(self):
        """paint-order puts the stroke behind the fill; without it a heavy
        stroke eats the glyph from the inside."""
        self.assertIn('paint-order:stroke fill',cfx.stroke_css({'strokeWidth':9}))

    def test_no_stroke_configured_emits_no_css(self):
        self.assertEqual(cfx.stroke_css({}),'')
        self.assertEqual(cfx.stroke_css({'strokeWidth':0}),'')


class SparseByConstruction(unittest.TestCase):
    def caps(self,*words):
        return [{'id':'c0','words':[{'text':w} for w in words]}]

    def test_within_the_cap_is_silent(self):
        r=cfx.normalise([{'word':'a','style':'detonate'}])
        self.assertEqual(cfx.detonation_findings(self.caps('a','b'),r,3),[])

    def test_past_the_cap_is_a_finding(self):
        r=cfx.normalise([{'word':'a','style':'detonate'},{'word':'b','style':'detonate'}])
        f=cfx.detonation_findings(self.caps('a','b'),r,1)
        self.assertEqual(len(f),1); self.assertEqual(f[0][0],'ERROR')

    def test_house_profile_sets_a_cap_and_base_does_not(self):
        self.assertEqual(style.load('assaf-v1')[0]['captions']['maxDetonations'],3)
        self.assertIsNone(style.load('base')[0]['captions'].get('maxDetonations'))

    def test_schema_carries_the_look_not_the_words(self):
        """Which word detonates is the plan's business."""
        self.assertIn('maxDetonations',style.SCHEMA['captions'])
        self.assertNotIn('emphasis',style.SCHEMA['captions'])


class NothingTouchesTheFace(unittest.TestCase):
    """The absolute rule. A detonated keyword fills the caption band, so a band
    that overlaps the head is a review failure, not a preference - which is why
    this check is unconditional rather than profile-gated."""

    def test_verify_refuses_a_band_that_reaches_the_head(self):
        src=(ROOT/'skills/reelkit/scripts/verify.py').read_text()
        self.assertIn('captions would sit on the speaker',src)
        i=src.index('captions would sit on the speaker')
        self.assertIn('ERROR',src[max(0,i-400):i],'the face rule must block, not warn')

    def test_the_rule_is_not_reachable_from_a_profile(self):
        for sec in style.SCHEMA.values():
            self.assertNotIn('faceZone',sec); self.assertNotIn('headMargin',sec)


if __name__=='__main__': unittest.main()
