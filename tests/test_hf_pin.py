#!/usr/bin/env python3
"""One pinned HyperFrames version, named the same everywhere.

Run: python3 -m unittest discover -s tests -v

`npx -y hyperframes@latest` cost ~1.6s per invocation resolving what "latest"
means, once per segment per stage. The correctness reason is the real one:
@latest can move between the preview pass and the full pass of the same reel,
which breaks the "identical command, identical inputs = equally valid render"
basis the segment reuse cache rests on - silently, with a green exit code.

reelkit.HF_VERSION is the single source of truth. These tests fail when a
caller or a document drifts from it, which is the only way a half-applied
upgrade shows up before a render does something surprising.
"""
import re,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import reelkit  # noqa: E402

SCRIPTS=ROOT/'skills/reelkit/scripts'
DOCS=[ROOT/'README.md', ROOT/'skills/reelkit/SKILL.md',
      ROOT/'skills/reelkit/examples/ai-took-my-job/NOTES.md']


def fenced(md):
    """The lines inside ``` blocks - the ones a reader actually runs."""
    out,inside=[],False
    for line in md.splitlines():
        if line.lstrip().startswith('```'):
            inside=not inside; continue
        if inside: out.append(line)
    return out


class Pin(unittest.TestCase):
    def test_version_is_an_exact_release(self):
        self.assertRegex(reelkit.HF_VERSION,r'^\d+\.\d+\.\d+$',
                         'the pin must be one published version, not a range or a tag')
        self.assertEqual(reelkit.HF,f'hyperframes@{reelkit.HF_VERSION}')

    def test_no_script_resolves_latest(self):
        """A quoted literal is a command about to run; prose explaining why we
        do not use @latest is not, so only string literals are checked."""
        for f in sorted(SCRIPTS.glob('*.py')):
            txt=f.read_text(encoding='utf-8')
            for q in ('"hyperframes@latest"',"'hyperframes@latest'"):
                self.assertNotIn(q,txt,f'{f.name} still resolves @latest at run time')

    def test_no_doc_teaches_latest(self):
        """Only fenced code blocks - a reader copies those, not the paragraphs
        around them."""
        for f in DOCS:
            for line in fenced(f.read_text(encoding='utf-8')):
                self.assertNotIn('hyperframes@latest',line,
                                 f'{f.name} still tells a reader to run: {line.strip()}')

    def test_docs_teach_the_pinned_version(self):
        for f in DOCS:
            for line in fenced(f.read_text(encoding='utf-8')):
                for found in set(re.findall(r'hyperframes@([\w.]+)',line)):
                    self.assertEqual(found,reelkit.HF_VERSION,
                                     f'{f.name} runs hyperframes@{found}, pin is {reelkit.HF_VERSION}')

    def test_dockerfile_warms_the_pinned_version(self):
        txt=(ROOT/'Dockerfile').read_text(encoding='utf-8')
        m=re.search(r'ARG HF_VERSION=([\w.]+)',txt)
        self.assertIsNotNone(m,'Dockerfile no longer declares ARG HF_VERSION')
        self.assertEqual(m.group(1),reelkit.HF_VERSION,
                         'the image would warm one version and the pipeline ask for another')
        self.assertNotIn('hyperframes@latest',txt)

    def test_transcribe_adapter_shares_the_pin(self):
        """The adapter imports HF rather than repeating the number, so there is
        nothing to forget on an upgrade."""
        txt=(SCRIPTS/'whisper_adapter.py').read_text(encoding='utf-8')
        self.assertIn('from reelkit import HF',txt)
        self.assertNotIn('hyperframes@',txt,'the adapter hardcodes a version again')
        self.assertIn('HF',txt)

    def test_upgrade_procedure_is_documented(self):
        txt=(ROOT/'skills/reelkit/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('HF_VERSION',txt)
        self.assertIn('To upgrade',txt,'SKILL.md does not say how to move the pin')


if __name__=='__main__': unittest.main()
