#!/usr/bin/env python3
"""Chapter metadata, and the bin_data track it becomes in a deliverable.

Run: python3 -m unittest discover -s tests -v

The defect, found on the Kaggle runner: final.mp4 carried a stray `bin_data`
stream and failed reelkit's own container audit. It was not a stream in the
source at all - the three bundled whoosh files each carried an Ableton export
residue chapter ("Tempo: 120.0"), chapters are GLOBAL metadata rather than
streams, so `-map`, `-dn` and `-sn` never touched them, and the MP4 muxer
materialised them as a chapter track on the way out.

Two defences, both gated here: `-map_chapters -1` on every mux that takes an
external input, and stripping chapters off SFX on ingest so the metadata never
enters the pipeline for libraries we do not control.
"""
import ast,json,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SCRIPTS=ROOT/'skills/reelkit/scripts'
sys.path.insert(0,str(SCRIPTS))
import reelkit  # noqa: E402
from cards import Anim  # noqa: E402


def probe_chapters(path):
    r=subprocess.run(['ffprobe','-v','error','-print_format','json','-show_chapters',
                      str(path)],capture_output=True,text=True)
    return json.loads(r.stdout).get('chapters',[])


def stream_kinds(path):
    r=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type',
                      '-of','default=nw=1:nk=1',str(path)],capture_output=True,text=True)
    return r.stdout.split()


def decoded(path):
    r=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','s16le','-ac','2',
                      '-ar','48000','-'],capture_output=True)
    return r.stdout


def tone(path,seconds=1.0,chapter=None):
    """A short mp3, optionally carrying one embedded chapter."""
    cmd=['ffmpeg','-y','-v','error','-f','lavfi','-i',
         f'sine=frequency=440:duration={seconds}']
    if chapter:
        meta=Path(str(path)+'.ffmeta')
        meta.write_text(';FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\n'
                        f'START=0\nEND={int(seconds*1000)}\ntitle={chapter}\n')
        cmd+=['-i',str(meta),'-map_metadata','1','-map_chapters','1']
    subprocess.run(cmd+['-c:a','libmp3lame','-q:a','4',str(path)],check=True)
    return path


class TheBundledPackIsClean(unittest.TestCase):
    """The root cause: the shipped assets themselves."""

    def test_no_bundled_sfx_carries_chapters(self):
        pack=Path(reelkit.BUNDLED_SFX)
        dirty={p.name:[c.get('tags',{}).get('title','') for c in probe_chapters(p)]
               for p in sorted(pack.glob('*.mp3')) if probe_chapters(p)}
        self.assertEqual(dirty,{},
                         'bundled sfx carrying chapters - they ride every mux into '
                         'the deliverable as a bin_data track')


class ReadingAndStripping(unittest.TestCase):
    def test_chapters_are_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            p=tone(Path(d)/'a.mp3',chapter='Tempo: 120.0')
            self.assertEqual(reelkit.chapters(p),['Tempo: 120.0'])

    def test_a_clean_file_reads_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(reelkit.chapters(tone(Path(d)/'a.mp3')),[])

    def test_strip_removes_them_and_leaves_the_audio_alone(self):
        with tempfile.TemporaryDirectory() as d:
            p=tone(Path(d)/'a.mp3',chapter='Tempo: 120.0')
            before=decoded(p)
            gone=reelkit.strip_chapters(str(p))
            self.assertEqual(gone,['Tempo: 120.0'])
            self.assertEqual(reelkit.chapters(p),[])
            self.assertEqual(decoded(p),before,
                             'stripping chapters must be a stream copy - the samples '
                             'are not allowed to move')

    def test_strip_is_a_no_op_on_a_clean_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=tone(Path(d)/'a.mp3')
            before=p.read_bytes()
            self.assertEqual(reelkit.strip_chapters(str(p)),[])
            self.assertEqual(p.read_bytes(),before,'a clean file must not be rewritten')


