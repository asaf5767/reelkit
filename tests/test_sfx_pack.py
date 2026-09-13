#!/usr/bin/env python3
"""The bundled CC0 SFX pack and its per-name fallback.

Run: python3 -m unittest discover -s tests -v

Two things are worth a gate here. Licensing, because a non-CC0 file in this
directory cannot legally be re-hosted in a public repo and nothing else would
catch it. And resolution, because a cue name that resolves to nothing is a
silent edit point - the failure this pack exists to fix.
"""
import json,sys,unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'skills/reelkit/scripts'))
import reelkit  # noqa: E402

# every name auto_cues() can emit; a miss here is a silent edit point
AUTO_NAMES=('whoosh','whoosh-short','pop','click-soft','impact-bass-2','riser')


class BundledSfxPack(unittest.TestCase):
    def setUp(self):
        self.pack=Path(reelkit.BUNDLED_SFX)
        self.man=json.loads((self.pack/'manifest.json').read_text())

    def test_manifest_matches_files(self):
        self.assertTrue(self.man,'manifest is empty')
        for name,meta in self.man.items():
            self.assertTrue((self.pack/f'{name}.mp3').exists(),f'{name}.mp3 missing')
            for field in ('license','author','pack','source','duration'):
                self.assertIn(field,meta,f'{name} has no {field}')

    def test_every_bundled_cue_is_cc0(self):
        """Anything not CC0 cannot be redistributed inside this repository."""
        for name,meta in self.man.items():
            self.assertTrue(meta['license'].startswith('CC0'),
                            f'{name} is {meta["license"]}, not CC0 - cannot be bundled')

    def test_no_stray_audio_outside_the_manifest(self):
        """A file nobody recorded provenance for is a licensing unknown."""
        for f in self.pack.glob('*.mp3'):
            self.assertIn(f.stem,self.man,f'{f.name} is not in manifest.json')

    def test_licence_texts_shipped(self):
        packs={m['pack'] for m in self.man.values()}
        have={p.name.split('.License')[0] for p in (self.pack/'licenses').glob('*.License.txt')}
        self.assertEqual(packs-have,set(),'a source pack ships no licence text')

    def test_auto_placer_names_all_resolve(self):
        for name in AUTO_NAMES:
            src,_=reelkit.sfx_src(str(self.pack),name)
            self.assertIsNotNone(src,f'{name} resolves to nothing - silent edit point')

    def test_riser_is_bundled_and_builds(self):
        """The closing cue is real audio now, not the stand-in."""
        self.assertIn('riser',self.man)
        src,_=reelkit.sfx_src(str(self.pack),'riser')
        self.assertIn(str(self.pack),src)
        # long enough to read as a build, short enough for the 1.3s the placer allows
        self.assertGreater(self.man['riser']['duration'],1.0)
        self.assertLess(self.man['riser']['duration'],2.0)

    def test_unmapped_name_still_falls_back_to_synth(self):
        """Per-name fallback must survive the pack growing."""
        src,_=reelkit.sfx_src(str(self.pack),'typing')
        self.assertIsNotNone(src); self.assertNotIn(str(self.pack),src)

    def test_pack_is_used_when_media_use_is_absent(self):
        """A clean clone has no media-use, and must still land on real sounds."""
        real=reelkit.SFX_SEARCH
        reelkit.SFX_SEARCH=['/nonexistent/media-use/sfx']
        try: self.assertEqual(reelkit.find_sfx_dir(),str(self.pack))
        finally: reelkit.SFX_SEARCH=real


if __name__=='__main__': unittest.main()
