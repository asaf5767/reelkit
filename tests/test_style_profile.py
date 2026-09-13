#!/usr/bin/env python3
"""Style profiles: resolution, strictness, and the things they may not touch.

Run: python3 -m unittest discover -s tests -v

A profile is the socket reference-derived defaults land in. Two properties make
it trustworthy rather than decorative: it may only carry keys the build reads
(a key nothing consumes looks configured and is not), and it may express a
preference without ever reaching the gate.
"""
import json,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import cards,style  # noqa: E402


class Resolution(unittest.TestCase):
    def test_base_is_the_floor(self):
        r,_=style.load('base')
        self.assertEqual(r['captions']['maxWords'],3,'base must be pre-profile behaviour')
        self.assertEqual((r.get('pacing') or {}).get('severity'),'off')

    def test_house_extends_base_and_states_only_deltas(self):
        raw=json.loads((ROOT/'skills/reelkit/assets/style/assaf-v1.json').read_text())
        self.assertEqual(raw['extends'],'base')
        self.assertNotIn('maxChars',raw['captions'],'restating an inherited value invites drift')

    def test_deltas_win_and_inherited_values_survive(self):
        r,_=style.load('assaf-v1')
        self.assertEqual(r['captions']['maxWords'],2)          # house delta
        self.assertEqual(r['captions']['maxChars'],15)          # inherited from base
        self.assertEqual(r['motion']['defaults']['fade']['duration'],0.40)

    def test_plan_overrides_the_profile(self):
        r,_=style.load('assaf-v1')
        br={'captionMaxWords':3,'captionMaxChars':15,'captionSize':76,
            'captionTop':1500,'captionHeight':360}
        self.assertEqual(style.captions(r,{},br)['maxWords'],2)
        self.assertEqual(style.captions(r,{'captions':{'maxWords':5}},br)['maxWords'],5)

    def test_brand_stays_nested_by_reference(self):
        """Q3: the profile names a brand preset, it does not inline 17 keys."""
        r,_=style.load('assaf-v1')
        self.assertEqual(r['brand'],'assaf')
        self.assertIsInstance(r['brand'],str)

    def test_absent_plan_style_means_the_house(self):
        _,prov=style.for_plan({})
        self.assertEqual(prov['profile'],style.DEFAULT_PROFILE)

    def test_named_plan_style_is_honoured(self):
        _,prov=style.for_plan({'style':'base'})
        self.assertEqual(prov['profile'],'base')

    def test_unknown_profile_is_refused_not_defaulted(self):
        with self.assertRaises(SystemExit) as e: style.load('no-such-style')
        self.assertIn('no-such-style',str(e.exception))


class Strictness(unittest.TestCase):
    """A profile may only carry what the build reads."""

    def bad(self,prof):
        with self.assertRaises(SystemExit) as e: style.validate(prof,'t')
        return str(e.exception)

    def test_unknown_top_level_section_is_refused(self):
        self.assertIn('transitions',self.bad({'transitions':{}}))

    def test_unknown_key_inside_a_section_is_refused(self):
        msg=self.bad({'captions':{'maxWords':2,'stroke':'black'}})
        self.assertIn('stroke',msg); self.assertIn('captions',msg)

    def test_unknown_motion_primitive_is_refused(self):
        self.assertIn('drawOn',self.bad({'motion':{'defaults':{'drawOn':{'duration':0.4}}}}))

    def test_unknown_motion_key_is_refused(self):
        self.assertIn('bounce',self.bad({'motion':{'defaults':{'pop':{'bounce':2}}}}))

    def test_absurd_duration_is_refused(self):
        self.assertIn('duration',self.bad({'motion':{'defaults':{'fade':{'duration':45}}}}))
        self.assertIn('duration',self.bad({'motion':{'defaults':{'fade':{'duration':0}}}}))

    def test_unknown_severity_is_refused(self):
        self.assertIn('severity',self.bad({'pacing':{'severity':'maybe'}}))

    def test_every_shipped_profile_validates(self):
        for f in sorted((ROOT/'skills/reelkit/assets/style').glob('*.json')):
            style.read(f.stem)       # raises on anything unknown

    def test_circular_extends_is_caught(self):
        real=style.STYLE_DIR
        with tempfile.TemporaryDirectory() as d:
            style.STYLE_DIR=d
            self.addCleanup(setattr,style,'STYLE_DIR',real)
            (Path(d)/'a.json').write_text('{"name":"a","extends":"b"}')
            (Path(d)/'b.json').write_text('{"name":"b","extends":"a"}')
            with self.assertRaises(SystemExit) as e: style.load('a')
            self.assertIn('circular',str(e.exception))


