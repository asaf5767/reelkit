#!/usr/bin/env python3
"""The planner against the gates it has to satisfy (Kaggle v30 regression).

Run: python3 -m unittest discover -s tests -v

The failure, on the real 32.5s source: the full render died in segment-001 with
two ERRORs from reelkit's own gates, on a plan reelkit's own pipeline produced.

    ERROR ai-world: beat dwells 1.3s; the assaf-v1 profile holds a layout
                    2.0-4.0s.
    ERROR ai-world: the caption band starts at y=1500 but the head reaches
                    y=1515 - captions would sit on the speaker's face.

Both gates are right. The pipeline was wrong three separate ways, and the gates
only became able to say so when verify started reading the BUILT beats instead
of the authored plan - before that the build could violate them invisibly.

  1. The mandatory hook was materialised in EVERY segment, because segmentrender
     builds each segment as its own project. So segment-001 opened with a hook
     card that belongs at 0s of the reel, and pushed its first beat behind it.
  2. A beat the hook pushes was left at whatever remained. 4.9s - 3.6s = 1.3s,
     the number in the report.
  3. The caption band came from a constant. 1500 clears a mid-shot and sits on
     the chin of a closer one.

And the planner itself drafted 5.5-9s beats under a profile that holds a layout
2-4s: every beat of a fresh draft failed the pacing gate. Measured on the
ai-took-my-job transcript, old planner: 7 of 7 beats ERROR.
"""
import json,statistics,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import reelkit,style,verify  # noqa: E402
from segmentrender import shift_plan  # noqa: E402

HOUSE,_=style.load('assaf-v1')
BASE,_=style.load('base')
WORDS=[{'text':'שלום','start':0.0,'end':0.5},{'text':'עולם','start':0.6,'end':1.2}]


def beat(bid,st,en,kind='stat'):
    return {'id':bid,'start':st,'end':en,'kind':kind,'mode':'top','data':{}}


def hooked(beats,sty=HOUSE,dur=None,offset=0.0):
    plan={'meta':{'lang':'he','fps':30,'reelOffset':offset},'hook':{'title':'כותרת'},
          'beats':[dict(b) for b in beats]}
    reelkit.ensure_mandatory_hook(tempfile.mkdtemp(),plan,WORDS,_style=sty,dur=dur)
    return plan


def dwells(plan):
    return {b['id']:round(float(b['end'])-float(b['start']),2) for b in plan['beats']}


class TheReportedFailure(unittest.TestCase):
    """The exact beat from the runner, start to finish."""

    PLAN=[beat('ai-world',0.0,4.9),beat('linkedin-video',5.0,8.0,'hero')]

    def test_the_hook_no_longer_leaves_a_runt(self):
        p=hooked(self.PLAN)
        self.assertNotIn('ai-world',dwells(p),
                         'ai-world had 1.3s left and nowhere to grow - it must be dropped, '
                         'not emitted as a beat the pacing gate rejects')
        self.assertEqual(dwells(p)['reelkit-hook'],3.6,'the hook itself is unchanged')

    def test_the_plan_that_failed_now_passes_its_own_gate(self):
        p=hooked(self.PLAN)
        p['style']='assaf-v1'
        self.assertEqual(style.pacing_findings(HOUSE,p),[])

    def test_it_really_did_fail_before(self):
        """The old behaviour, reproduced by hand, so this test fails if the
        numbers in the report stop being the numbers the code produces."""
        b=dict(self.PLAN[0]); b['start']=3.6
        bad={'beats':[b]}
        f=style.pacing_findings(HOUSE,bad)
        self.assertEqual(len(f),1)
        self.assertIn('dwells 1.3s',f[0][2])


