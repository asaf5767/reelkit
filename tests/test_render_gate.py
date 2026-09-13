#!/usr/bin/env python3
"""The render-time geometry gate (NEXT #1).

Run: python3 -m unittest discover -s tests -v

`build` already refuses a card it cannot fit, but a driver can render a project
built earlier or elsewhere - which is how head-zone collisions were still being
caught by hand on snapshots. render_project() is the one funnel every path goes
through, so the decision it makes there is worth pinning.
"""
import sys,unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'skills/reelkit/scripts'))
import reelkit  # noqa: E402

OK={'cardGeometry':True,'faceDetection':True,'findings':[]}


class GateDecision(unittest.TestCase):
    def test_clean_result_lets_the_render_through(self):
        self.assertEqual(reelkit.gate_problems(OK),[])

    def test_error_finding_blocks(self):
        v=dict(OK,findings=[{'level':'ERROR','id':'b06','message':'card covers 17.6% of the head'}])
        p=reelkit.gate_problems(v)
        self.assertEqual(len(p),1); self.assertIn('b06',p[0]); self.assertIn('17.6%',p[0])

    def test_warn_does_not_block(self):
        v=dict(OK,findings=[{'level':'WARN','id':'b01','message':'grazes the caption band'}])
        self.assertEqual(reelkit.gate_problems(v),[])

    def test_tuple_findings_are_understood(self):
        v=dict(OK,findings=[['ERROR','b02','off canvas']])
        self.assertEqual(len(reelkit.gate_problems(v)),1)

    def test_every_error_is_reported_not_just_the_first(self):
        v=dict(OK,findings=[{'level':'ERROR','id':'a','message':'x'},
                            {'level':'WARN','id':'b','message':'y'},
                            {'level':'ERROR','id':'c','message':'z'}])
        self.assertEqual(len(reelkit.gate_problems(v)),2)

    def test_malformed_finding_is_ignored_not_crashed_on(self):
        """A shape change in verify.json must not take the gate down with it."""
        v=dict(OK,findings=[None,'oops',{},{'level':'ERROR','id':'b1','message':'real'}])
        self.assertEqual(len(reelkit.gate_problems(v)),1)


class GateCannotRun(unittest.TestCase):
    """A gate that cannot run blocks delivery (CLAUDE.md)."""

    def test_missing_playwright_blocks(self):
        p=reelkit.gate_problems(dict(OK,cardGeometry=False))
        self.assertEqual(len(p),1); self.assertIn('playwright',p[0])

    def test_missing_opencv_blocks(self):
        p=reelkit.gate_problems(dict(OK,faceDetection=False))
        self.assertEqual(len(p),1); self.assertIn('opencv',p[0])

    def test_message_names_how_to_fix_it(self):
        """The Kaggle kernel has to be able to act on this without guessing."""
        p=reelkit.gate_problems(dict(OK,cardGeometry=False,faceDetection=False))[0]
        self.assertIn('requirements-verify.txt',p)
        self.assertIn('playwright install',p)

    def test_unmeasured_run_blocks_even_with_no_findings(self):
        self.assertTrue(reelkit.gate_problems({'cardGeometry':False,'faceDetection':False}))


class DependenciesAreDeclared(unittest.TestCase):
    def test_requirements_file_exists_and_pins_opencv(self):
        f=Path(reelkit.VERIFY_REQS)
        self.assertTrue(f.exists(),f'{f} missing')
        body=f.read_text()
        self.assertIn('opencv-python-headless<5',body,'the 5.x pin is load-bearing')
        self.assertIn('playwright',body)


if __name__=='__main__': unittest.main()