class TheLeakItself(unittest.TestCase):
    """Chapters really do become a bin_data track, and the flag really does stop
    it. Without this pair the fix is a claim rather than a measurement."""

    def _mux(self,d,extra):
        vid=Path(d)/'v.mp4'
        subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i',
                        'color=c=black:s=64x64:d=1','-c:v','libx264','-pix_fmt',
                        'yuv420p',str(vid)],check=True)
        cue=tone(Path(d)/'cue.mp3',chapter='Tempo: 120.0')
        out=Path(d)/f'out{len(extra)}.mp4'
        subprocess.run(['ffmpeg','-y','-v','error','-i',str(vid),'-i',str(cue),
                        '-map','0:v:0','-map','1:a:0','-dn','-sn','-write_tmcd','0']
                       +extra+['-c:v','copy','-c:a','aac',str(out)],check=True)
        return out

    def test_without_the_flag_the_chapter_leaks(self):
        with tempfile.TemporaryDirectory() as d:
            out=self._mux(d,[])
            self.assertTrue(probe_chapters(out),
                            'expected the chapter to survive -map/-dn/-sn; if this '
                            'stops holding, ffmpeg changed and the gate below is moot')
            # ffprobe calls the chapter track codec_type `data`, codec_name
            # `bin_data` - the name in the Kaggle report. reelkit's own audit
            # is what has to see it.
            self.assertIn('data',stream_kinds(out))
            self.assertEqual(reelkit._extra_streams(str(out)),['data'])

    def test_with_the_flag_it_does_not(self):
        with tempfile.TemporaryDirectory() as d:
            out=self._mux(d,['-map_chapters','-1'])
            self.assertEqual(probe_chapters(out),[])
            self.assertEqual([k for k in stream_kinds(out) if k not in ('video','audio')],[])


class IngestStripsThem(unittest.TestCase):
    """The pipeline-level defence: a cue never enters a project carrying
    chapters, whichever library it came from. -map_chapters on every mux keeps
    the deliverable clean even if this misses; this keeps the metadata out of
    the project in the first place, for libraries we do not control."""

    def test_a_dirty_library_cue_lands_clean(self):
        with tempfile.TemporaryDirectory() as d:
            lib=Path(d)/'lib'; lib.mkdir()
            tone(lib/'pop.mp3',seconds=0.4,chapter='Tempo: 120.0')
            (lib/'manifest.json').write_text(json.dumps({'pop':{'duration':0.4}}))
            pub=Path(d)/'public'; pub.mkdir()
            plan={'audio':{'sfxDir':str(lib),'autoSfx':False},
                  'beats':[{'id':'b1','start':0.0,'end':2.0,
                            'sfx':[{'name':'pop','at':0.5}]}]}
            tags,names=reelkit.resolve_sfx(plan,str(pub),4.0,Anim(30))
            landed=pub/'sfx/pop.mp3'
            self.assertTrue(landed.exists(),f'cue never copied in: {tags}')
            self.assertEqual(probe_chapters(landed),[],
                             'ingest let a chapter through into the project')


class TheGates(unittest.TestCase):
    def test_container_audit_names_chapters(self):
        with tempfile.TemporaryDirectory() as d:
            vid=Path(d)/'v.mp4'
            cue=tone(Path(d)/'cue.mp3',chapter='Tempo: 120.0')
            subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i',
                            'color=c=black:s=64x64:d=1','-i',str(cue),'-map','0:v:0',
                            '-map','1:a:0','-c:v','libx264','-pix_fmt','yuv420p',
                            '-c:a','aac','-movflags','+faststart',str(vid)],check=True)
            errs=[m for lvl,m in reelkit.container_problems(str(vid)) if lvl=='ERROR']
            self.assertTrue(any('chapter' in m for m in errs),
                            f'container audit said nothing about chapters: {errs}')
            self.assertTrue(any('Tempo: 120.0' in m for m in errs),
                            'the audit should name the chapter, not just count it')

    def test_every_mux_passes_map_chapters(self):
        """Source-level: a new mux that forgets the flag re-opens the leak, and
        nothing would catch it until a render reaches the runner. Any function
        that builds an ffmpeg command with explicit stream maps is writing a
        file, so it has to drop chapters on the way."""
        missing=[]
        for f in ('reelkit.py','audiomix.py','segmentrender.py'):
            tree=ast.parse((SCRIPTS/f).read_text())
            for fn in [n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)]:
                lit=[n.value for n in ast.walk(fn)
                     if isinstance(n,ast.Constant) and isinstance(n.value,str)]
                if 'ffmpeg' not in lit:
                    continue
                maps=[v for v in lit if v.startswith('-map') and v!='-map_chapters']
                if maps and '-map_chapters' not in lit:
                    missing.append(f'{f}:{fn.name}')
        self.assertEqual(missing,[],
                         'ffmpeg command with stream maps but no `-map_chapters -1`')


if __name__=='__main__':
    unittest.main()
