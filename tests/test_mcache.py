#!/usr/bin/env python3
"""The measurement cache, and the rules that stop it weakening the gate.

Run: python3 -m unittest discover -s tests -v

Why it exists: `build` measures the cards and the head, `verify` measures them
again seconds later, and render_gate runs verify before EVERY render - so a
segmented render paid ~6.1s per segment re-measuring identical cards and
re-scanning identical footage. Warm, that pass is now ~0.13s.

What is tested here is not the speed but the safety. A cache in front of a
fail-closed gate is only acceptable while three things hold: a changed input
misses, a missing measurement is never cached as an answer, and a hit can never
substitute for the measuring dependency itself.
"""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'skills/reelkit/scripts'))
import mcache  # noqa: E402


class Keys(unittest.TestCase):
    def test_same_inputs_same_key(self):
        self.assertEqual(mcache.sha('a','b'),mcache.sha('a','b'))

    def test_any_changed_part_changes_the_key(self):
        base=mcache.sha('card-html',1080,1920)
        self.assertNotEqual(base,mcache.sha('card-html!',1080,1920))
        self.assertNotEqual(base,mcache.sha('card-html',1081,1920))
        self.assertNotEqual(base,mcache.sha('card-html',1080,1921))

    def test_fields_cannot_impersonate_each_other(self):
        """Length-prefixed, so ('ab','c') and ('a','bc') are different keys.
        Unprefixed concatenation would make a card ending in a digit collide
        with the canvas width that follows it."""
        self.assertNotEqual(mcache.sha('ab','c'),mcache.sha('a','bc'))

    def test_file_id_tracks_content_not_name(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a.mp4'; b=Path(d)/'b.mp4'
            a.write_bytes(b'same'); b.write_bytes(b'same')
            self.assertEqual(mcache.file_id(a),mcache.file_id(b))
            b.write_bytes(b'recut')
            self.assertNotEqual(mcache.file_id(a),mcache.file_id(b))

    def test_missing_file_ids_as_absent_not_as_some_other_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(mcache.file_id(Path(d)/'gone.mp4'),'')


class Roundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.p=self.tmp.name; self.addCleanup(self.tmp.cleanup)

    def test_store_then_read_back(self):
        mcache.replace(self.p,'cards','scope1',{'k1':{'x':1,'y':2}})
        self.assertEqual(mcache.get(mcache.load(self.p),'cards','scope1','k1'),{'x':1,'y':2})

    def test_absent_cache_is_a_miss_not_an_error(self):
        self.assertIsNone(mcache.get(mcache.load(self.p),'cards','scope1','k1'))

    def test_unknown_key_in_a_known_scope_is_a_miss(self):
        mcache.replace(self.p,'cards','scope1',{'k1':{'x':1}})
        self.assertIsNone(mcache.get(mcache.load(self.p),'cards','scope1','other'))

    def test_a_different_scope_is_never_consulted(self):
        """Restyled cards or re-cut footage: the old section is not merged with,
        so a measurement from before the change cannot be served."""
        mcache.replace(self.p,'cards','scope1',{'k1':{'x':1}})
        self.assertIsNone(mcache.get(mcache.load(self.p),'cards','scope2','k1'))

    def test_writing_a_new_scope_drops_the_old_entries(self):
        mcache.replace(self.p,'cards','scope1',{'k1':{'x':1}})
        mcache.replace(self.p,'cards','scope2',{'k2':{'x':2}})
        c=mcache.load(self.p)
        self.assertEqual(list(c['cards']['entries']),['k2'],'stale scope kept entries')

    def test_partial_writers_in_one_scope_do_not_erase_each_other(self):
        """build measures the split beats and the over-footage beats in separate
        passes; verify measures all of them. All three write the same section."""
        mcache.replace(self.p,'faces','v1',{'b01':[1,2,3,4]})
        mcache.replace(self.p,'faces','v1',{'b02':[5,6,7,8]})
        c=mcache.load(self.p)
        self.assertEqual(mcache.get(c,'faces','v1','b01'),[1,2,3,4])
        self.assertEqual(mcache.get(c,'faces','v1','b02'),[5,6,7,8])

    def test_sections_are_independent(self):
        mcache.replace(self.p,'cards','cs',{'k':{'x':1}})
        mcache.replace(self.p,'faces','fs',{'k':[1,2,3,4]})
        c=mcache.load(self.p)
        self.assertIsNotNone(mcache.get(c,'cards','cs','k'))
        self.assertIsNotNone(mcache.get(c,'faces','fs','k'))


class NeverWeakensTheGate(unittest.TestCase):
    """A cache in front of a fail-closed gate has to fail closed too."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.p=self.tmp.name; self.addCleanup(self.tmp.cleanup)

    def test_empty_measurements_are_not_stored(self):
        """A card that measured nothing and a beat with no detected face are
        re-measured every pass. The cache can only ever hand back a box to
        AVOID - it can never delete a head a card has to clear."""
        mcache.replace(self.p,'cards','s',{'measured':{'x':1},'nothing':None,'empty':{}})
        c=mcache.load(self.p)
        self.assertIsNotNone(mcache.get(c,'cards','s','measured'))
        self.assertIsNone(mcache.get(c,'cards','s','nothing'))
        self.assertIsNone(mcache.get(c,'cards','s','empty'))

    def test_corrupt_cache_is_no_cache(self):
        Path(mcache.path(self.p)).write_text('{not json')
        self.assertEqual(mcache.load(self.p),{})

    def test_cache_from_another_version_is_discarded(self):
        Path(mcache.path(self.p)).write_text(json.dumps(
            {'version':mcache.VERSION+1,'cards':{'scope':'s','entries':{'k':{'x':1}}}}))
        self.assertEqual(mcache.load(self.p),{})

    def test_non_dict_cache_is_discarded(self):
        Path(mcache.path(self.p)).write_text('[]')
        self.assertEqual(mcache.load(self.p),{})

    def test_unwritable_project_does_not_raise(self):
        """A cache that cannot be written is a slow run, never a failed one."""
        mcache.replace('/proc/nonexistent-reelkit','cards','s',{'k':{'x':1}})

    def test_write_is_atomic_leaving_no_partial_file(self):
        mcache.replace(self.p,'cards','s',{'k':{'x':1}})
        json.load(open(mcache.path(self.p),encoding='utf-8'))   # parses or raises
        self.assertEqual(list(Path(self.p).glob('.mcache-*.tmp')),[],'temp file left behind')


class DependencyIsNotCacheable(unittest.TestCase):
    """Rule 3: a hit must never stand in for the tool the gate needs.

    Without Playwright, measure_cards returns {} whatever is cached - otherwise
    a machine with no browser could serve a full set of boxes and verify would
    report cardGeometry measured when nothing measured it."""

    def test_measure_cards_returns_nothing_without_playwright(self):
        import geometry
        real=geometry.HAVE_PW; geometry.HAVE_PW=False
        self.addCleanup(lambda: setattr(geometry,'HAVE_PW',real))
        with tempfile.TemporaryDirectory() as d:
            mcache.replace(d,'cards','any',{'k':{'x':1,'y':2,'w':3,'h':4}})
            self.assertEqual(geometry.measure_cards(d,{'beats':[]},1080,1920),{})

    def test_detect_faces_returns_nothing_without_cv2(self):
        import builtins,cards
        real=builtins.__import__
        def no_cv2(name,*a,**k):
            if name=='cv2': raise ImportError('no cv2')
            return real(name,*a,**k)
        builtins.__import__=no_cv2
        self.addCleanup(lambda: setattr(builtins,'__import__',real))
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cards.detect_faces('any.mp4',{'b01':[1.0]},1080,1920,cache_dir=d),{})


# BOX_JS reads '.card .root', so the fixture has to carry that shape.
CARD=('<div class="card"><div class="root">'
      '<div class="hd">a headline that wraps onto two lines</div></div></div>')
INDEX=('<html><head><style>.root{position:absolute;left:93px;top:50px;width:894px}'
       '.hd{font-size:60px;line-height:1.2}</style></head><body></body></html>')


def fixture(d, card=CARD, beats=('b01',)):
    """The smallest project measure_cards will read: a theme and some cards."""
    pub=Path(d)/'public'; (pub/'cards').mkdir(parents=True,exist_ok=True)
    (pub/'index.html').write_text(INDEX,encoding='utf-8')
    for b in beats: (pub/'cards'/f'{b}.html').write_text(card,encoding='utf-8')
    return {'beats':[{'id':b} for b in beats]}


@unittest.skipUnless(__import__('geometry').HAVE_PW,'playwright not installed')
class MeasuredThroughTheCache(unittest.TestCase):
    """The cache is only correct if a hit equals what a fresh browser would say
    and a changed card misses. Both are checked against a real measurement."""

    def setUp(self):
        import geometry
        self.g=geometry
        self.tmp=tempfile.TemporaryDirectory(); self.d=self.tmp.name; self.addCleanup(self.tmp.cleanup)
        self.plan=fixture(self.d)

    def test_hit_equals_a_fresh_measurement(self):
        cold=self.g.measure_cards(self.d,self.plan,1080,1920,use_cache=False)
        self.assertTrue(cold,'nothing measured - fixture is wrong, not the cache')
        self.g.measure_cards(self.d,self.plan,1080,1920)          # warms it
        self.assertEqual(self.g.measure_cards(self.d,self.plan,1080,1920),cold)

    def test_changed_card_misses(self):
        self.g.measure_cards(self.d,self.plan,1080,1920)
        (Path(self.d)/'public/cards/b01.html').write_text(
            CARD.replace('two lines','two lines and then several more words that wrap again'),
            encoding='utf-8')
        warm=self.g.measure_cards(self.d,self.plan,1080,1920)
        cold=self.g.measure_cards(self.d,self.plan,1080,1920,use_cache=False)
        self.assertEqual(warm,cold,'served a stale box for a card that changed')

    def test_changed_theme_misses(self):
        self.g.measure_cards(self.d,self.plan,1080,1920)
        (Path(self.d)/'public/index.html').write_text(
            INDEX.replace('font-size:60px','font-size:120px'),encoding='utf-8')
        warm=self.g.measure_cards(self.d,self.plan,1080,1920)
        cold=self.g.measure_cards(self.d,self.plan,1080,1920,use_cache=False)
        self.assertEqual(warm,cold,'served a stale box after the theme changed')

    def test_changed_canvas_misses(self):
        self.g.measure_cards(self.d,self.plan,1080,1920)
        warm=self.g.measure_cards(self.d,self.plan,720,1280)
        cold=self.g.measure_cards(self.d,self.plan,720,1280,use_cache=False)
        self.assertEqual(warm,cold,'served a box measured at another canvas size')

    def test_layout_top_is_not_part_of_the_measurement(self):
        """Why the key does not carry layout.top: the harness measures the card
        alone and fit_layout applies the top afterwards, so two layouts give the
        same box. If a change ever makes the harness honour layout.top, this
        fails - and the key must grow to include it before the cache is safe."""
        a=self.g.measure_cards(self.d,self.plan,1080,1920,use_cache=False)
        moved=copy.deepcopy(self.plan)
        for b in moved['beats']: b['layout']={'top':700}
        self.assertEqual(self.g.measure_cards(self.d,moved,1080,1920,use_cache=False),a)

    def test_cache_survives_a_card_being_removed(self):
        plan2=fixture(self.d,beats=('b01','b02'))
        self.g.measure_cards(self.d,plan2,1080,1920)
        os.unlink(Path(self.d)/'public/cards/b02.html')
        self.assertEqual(set(self.g.measure_cards(self.d,plan2,1080,1920)),{'b01'})


if __name__=='__main__': unittest.main()