class ReCuttingWhatTheHookShortens(unittest.TestCase):
    def test_a_beat_with_room_is_extended_to_the_minimum(self):
        p=hooked([beat('ai-world',0.0,4.9),beat('next',7.0,10.0)])
        self.assertEqual(dwells(p)['ai-world'],2.0,'extend into the gap rather than drop')
        self.assertEqual(p['beats'][1]['start'],3.6)

    def test_the_extension_never_touches_the_next_beat(self):
        for nxt in (5.0,5.5,5.61,5.64,6.0,7.0):
            p=hooked([beat('a',0.0,4.9),beat('b',nxt,nxt+3.0)])
            bs=sorted(p['beats'],key=lambda x:x['start'])
            for b in bs:
                self.assertGreater(b['end'],b['start'],f'next at {nxt}: inverted beat {b["id"]}')
            for i in range(len(bs)-1):
                self.assertLessEqual(bs[i]['end'],bs[i+1]['start'],
                                     f'next at {nxt}: beats overlap, which verify errors on')

    def test_the_extension_never_runs_past_the_media(self):
        p=hooked([beat('a',0.0,4.9)],dur=5.2)
        self.assertNotIn('a',dwells(p),'no room before the end of the clip - drop it')
        p=hooked([beat('a',0.0,4.9)],dur=9.0)
        self.assertEqual(dwells(p)['a'],2.0)

    def test_a_beat_the_hook_does_not_touch_is_untouched(self):
        p=hooked([beat('a',5.0,8.0)])
        self.assertEqual(p['beats'][1],beat('a',5.0,8.0))

    def test_pacing_off_keeps_the_old_half_second_floor(self):
        """A plan that predates the house style behaves exactly as before."""
        self.assertEqual(style.dwell_window(BASE),(None,None))
        p=hooked([beat('a',0.0,4.9),beat('b',5.0,8.0)],sty=BASE)
        self.assertEqual(dwells(p)['a'],1.3,'base enforces no window - nothing is re-cut')


class TheHookBelongsToTheReel(unittest.TestCase):
    """It was materialised once per SEGMENT, so a 32.5s reel cut into three got
    a title card at 0s, 12s and 24s - and each later segment had its first beat
    shoved behind a hook window that should not have existed."""

    def test_a_later_segment_gets_no_hook(self):
        p=hooked([beat('ai-world',0.0,4.9)],offset=12.4)
        self.assertNotIn('reelkit-hook',dwells(p))
        self.assertEqual(dwells(p)['ai-world'],4.9,'and its beat keeps its authored dwell')

    def test_the_opening_segment_still_gets_one(self):
        p=hooked([beat('a',5.0,8.0)],offset=0.0)
        self.assertIn('reelkit-hook',dwells(p))

    def test_shift_plan_tells_the_build_where_it_is(self):
        plan={'meta':{'fps':30},'beats':[beat('a',14.0,17.0)],'framing':{}}
        self.assertEqual(shift_plan(plan,12.4,24.0)['meta']['reelOffset'],12.4)
        self.assertEqual(shift_plan(plan,0.0,12.4)['meta']['reelOffset'],0.0)

    def test_the_reel_still_gets_exactly_one_hook(self):
        plan={'meta':{'fps':30},'beats':[beat('a',1.0,4.0),beat('b',14.0,17.0),
                                         beat('c',26.0,29.0)],'framing':{}}
        n=0
        for st,en in ((0.0,12.4),(12.4,24.0),(24.0,32.5)):
            sp=shift_plan(plan,st,en)
            sp['hook']={'title':'כותרת'}; sp['meta']['lang']='he'
            reelkit.ensure_mandatory_hook(tempfile.mkdtemp(),sp,WORDS,_style=HOUSE)
            n+=sum(1 for b in sp['beats'] if b['id']=='reelkit-hook')
        self.assertEqual(n,1,'one hook per reel, not one per segment')


class ThePlannerDraftsToTheProfile(unittest.TestCase):
    """A draft used to be grouped at a flat 5.5s, so under the house profile
    every beat it emitted was an ERROR before anyone looked at it."""

    def _draft(self,words):
        d=tempfile.mkdtemp()
        (Path(d)/'transcript.json').write_text(json.dumps(words),encoding='utf-8')
        reelkit.draft_plan(d,'he',None)
        return json.loads((Path(d)/'plan.draft.json').read_text(encoding='utf-8'))

    def _speech(self,n=40,step=1.1):
        return [{'text':f'w{i}.','start':round(i*step,2),'end':round(i*step+0.9,2)}
                for i in range(n)]

    def test_every_drafted_beat_sits_inside_the_window(self):
        p=self._draft(self._speech())
        sty,_=style.for_plan(p)
        lo,hi=style.dwell_window(sty)
        self.assertEqual(style.pacing_findings(sty,p),[],
                         f'draft dwells {sorted(dwells(p).values())} outside {lo}-{hi}')
        self.assertTrue(p['beats'],'a draft with no beats proves nothing')

    def test_the_draft_survives_the_hook_too(self):
        """The two halves of the fix meet here: build materialises the hook over
        the planner's first beat, and the result still has to pass."""
        p=self._draft(self._speech())
        p['meta'].setdefault('lang','he')
        reelkit.ensure_mandatory_hook(tempfile.mkdtemp(),p,self._speech(),_style=HOUSE)
        sty,_=style.for_plan(p)
        self.assertEqual(style.pacing_findings(sty,p),[])

    def test_beats_never_overlap(self):
        p=self._draft(self._speech())
        bs=sorted(p['beats'],key=lambda x:x['start'])
        for i in range(len(bs)-1):
            self.assertLessEqual(bs[i]['end'],bs[i+1]['start'],
                                 f"{bs[i]['id']} overlaps {bs[i+1]['id']}")

    def test_a_single_long_clause_is_capped_not_stretched(self):
        """One unbroken 9s run. The card ends at the window's maximum and the
        face carries the rest - the alternative is a beat the gate rejects."""
        p=self._draft([{'text':'ואז','start':0.0,'end':9.0},
                       {'text':'עצרתי.','start':9.0,'end':9.4},
                       {'text':'שתי','start':12.0,'end':12.6},
                       {'text':'שניות.','start':12.6,'end':14.2}])
        for b in p['beats']:
            self.assertLessEqual(round(b['end']-b['start'],2),4.0)


