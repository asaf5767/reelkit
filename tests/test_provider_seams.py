#!/usr/bin/env python3
"""Gates are code, not vibes - so the two that block delivery have tests.

Run: python3 -m unittest discover -s tests -v

Covers the transcript contract (segment-level output destroys every downstream
time) and the worker's fail-closed gate (an ERROR blocks, and so does a gate
that could not measure). Stdlib only; no provider is called.
"""
import json,os,sys,tempfile,unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'skills/reelkit/scripts'))
import assets,worker  # noqa: E402


class TranscriptContract(unittest.TestCase):
    def test_words_accepted(self):
        self.assertTrue(assets.words_are_word_level(
            [{'text':'שלום','start':0,'end':.4},{'text':'עולם','start':.4,'end':.9}]))

    def test_segments_rejected(self):
        self.assertFalse(assets.words_are_word_level(
            [{'text':'שלום עולם מה נשמע','start':0,'end':2.4},
             {'text':'הכל טוב כאן','start':2.4,'end':4.0}]))

    def test_one_stray_space_tolerated(self):
        """A single hyphenated or compound token must not fail a real transcript."""
        words=[{'text':f'w{i}','start':i,'end':i+.4} for i in range(20)]
        words[3]['text']='ד״ר כהן'
        self.assertTrue(assets.words_are_word_level(words))


class FailClosedGate(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.p=Path(self.tmp.name)
        self._real=worker.reelkit
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: setattr(worker,'reelkit',self._real))

    def stub_verify(self,payload,code=0):
        (self.p/'verify.json').write_text(json.dumps(payload))
        worker.reelkit=lambda *a,**k: code

    def test_clean_run_passes(self):
        self.stub_verify({'cardGeometry':True,'faceDetection':True,'beats':[{'id':'b01'}],'findings':[]})
        self.assertTrue(worker.gate(self.p,'test'))

    def test_error_finding_blocks(self):
        self.stub_verify({'cardGeometry':True,'faceDetection':True,'beats':[],
                          'findings':[['ERROR','b02','card overlaps the head by 14%']]},code=1)
        self.assertFalse(worker.gate(self.p,'test'))

    def test_warn_alone_does_not_block(self):
        self.stub_verify({'cardGeometry':True,'faceDetection':True,'beats':[],
                          'findings':[['WARN','b02','card grazes the caption band (0.4%)']]})
        self.assertTrue(worker.gate(self.p,'test'))

    def test_unmeasurable_gate_blocks(self):
        """Playwright/OpenCV missing: verify exits 0 having checked nothing."""
        self.stub_verify({'cardGeometry':False,'faceDetection':True,'beats':[],'findings':[]})
        with self.assertRaises(SystemExit) as e: worker.gate(self.p,'test')
        self.assertIn('cannot run',str(e.exception))

    def test_missing_verify_json_blocks(self):
        worker.reelkit=lambda *a,**k: 0
        with self.assertRaises(SystemExit) as e: worker.gate(self.p,'test')
        self.assertIn('no verify.json',str(e.exception))


class TranscribeDefaultAdapter(unittest.TestCase):
    """A clean checkout must transcribe with no key and no config (PR #1 review)."""

    def setUp(self):
        self.c=assets.cfg()['transcribe']
        self._env=os.environ.pop('REELKIT_TRANSCRIBE_CMD',None)
        if self._env is not None:
            self.addCleanup(os.environ.__setitem__,'REELKIT_TRANSCRIBE_CMD',self._env)

    def test_falls_back_to_bundled_adapter(self):
        cmd=assets.transcribe_command(self.c)
        self.assertIn(self.c['defaultAdapter'],cmd)
        for ph in ('{audio}','{out}','{lang}','{model}'): self.assertIn(ph,cmd)

    def test_bundled_adapter_exists(self):
        self.assertTrue((Path(assets.__file__).parent/self.c['defaultAdapter']).exists())

    def test_env_overrides_default(self):
        os.environ['REELKIT_TRANSCRIBE_CMD']='other --audio {audio}'
        self.addCleanup(os.environ.pop,'REELKIT_TRANSCRIBE_CMD',None)
        self.assertEqual(assets.transcribe_command(self.c),'other --audio {audio}')


if __name__=='__main__': unittest.main()
