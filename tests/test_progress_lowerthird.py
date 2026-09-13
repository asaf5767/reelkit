#!/usr/bin/env python3
"""Progress-dim sequencing and the lower-third band (slice 7).

Run: python3 -m unittest discover -s tests -v

Progress-dim works because the timing comes from the SPEECH: a section lights
when its cue word is actually said. A section list with hand-typed timestamps
drifts the moment the cut changes, which is the failure these tests pin down.

Lower-thirds live in the narrow band between the chin and the captions. Both
neighbours move - a close framing lowers the head, a plan can raise the captions
- so the fit is measured per beat rather than assumed from a constant.
"""
import sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import cards,heavy,progress as pg,reelkit  # noqa: E402

WORDS=[{'text':'alpha','start':1.0},{'text':'beta','start':2.4},
       {'text':'gamma','start':3.9},{'text':'alpha','start':9.0}]


class CueResolution(unittest.TestCase):
    def res(self,secs,st=0.5,en=5.0,words=None):
        return pg.resolve_cues(secs,words if words is not None else WORDS,st,en)

    def test_a_section_lights_when_its_cue_is_spoken(self):
        out=self.res([{'label':'A','cue':'alpha'},{'label':'B','cue':'beta'}])
        self.assertEqual([s['at'] for s in out],[1.0,2.4])

    def test_matching_is_case_insensitive_and_substring(self):
        out=self.res([{'label':'A','cue':'ALPH'}])
        self.assertEqual(out[0]['at'],1.0)

    def test_a_cue_outside_the_beat_is_not_used_in_preference(self):
        """The same word said later in the reel is not this section's cue."""
        out=self.res([{'label':'A','cue':'alpha'}],st=0.5,en=5.0)
        self.assertEqual(out[0]['at'],1.0)

    def test_an_unspoken_cue_falls_back_rather_than_failing(self):
        out=self.res([{'label':'A','cue':'nowhere'},{'label':'B','cue':'beta'}])
        self.assertEqual(len(out),2)
        self.assertTrue(all(0.5<=s['at']<5.0 for s in out))

    def test_an_explicit_time_wins_over_a_cue(self):
        out=self.res([{'label':'A','cue':'alpha','at':4.2}])
        self.assertEqual(out[0]['at'],4.2)

    def test_sections_never_go_backwards(self):
        """A cue matched out of order would light a later section first."""
        out=self.res([{'label':'A','cue':'gamma'},{'label':'B','cue':'alpha'}])
        self.assertLessEqual(out[0]['at'],out[1]['at'])

    def test_times_stay_inside_the_beat(self):
        out=self.res([{'label':'A','at':99.0},{'label':'B','at':-5.0}],st=2.0,en=6.0)
        for s in out: self.assertTrue(2.0<=s['at']<6.0)

    def test_no_cues_at_all_spreads_evenly(self):
        out=self.res([{'label':'A'},{'label':'B'},{'label':'C'}],st=0.0,en=3.0)
        self.assertEqual([s['at'] for s in out],[0.0,1.0,2.0])

    def test_no_transcript_is_not_a_crash(self):
        out=self.res([{'label':'A','cue':'alpha'}],words=[])
        self.assertEqual(len(out),1)


class ProgressCard(unittest.TestCase):
    def build(self,data,st=0.5,en=5.0):
        br=dict(reelkit.DEFAULT_BRAND); br['_dir']='ltr'
        return cards.KINDS['progress']('p',data,br,cards.Anim(30),st,en)

    def secs(self): return [{'label':'A','at':1.0},{'label':'B','at':2.4},{'label':'C','at':3.9}]

    def test_each_section_lights_and_the_covered_ones_dim(self):
        _,g=self.build({'sections':self.secs()})
        self.assertEqual(sum('opacity:1,duration:0.26' in x for x in g),3)   # lights
        self.assertEqual(sum('opacity:0.26' in x for x in g),2)              # dims after

    def test_the_last_section_stays_lit(self):
        """Nothing follows it, so nothing dims it."""
        _,g=self.build({'sections':self.secs()})
        self.assertEqual(sum('opacity:0.26' in x for x in g),len(self.secs())-1)

    def test_every_section_starts_dim_so_a_seek_lands_right(self):
        _,g=self.build({'sections':self.secs()})
        self.assertEqual(sum(x.startswith('tl.set') and 'opacity:0.34' in x for x in g),3)

    def test_dimming_uses_no_filter(self):
        """A filter is the obvious way to grey a row out and the one that spends
        the heavy-overlay budget."""
        b,g=self.build({'sections':self.secs()})
        for x in g+[b]: self.assertNotIn('filter',x)

    def test_it_costs_nothing_from_the_heavy_budget(self):
        b,_=self.build({'title':'three moves','sections':self.secs()})
        self.assertEqual(heavy.count(f'<html><body>{b}</body></html>')[0],0)

    def test_sections_are_numbered_by_default_and_can_be_plain(self):
        self.assertIn('pgnum',self.build({'sections':self.secs()})[0])
        self.assertNotIn('pgnum',self.build({'sections':self.secs(),'numbered':False})[0])

    def test_an_empty_diagram_is_refused(self):
        with self.assertRaises(SystemExit): self.build({'sections':[]})

    def test_labels_are_escaped(self):
        b,_=self.build({'sections':[{'label':'<x>','at':1.0}]})
        self.assertIn('&lt;x&gt;',b)


