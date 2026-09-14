#!/usr/bin/env python3
"""PiP as a finished mode: the artifact fills the frame (v33 regression).

Run: python3 -m unittest discover -s tests -v

v33 converted the linkedin-video beat to mode 'pip' and verify refused it:

    ERROR linkedin-video card covers 13.3% of the speaker's head - it reaches
                        y=670 and the head starts at y=558; it needs to end
                        above y=486, or the beat wants B-roll (mode 'full')

The gate was measuring the head where the SOURCE footage puts it - full frame -
and a pip beat's entire point is that the head is not there: it has insetted to
a corner and the artifact has the frame. So the artifact was being held above a
line that is free at render time, which made pip plus any artifact very nearly
impossible.

pip.py already said what the mode is - "the speaker shrinks to a corner while
the artifact fills" - and only the first half had been built. The head insetted;
nothing ever filled. The card was still laid out as a small over-the-footage
card and gated as one, and broll.src was required by the gate and read by
nothing, which is the declared-but-unread key doctrine calls fatal.

What this fixes, in one sentence each:

  * The artifact owns the frame, exactly as `full` does, and renders UNDER the
    inset - so the face-zone law holds by construction (the face is on top)
    rather than by keeping the artifact away from where the head used to be.
  * The head zone during a pip beat is the head mapped through the inset
    transform, used by every gate that asks where the face is.
  * broll.src is read - it is the full-frame ground - and is therefore optional
    rather than mandatory. A still is allowed here and banned in `full` because
    the speaker stays on screen, which is the editorial case for pip.
  * What replaces the face check is a CONTENT check: an artifact hidden behind
    the inset is one nobody can read.
"""
import sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import pip as pipmod, reelkit  # noqa: E402
from cards import head_rect  # noqa: E402

W,H=1080,1920
# The head from the v33 report: full-frame, starting at y=558 and reaching 670+.
V33_FACE=(360.0,600.0,300.0,300.0)


class TheHeadIsNotWhereTheFootagePutsIt(unittest.TestCase):
    def test_the_inset_transform_is_applied_exactly(self):
        """Not "the head zone is the whole inset" - the head occupies PART of
        the inset, and rounding it up to the whole thing would forbid layouts
        that are actually clear."""
        x,y,w,h=pipmod.inset_rect(W,H,0.30,'top-right')
        hr=head_rect(V33_FACE)
        zx,zy,zw,zh=pipmod.head_zone(hr,W,H,{'corner':'top-right','scale':0.30})
        self.assertAlmostEqual(zx,x+hr[0]*0.30,places=3)
        self.assertAlmostEqual(zy,y+hr[1]*0.30,places=3)
        self.assertAlmostEqual(zw,hr[2]*0.30,places=3)
        self.assertAlmostEqual(zh,hr[3]*0.30,places=3)
        self.assertLess(zw*zh,w*h,'the head is part of the inset, not all of it')

    def test_the_head_lands_inside_the_inset(self):
        ix,iy,iw,ih=pipmod.inset_rect(W,H,0.30,'top-right')
        zx,zy,zw,zh=pipmod.head_zone(head_rect(V33_FACE),W,H,{'corner':'top-right'})
        self.assertGreaterEqual(zx,ix); self.assertGreaterEqual(zy,iy)
        self.assertLessEqual(zx+zw,ix+iw); self.assertLessEqual(zy+zh,iy+ih)

    def test_the_v33_region_is_free_during_the_beat(self):
        """The card that was refused reached y=670. Mapped through the inset the
        head no longer goes anywhere near it."""
        _zx,zy,_zw,zh=pipmod.head_zone(head_rect(V33_FACE),W,H,{'corner':'top-right'})
        self.assertLess(zy+zh,670,
                        'the head must be clear of the region the v33 card wanted')

    def test_every_corner_maps_inside_its_own_inset(self):
        for corner in pipmod.CORNERS:
            ix,iy,iw,ih=pipmod.inset_rect(W,H,0.30,corner)
            zx,zy,zw,zh=pipmod.head_zone(head_rect(V33_FACE),W,H,{'corner':corner})
            self.assertTrue(ix<=zx and zx+zw<=ix+iw and iy<=zy and zy+zh<=iy+ih,corner)

    def test_no_head_is_still_no_information(self):
        self.assertIsNone(pipmod.head_zone(None,W,H,{}))