class PerKindMotion(unittest.TestCase):
    """Q1 answered per-kind: a doodle and a hero are different rows."""

    def setUp(self): self.r,_=style.load('assaf-v1')

    def test_a_kind_overrides_the_default(self):
        self.assertEqual(style.motion_for(self.r,'hero')['pop']['duration'],0.34)
        self.assertEqual(style.motion_for(self.r,'stat')['pop']['duration'],0.45)

    def test_a_kind_entry_merges_rather_than_replaces(self):
        """doodle names only fade; it must still get pop and slide."""
        m=style.motion_for(self.r,'doodle')
        self.assertEqual(m['fade']['ease'],'power1.inOut')
        self.assertIn('pop',m); self.assertIn('slide',m)

    def test_an_unlisted_kind_gets_the_defaults(self):
        self.assertEqual(style.motion_for(self.r,'chat'),
                         style.motion_for(self.r,'no-such-kind'))

    def test_anim_emits_the_resolved_duration_and_ease(self):
        a=cards.Anim(30).use(style.motion_for(self.r,'hero'))
        g=a.pop("'#x'",1.0)
        self.assertIn('duration:0.34',g); self.assertIn("back.out(2.2)",g)

    def test_an_explicit_duration_still_wins(self):
        """The hardcoded per-kind offsets are absorbed in later slices, not
        silently overridden by this one."""
        a=cards.Anim(30).use(style.motion_for(self.r,'hero'))
        self.assertIn('duration:0.9',a.pop("'#x'",1.0,0.9))

    def test_no_profile_reproduces_the_old_literals(self):
        a=cards.Anim(30)
        self.assertIn('duration:0.4',a.fade("'#x'",1))
        self.assertIn('duration:0.45',a.pop("'#x'",1))
        self.assertIn('duration:0.42',a.slide("'#x'",1))


class PacingIsEnforced(unittest.TestCase):
    """Q2 answered ENFORCED: a declared cadence that does not block declares
    nothing."""

    def plan(self,*durs):
        out,t=[],0.0
        for i,d in enumerate(durs):
            out.append({'id':f'b{i:02d}','start':t,'end':t+d}); t+=d
        return {'beats':out}

    def test_in_window_is_silent(self):
        r,_=style.load('assaf-v1')
        self.assertEqual(style.pacing_findings(r,self.plan(2.0,3.0,4.0)),[])

    def test_too_long_is_an_error_under_the_house_profile(self):
        r,_=style.load('assaf-v1')
        f=style.pacing_findings(r,self.plan(9.2))
        self.assertEqual(len(f),1); self.assertEqual(f[0][0],'ERROR')
        self.assertIn('9.2s',f[0][2])

    def test_too_short_is_caught_too(self):
        r,_=style.load('assaf-v1')
        self.assertEqual(len(style.pacing_findings(r,self.plan(0.8))),1)

    def test_base_profile_does_not_enforce(self):
        """Plans that predate the house style keep working."""
        r,_=style.load('base')
        self.assertEqual(style.pacing_findings(r,self.plan(9.2,0.4)),[])

    def test_severity_warn_does_not_block(self):
        r,_=style.load('assaf-v1'); r['pacing']=dict(r['pacing'],severity='warn')
        self.assertEqual(style.pacing_findings(r,self.plan(9.2))[0][0],'WARN')

    def test_the_shipped_reel_matches_the_house_cadence(self):
        """videos/ is gitignored, so this guards the example that ships instead:
        it is pinned to base precisely because it predates the cadence."""
        ex=json.loads((ROOT/'skills/reelkit/examples/ai-took-my-job/plan.json').read_text())
        self.assertEqual(ex.get('style'),'base',
                         'the example predates the 2-4s cadence and must say so')


class ProvenanceAndReuse(unittest.TestCase):
    def test_provenance_names_the_chain_and_digests_every_file(self):
        _,p=style.load('assaf-v1')
        self.assertEqual(p['profile'],'assaf-v1'); self.assertEqual(p['extends'],['base'])
        self.assertEqual({f['name'] for f in p['files']},{'assaf-v1','base'})
        for f in p['files']: self.assertEqual(len(f['sha256']),64)
        self.assertEqual(len(p['resolvedSha256']),64)

    def test_resolved_digest_is_stable(self):
        self.assertEqual(style.load('assaf-v1')[1]['resolvedSha256'],
                         style.load('assaf-v1')[1]['resolvedSha256'])

    def test_profiles_differ_in_digest(self):
        self.assertNotEqual(style.load('base')[1]['resolvedSha256'],
                            style.load('assaf-v1')[1]['resolvedSha256'])

    def test_segment_key_hashes_the_style_directory(self):
        """A profile edit must invalidate cached segments, exactly as a brand
        edit does - otherwise a restyled reel resumes pre-edit pixels."""
        import segmentrender as sr
        src=(ROOT/'skills/reelkit/scripts/segmentrender.py').read_text()
        self.assertIn("'assets'/'style'",src.replace('"',"'"))
        with tempfile.TemporaryDirectory() as d:
            seg=Path(d)/'seg'; (seg/'public').mkdir(parents=True)
            (seg/'plan.json').write_text('{}')
            scripts=Path(d)/'scripts'; scripts.mkdir()
            (scripts/'reelkit.py').write_text('x')
            for sub in ('brand','style'):
                (Path(d)/'assets'/sub).mkdir(parents=True)
            prof=Path(d)/'assets'/'style'/'s.json'
            prof.write_text('{"name":"s"}')
            k1=sr.segment_key(str(seg),30,str(scripts/'reelkit.py'))
            prof.write_text('{"name":"s","version":2}')
            k2=sr.segment_key(str(seg),30,str(scripts/'reelkit.py'))
            self.assertNotEqual(k1,k2,'editing a profile left the segment key unchanged')


if __name__=='__main__': unittest.main()