class TheCaptionBandIsMeasured(unittest.TestCase):
    """(b): captions.top came from a constant that a closer framing walks into."""

    BR={'captionTop':1500,'captionHeight':360}

    def _band(self,head_bottom,H=1920,authored=None,face_h=300.0):
        """A project with no video, so caption_band takes the authored value;
        then the same call with faces injected, to see what the measurement does."""
        d=tempfile.mkdtemp()
        pub=Path(d)/'public'; pub.mkdir()
        (pub/'input-video.mp4').write_text('not a video')
        plan={'captions':{} if authored is None else {'top':authored},
              'beats':[beat('b1',0.0,3.0)]}
        # head_rect() adds hair above and jaw below the detected box; invert it
        # so the head bottom lands exactly where the test says it does.
        from cards import HAIR_RATIO,JAW_RATIO
        y=head_bottom-face_h*(1+JAW_RATIO)
        real=reelkit.detect_faces
        reelkit.detect_faces=lambda *a,**k:{'b1':(400.0,y,240.0,face_h)}
        try:
            return reelkit.caption_band(d,plan,dict(self.BR),1080,H,plan['beats'])
        finally:
            reelkit.detect_faces=real

    def test_the_reported_collision_is_resolved(self):
        top,hgt=self._band(1515.0)
        self.assertGreater(top,1515,'the band must clear the head the gate measured')
        self.assertLessEqual(top+hgt,1920,'and must not run off the bottom of the canvas')

    def test_the_gate_that_failed_now_passes_on_the_built_value(self):
        top,hgt=self._band(1515.0)
        self.assertGreaterEqual(top,1515,
                                'verify errors on cap_top < head bottom - this is that check')

    def test_a_high_framing_leaves_the_authored_band_alone(self):
        self.assertEqual(self._band(900.0)[0],1500,'the band only ever moves down')

    def test_an_author_who_wants_captions_lower_keeps_their_value(self):
        self.assertEqual(self._band(900.0,authored=1600)[0],1600)

    def test_no_head_detected_is_not_no_head(self):
        d=tempfile.mkdtemp(); (Path(d)/'public').mkdir()
        plan={'captions':{},'beats':[beat('b1',0.0,3.0)]}
        real=reelkit.detect_faces
        reelkit.detect_faces=lambda *a,**k:{}
        try:
            self.assertEqual(reelkit.caption_band(d,plan,dict(self.BR),1080,1920,
                                                  plan['beats']),(1500,360))
        finally:
            reelkit.detect_faces=real

    def test_an_impossible_framing_stays_on_canvas_and_lets_the_gate_refuse(self):
        """No position both fits the canvas and clears the head. The band stays
        where captions are at least visible and verify says reframe the shot -
        a band pushed off the bottom would fail silently instead."""
        top,hgt=self._band(1750.0)
        self.assertEqual(top+hgt,1920)
        self.assertLess(top,1750,'so the head gate still fires, loudly')

    def test_the_gate_reads_the_band_the_build_resolved(self):
        d=tempfile.mkdtemp()
        (Path(d)/'built-beats.json').write_text(json.dumps(
            {'beats':[beat('b1',0.0,3.0)],'captions':{'top':1587,'height':360}}))
        got=verify.gated_plan(d,{'captions':{'top':1500},'beats':[]})
        self.assertEqual(got['captions']['top'],1587)


if __name__=='__main__':
    unittest.main()