class LowerThirdBand(unittest.TestCase):
    H,CAP=1920,1500

    def test_the_band_parks_above_the_caption_band(self):
        y,h=pg.band_rect(self.H,self.CAP,None)
        self.assertLessEqual(y+h,self.CAP)

    def test_a_clear_framing_fits(self):
        self.assertEqual(pg.band_problems('b',self.H,self.CAP,1200),[])

    def test_a_head_reaching_the_band_blocks(self):
        p=pg.band_problems('b',self.H,self.CAP,1350)
        self.assertTrue(p); self.assertEqual(p[0][0],'ERROR')
        self.assertIn('chin',p[0][2])

    def test_captions_raised_too_far_leave_no_room(self):
        p=pg.band_problems('b',self.H,120,None)
        self.assertTrue(p); self.assertIn('no room',p[0][2])

    def test_raising_the_captions_can_make_it_fit(self):
        """Both neighbours move, which is why this is measured per beat."""
        self.assertTrue(pg.band_problems('b',self.H,1500,1350))
        self.assertEqual(pg.band_problems('b',self.H,1620,1350),[])

    def test_no_face_detected_is_no_information_not_no_constraint(self):
        self.assertEqual(pg.band_problems('b',self.H,self.CAP,None),[])

    def test_verify_gates_lower_thirds(self):
        src=(ROOT/'skills/reelkit/scripts/verify.py').read_text()
        self.assertIn("b.get(\"kind\") != \"lowerthird\"",src)
        self.assertIn('pgmod.band_problems',src)


class LowerThirdCard(unittest.TestCase):
    def build(self,data,dirn='ltr'):
        br=dict(reelkit.DEFAULT_BRAND); br['_dir']=dirn
        return cards.KINDS['lowerthird']('l',data,br,cards.Anim(30),2.0,5.0)

    def test_name_and_role_render(self):
        b,g=self.build({'name':'Assaf','title':'building reelkit'})
        self.assertIn('ltname',b); self.assertIn('ltrole',b); self.assertEqual(len(g),2)

    def test_only_the_name_is_required(self):
        b,g=self.build({'name':'Assaf'})
        self.assertNotIn('ltrole',b); self.assertEqual(len(g),1)

    def test_a_nameless_lower_third_is_refused(self):
        with self.assertRaises(SystemExit): self.build({'title':'x'})

    def test_it_slides_in_from_the_reading_edge(self):
        self.assertIn('x:-28',self.build({'name':'A'})[1][0])
        self.assertIn('x:28',self.build({'name':'A'},dirn='rtl')[1][0])

    def test_no_plate_and_no_glow(self):
        b,_=self.build({'name':'Assaf','title':'x'})
        for banned in ('box-shadow','blur(','radial-gradient','backdrop'):
            self.assertNotIn(banned,b)

    def test_it_costs_nothing_from_the_heavy_budget(self):
        b,_=self.build({'name':'Assaf','title':'x'})
        self.assertEqual(heavy.count(f'<html><body>{b}</body></html>')[0],0)

    def test_text_is_escaped(self):
        b,_=self.build({'name':'<x>','title':'<y>'})
        self.assertIn('&lt;x&gt;',b); self.assertIn('&lt;y&gt;',b)


if __name__=='__main__': unittest.main()
