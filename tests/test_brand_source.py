#!/usr/bin/env python3
"""One source of truth for the built-in brand.

Run: python3 -m unittest discover -s tests -v

DEFAULT_BRAND used to be a dict literal in reelkit.py alongside
assets/brand/default.json, and the two drifted: a plan with no brand key
rendered canvasBg #F7F7F4 while `"brand": "default"` rendered #FAFAF9, with
nothing to catch it. Same defect class as the plan-box vs CSS drift geometry.py
removed. These tests are what stop it coming back.
"""
import json,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import reelkit  # noqa: E402

BRAND=ROOT/'skills/reelkit/assets/brand'


class SingleSource(unittest.TestCase):
    def test_default_brand_is_the_json_not_a_copy(self):
        self.assertEqual(reelkit.DEFAULT_BRAND,
                         json.loads((BRAND/'default.json').read_text(encoding='utf-8')))

    def test_no_brand_key_renders_like_brand_default(self):
        """The drift was invisible precisely because nobody compared these two."""
        self.assertEqual(reelkit.load_brand('.', {}),
                         reelkit.load_brand('.', {'brand':'default'}))

    def test_editing_the_preset_moves_the_built_in_default(self):
        """Proof it is a load, not a snapshot: patch the JSON's value and the
        resolved brand follows. Guards against someone reintroducing a literal
        that happens to agree today."""
        real=reelkit.DEFAULT_BRAND
        self.addCleanup(setattr,reelkit,'DEFAULT_BRAND',real)
        reelkit.DEFAULT_BRAND=dict(real,canvasBg='#123456')
        self.assertEqual(reelkit.load_brand('.', {})['canvasBg'],'#123456')

    def test_every_shipped_preset_has_the_same_keys(self):
        """A preset missing a key silently inherits the default - fine - but a
        preset with an EXTRA key is a typo nothing else would catch."""
        base=set(reelkit.DEFAULT_BRAND)
        for f in sorted(BRAND.glob('*.json')):
            keys=set(json.loads(f.read_text(encoding='utf-8')))
            self.assertEqual(keys-base,set(),f'{f.name} has keys no default defines')

    def test_presets_resolve_to_a_complete_brand(self):
        """Whatever a preset omits, the resolved brand must still be complete -
        build indexes these keys directly and a missing one is a KeyError mid-build."""
        for f in sorted(BRAND.glob('*.json')):
            b=reelkit.load_brand('.', {'brand':f.stem})
            self.assertEqual(set(reelkit.DEFAULT_BRAND)-set(b),set(),f'{f.name} resolves incomplete')

    def test_unknown_preset_is_refused_not_defaulted(self):
        with self.assertRaises(SystemExit):
            reelkit.load_brand('.', {'brand':'no-such-preset'})

    def test_inline_brand_object_still_overrides(self):
        self.assertEqual(reelkit.load_brand('.', {'brand':{'bg':'#ff0000'}})['bg'],'#ff0000')

    def test_loader_refuses_a_file_that_is_not_a_preset(self):
        """Fatal rather than a silent fallback to hardcoded values - falling back
        is how the copy got there in the first place."""
        import tempfile,os
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d,'assets','brand'))
            open(os.path.join(d,'assets','brand','default.json'),'w').write('{"nope":1}')
            real=reelkit.BRAND_DIR
            reelkit.BRAND_DIR=os.path.join(d,'assets','brand')
            try:
                with self.assertRaises(SystemExit): reelkit._load_default_brand()
            finally: reelkit.BRAND_DIR=real


if __name__=='__main__': unittest.main()