class TheArtifactMustBeReadable(unittest.TestCase):
    """What replaces the face check. The artifact is UNDER the inset, so this is
    never a face-zone finding - the face cannot be covered. It is a content
    finding: an artifact behind the speaker is an artifact nobody can read."""

    def full_bleed(self):
        return {'x':0.0,'y':0.0,'w':float(W),'h':float(H)}

    def test_a_full_bleed_artifact_is_clean(self):
        """The inset always hides scale^2 of the frame - 9% at the default - and
        on a full-bleed artifact that is inherent to picture-in-picture, not a
        defect. The threshold has to sit clear of it or every pip beat warns."""
        o=pipmod.occlusion(self.full_bleed(),W,H,{'corner':'top-right'})
        self.assertAlmostEqual(o,9.0,delta=0.6)
        self.assertLess(o,pipmod.OCCLUSION_WARN)
        self.assertEqual(pipmod.artifact_findings('b1',self.full_bleed(),W,H,{}),[])

    def test_an_artifact_in_the_same_corner_is_refused(self):
        box={'x':700.0,'y':40.0,'w':340.0,'h':520.0}
        f=pipmod.artifact_findings('b1',box,W,H,{'corner':'top-right'})
        self.assertEqual([l for l,_i,_m in f],['ERROR'])
        self.assertIn('behind the speaker',f[0][2])
        self.assertIn('top-right',f[0][2],'the message must name the corner to move')

    def test_the_opposite_corner_clears_it(self):
        box={'x':700.0,'y':40.0,'w':340.0,'h':520.0}
        self.assertEqual(pipmod.artifact_findings('b1',box,W,H,{'corner':'top-left'}),[])

    def test_the_thresholds_bracket_the_inherent_figure(self):
        self.assertLess(9.0,pipmod.OCCLUSION_WARN)
        self.assertLess(pipmod.OCCLUSION_WARN,pipmod.OCCLUSION_MAX)

    def test_an_unmeasurable_artifact_reports_nothing_rather_than_zero(self):
        self.assertIsNone(pipmod.occlusion(None,W,H,{}))
        self.assertEqual(pipmod.artifact_findings('b1',None,W,H,{}),[])


class TheArtifactOwnsTheFrame(unittest.TestCase):
    """The layout half. Before this a pip card was laid out as a small
    over-the-footage card - top-aligned, inset from the top edge - which is why
    it collided with a head zone it had no business being measured against."""

    def css(self,mode):
        return reelkit.card_css('b1',mode,dict(reelkit.DEFAULT_BRAND,_dir='ltr'))

    def test_pip_centres_like_full_rather_than_hugging_the_top(self):
        self.assertIn('align-items:center',self.css('pip'))
        self.assertIn('align-items:flex-start',self.css('top'))

    def test_pip_takes_the_whole_frame(self):
        self.assertIn('padding:0px 0 0 0',self.css('pip'))
        self.assertNotIn('padding:0px 0 0 0',self.css('top'))


class TheLayerOrderIsTheMechanism(unittest.TestCase):
    """The face-zone law holds for pip because the face is painted ON TOP of the
    artifact, not because the artifact is kept away from the head. That is three
    z-indexes, and if they ever inverted the mode would silently start covering
    the speaker while every geometric gate still passed."""

    def layers(self):
        css=reelkit.theme_css(dict(reelkit.DEFAULT_BRAND,_dir='ltr'))
        out={}
        for name,sel in (('artifact','.card-host.pip-art'),('inset','#pip-frame'),
                         ('veil','.bottomveil'),('cards','.card-host')):
            block=css.split(sel+'{',1)[1].split('}',1)[0]
            out[name]=int(block.split('z-index:')[1].split(';')[0])
        return out

    def test_the_artifact_is_under_the_speaker_and_the_speaker_under_the_cards(self):
        z=self.layers()
        self.assertLess(z['artifact'],z['inset'],
                        'the artifact must render UNDER the inset - this is the face-zone law')
        self.assertLess(z['inset'],z['cards'],
                        'captions and cards stay above the footage')

    def test_the_veil_still_sits_over_the_footage(self):
        z=self.layers()
        self.assertLess(z['inset'],z['veil'])
        self.assertLess(z['veil'],z['cards'])


class BrollIsReadNow(unittest.TestCase):
    OK={'id':'b1','mode':'pip','kind':'image',
        'justification':'B-roll shows the LinkedIn post being described'}

    def msgs(self,b):
        return [m for _l,_i,m in pipmod.problems(b,W,H,1560)]

    def test_a_pip_beat_needs_no_broll(self):
        """It was required and read nowhere. Now it is the ground, so a beat
        whose own card is the artifact does not need one."""
        self.assertEqual(pipmod.problems(self.OK,W,H,1560),[])

    def test_the_justification_is_what_stayed_mandatory(self):
        b={k:v for k,v in self.OK.items() if k!='justification'}
        self.assertTrue(any('justification' in m for m in self.msgs(b)))

    def test_a_ground_does_not_excuse_a_missing_justification(self):
        b=dict(self.OK,broll={'src':'linkedin.png'})
        b.pop('justification')
        self.assertTrue(any('justification' in m for m in self.msgs(b)))

    def test_the_inset_still_may_not_sit_in_the_caption_band(self):
        b=dict(self.OK,pip={'corner':'bottom-right'})
        self.assertTrue(any('behind the words' in m for m in self.msgs(b)))


if __name__=='__main__':
    unittest.main()
