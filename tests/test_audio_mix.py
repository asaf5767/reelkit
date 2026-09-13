#!/usr/bin/env python3
"""The audio mix stage, and the cue drop it exists to fix.

Run: python3 -m unittest discover -s tests -v

The defect: segmentrender joined video with `-an` and re-muxed the ORIGINAL
file's audio, which kept sync perfectly and threw away every SFX cue. The direct
render kept them. Kaggle renders through the segmented path, so "SFX by
construction" was not holding where it mattered.

Measured on the 12s sample at the three cue timestamps, base profile so nothing
else moves: source -17.9 / -18.1 / -18.0 dBFS, mixed -14.2 / -13.2 / -13.0. At
t=2.0s, where no cue sits, both read -18.0 - cues restored, speech untouched.
"""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import audiomix,style  # noqa: E402

AUDIO=('<audio id="sfx-000-pop" class="clip" src="sfx/pop.mp3" data-start="0.1333" '
       'data-duration="0.7200" data-track-index="20" data-volume="0.145">')


class ReadingCues(unittest.TestCase):
    """Cues are read back from the built composition, not from plan.json: the
    hook beat and the automatic cues are materialised during build, so the plan
    would miss exactly the ones doctrine says are never optional."""

    def project(self, html, files=('pop.mp3',)):
        d=tempfile.mkdtemp(); self.addCleanup(lambda: __import__('shutil').rmtree(d,True))
        pub=Path(d)/'public'; (pub/'sfx').mkdir(parents=True)
        (pub/'index.html').write_text(html,encoding='utf-8')
        for f in files: (pub/'sfx'/f).write_bytes(b'\0'*64)
        return d

    def test_a_placed_cue_is_found(self):
        c=audiomix.cues(self.project(f'<html><body>{AUDIO}</body></html>'))
        self.assertEqual(len(c),1)
        self.assertAlmostEqual(c[0]['start'],0.1333); self.assertAlmostEqual(c[0]['volume'],0.145)

    def test_cues_come_back_in_time_order(self):
        two=AUDIO+AUDIO.replace('data-start="0.1333"','data-start="0.05"')
        self.assertEqual([c['start'] for c in audiomix.cues(self.project(f'<html>{two}</html>'))],
                         [0.05,0.1333])

    def test_a_cue_whose_file_is_missing_is_not_invented(self):
        c=audiomix.cues(self.project(f'<html>{AUDIO}</html>',files=()))
        self.assertEqual(c,[])

    def test_non_clip_audio_is_ignored(self):
        html='<html><audio src="sfx/pop.mp3" data-start="1"></audio></html>'
        self.assertEqual(audiomix.cues(self.project(html)),[])

    def test_no_composition_is_no_cues_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(audiomix.cues(d),[])


class VoiceChain(unittest.TestCase):
    def test_disabled_profile_emits_no_filters(self):
        self.assertEqual(audiomix.voice_filters({'enabled':False}),[])
        self.assertEqual(audiomix.voice_filters({}),[])
        self.assertEqual(audiomix.voice_filters(None),[])

    def test_chain_order_is_rumble_compress_shape_limit(self):
        """The compressor must not be pumped by rumble, and the limiter must be
        last or something downstream can exceed the ceiling."""
        f=audiomix.voice_filters({'enabled':True,'highpassHz':80,
                                  'eq':[{'hz':3200,'gainDb':2}]})
        names=[x.split('=')[0] for x in f]
        self.assertEqual(names,['highpass','acompressor','equalizer','alimiter'])

    def test_profile_values_reach_the_filter(self):
        f=audiomix.voice_filters({'enabled':True,
                                  'compressor':{'thresholdDb':-24,'ratio':5}})
        self.assertIn('threshold=-24dB',' '.join(f)); self.assertIn('ratio=5',' '.join(f))

    def test_house_profile_turns_it_on_and_base_leaves_it_off(self):
        v,_=style.audio_cfg(style.load('assaf-v1')[0]); self.assertTrue(v['enabled'])
        v,_=style.audio_cfg(style.load('base')[0]); self.assertFalse(v['enabled'])


class Graph(unittest.TestCase):
    CUE=[{'src':'sfx/pop.mp3','path':'/x/pop.mp3','start':1.5,'duration':0.5,'volume':0.11}]

    def test_nothing_to_do_returns_nothing(self):
        """A project with no cues and no processing keeps its original stream
        rather than paying a re-encode for a no-op."""
        self.assertEqual(audiomix.filtergraph([],{},{}),(None,None))

    def test_cue_is_delayed_to_its_absolute_time(self):
        fc,_=audiomix.filtergraph(self.CUE,{},{})
        self.assertIn('adelay=1500|1500',fc)

    def test_cue_volume_is_applied(self):
        fc,_=audiomix.filtergraph(self.CUE,{},{})
        self.assertIn('volume=0.1100',fc)

    def test_input_indices_are_the_ones_passed(self):
        """The graph must not assume an input order the caller did not use."""
        fc,_=audiomix.filtergraph(self.CUE,{'enabled':True},{},speech=1,cue_base=2)
        self.assertIn('[1:a]',fc); self.assertIn('[2:a]',fc)
        fc,_=audiomix.filtergraph(self.CUE,{'enabled':True},{},speech=3,cue_base=7)
        self.assertIn('[3:a]',fc); self.assertIn('[7:a]',fc)

    def test_ducking_sidechains_cues_under_the_voice_not_the_reverse(self):
        fc,_=audiomix.filtergraph(self.CUE,{},{'enabled':True})
        self.assertIn('[sfxraw][spk]sidechaincompress',fc,
                      'a cue that competes with a word costs the word')

    def test_no_ducking_means_no_sidechain(self):
        fc,_=audiomix.filtergraph(self.CUE,{},{'enabled':False})
        self.assertNotIn('sidechaincompress',fc)

    def test_mix_never_normalises(self):
        """normalize=1 would quietly attenuate the speech as cues are added."""
        fc,_=audiomix.filtergraph(self.CUE,{},{})
        self.assertNotIn('normalize=1',fc); self.assertIn('normalize=0',fc)

    def test_voice_only_still_produces_a_graph(self):
        fc,label=audiomix.filtergraph([],{'enabled':True},{})
        self.assertIsNotNone(fc); self.assertEqual(label,'[sp]')


class ProfileSchema(unittest.TestCase):
    """Slice 2 widens the schema in the same commit that consumes it."""

    def bad(self,prof):
        with self.assertRaises(SystemExit) as e: style.validate(prof,'t')
        return str(e.exception)

    def test_audio_section_is_accepted(self):
        style.validate({'audio':{'voice':{'enabled':True},'duck':{'enabled':True}}},'t')

    def test_unknown_voice_key_is_refused(self):
        self.assertIn('reverb',self.bad({'audio':{'voice':{'reverb':1}}}))

    def test_unknown_duck_key_is_refused(self):
        self.assertIn('sidechain',self.bad({'audio':{'duck':{'sidechain':1}}}))

    def test_eq_band_needs_hz_and_gain(self):
        self.assertIn('eq',self.bad({'audio':{'voice':{'eq':[{'hz':200}]}}}))

    def test_cue_placement_is_not_configurable(self):
        """Losing a cue is a defect, never a preference - so there is no key
        for it to hide behind."""
        self.assertNotIn('sfx',style.SCHEMA['audio'])
        self.assertNotIn('cues',style.SCHEMA['audio'])


class RealMix(unittest.TestCase):
    """One end-to-end mix through ffmpeg, so the graph is known to be valid
    rather than merely well-formed."""

    def test_cue_lands_and_is_audible(self):
        if not shutil_which('ffmpeg'): self.skipTest('ffmpeg not installed')
        with tempfile.TemporaryDirectory() as d:
            pub=Path(d)/'public'; (pub/'sfx').mkdir(parents=True)
            sub=lambda *a: subprocess.run(['ffmpeg','-y','-v','error',*a],check=True)
            # 3s of near-silence as the "speech", and a loud 1kHz blip as the cue
            sub('-f','lavfi','-i','sine=frequency=80:duration=3','-af','volume=0.02',
                '-c:a','aac',str(pub/'quiet.m4a'))
            sub('-f','lavfi','-i','sine=frequency=1000:duration=0.3',str(pub/'sfx'/'blip.mp3'))
            sub('-f','lavfi','-i','color=c=black:s=64x64:d=3','-i',str(pub/'quiet.m4a'),
                '-shortest','-c:v','libx264','-pix_fmt','yuv420p',str(pub/'input-video.mp4'))
            sub('-f','lavfi','-i','color=c=black:s=64x64:d=3','-c:v','libx264',
                '-pix_fmt','yuv420p',str(Path(d)/'video.mp4'))
            (pub/'index.html').write_text(
                '<html><audio id="sfx-000-blip" class="clip" src="sfx/blip.mp3" '
                'data-start="1.5" data-duration="0.3" data-volume="1.0"></html>',encoding='utf-8')
            out=str(Path(d)/'out.mp4')
            audiomix.mix(d,str(Path(d)/'video.mp4'),str(pub/'input-video.mp4'),out,log=lambda *a: None)
            self.assertTrue(os.path.exists(out))
            self.assertGreater(peak(out,1.5,0.25),peak(out,0.2,0.25)+10,
                               'the cue is not audible in the mixed output')


def shutil_which(x):
    import shutil; return shutil.which(x)


def peak(path,ss,t):
    r=subprocess.run(['ffmpeg','-hide_banner','-ss',str(ss),'-t',str(t),'-i',path,
                      '-af','volumedetect','-f','null','-'],capture_output=True,text=True)
    for line in r.stderr.splitlines():
        if 'max_volume' in line: return float(line.split(':')[-1].replace('dB','').strip())
    return -99.0



class ProvesItsOwnWork(unittest.TestCase):
    """A mix that runs cleanly and places nothing is inaudible to every other
    gate: the file decodes, the levels look ordinary, the cues are simply gone.
    Kaggle v16 caught exactly that, so the stage now measures its own output."""

    def test_the_graph_does_not_renormalise_when_a_cue_ends(self):
        """amix renormalises over 2s as each input ends, which pulled the whole
        mix DOWN after every cue - the riser measured 3 dB below the untouched
        source."""
        fc,_=audiomix.filtergraph(
            [{'src':'a','path':'a','start':1.0,'duration':.5,'volume':.1}],{},{})
        self.assertEqual(fc.count('dropout_transition=0'),fc.count('amix='))

    def test_every_input_is_normalised_before_it_is_mixed(self):
        """A mono 44.1k source against stereo cues otherwise leaves the
        conversions wherever ffmpeg puts them, which varies by build."""
        fc,_=audiomix.filtergraph(
            [{'src':'a','path':'a','start':1.0,'duration':.5,'volume':.1}],{},{})
        self.assertEqual(fc.count('sample_rates=48000'),2)

    def test_the_mux_maps_only_video_and_audio(self):
        """A phone source can carry a timecode or telemetry track, and a
        `-c copy` without explicit maps carries it into the deliverable."""
        src=(ROOT/'skills/reelkit/scripts/audiomix.py').read_text()
        self.assertEqual(src.count('"-dn", "-sn"'),2,'both mux paths must drop data streams')

    def test_the_proof_seeks_accurately(self):
        """`-ss` before `-i` is approximate; a few ms of misalignment stops the
        difference cancelling and every cue then reads as present."""
        src=(ROOT/'skills/reelkit/scripts/audiomix.py').read_text()
        i=src.index('def added_db(')
        body=src[i:src.index('def prove(')]
        self.assertIn('atrim=',body)
        self.assertNotIn('"-ss"',body,'approximate seek cannot measure a difference')

    def test_the_proof_window_covers_a_long_cue(self):
        """A riser opens near silence and builds; 0.45s at its onset reported it
        missing when it was correctly placed."""
        self.assertGreater(audiomix.PROOF_MAX_SPAN,audiomix.PROOF_WINDOW)

    def test_the_floor_sits_between_the_noise_and_a_real_cue(self):
        """Measured on the sample: noise floor -63..-67 dBFS, real cues -17..-22."""
        self.assertLess(audiomix.PROOF_FLOOR_DB,-30)
        self.assertGreater(audiomix.PROOF_FLOOR_DB,-60)

    def test_an_unmeasurable_cue_blocks_rather_than_passes(self):
        real=audiomix.added_db
        audiomix.added_db=lambda *a,**k: None
        self.addCleanup(setattr,audiomix,'added_db',real)
        with self.assertRaises(SystemExit) as e:
            audiomix.prove('o','s',[{'src':'x','start':1.0,'duration':.5}],log=lambda *a: None)
        self.assertIn('could not measure',str(e.exception))

    def test_a_silent_cue_blocks(self):
        real=audiomix.added_db
        audiomix.added_db=lambda *a,**k: -70.0
        self.addCleanup(setattr,audiomix,'added_db',real)
        with self.assertRaises(SystemExit) as e:
            audiomix.prove('o','s',[{'src':'x','start':1.0,'duration':.5}],log=lambda *a: None)
        self.assertIn('not audible',str(e.exception))

    def test_an_audible_cue_passes(self):
        real=audiomix.added_db
        audiomix.added_db=lambda *a,**k: -18.0
        self.addCleanup(setattr,audiomix,'added_db',real)
        audiomix.prove('o','s',[{'src':'x','start':1.0,'duration':.5}],log=lambda *a: None)

    def test_no_cues_means_nothing_to_prove(self):
        audiomix.prove('o','s',[],log=lambda *a: None)


class SegmentMixIsNotRepeated(unittest.TestCase):
    """The join discards segment audio with `-an`, so mixing per segment is work
    nobody hears - it cost ~28s of the ~30s the stage was adding."""

    def test_segmentrender_defers_the_mix(self):
        src=(ROOT/'skills/reelkit/scripts/segmentrender.py').read_text()
        self.assertIn('--no-audio-mix',src)

    def test_render_supports_deferring(self):
        import reelkit,inspect
        self.assertIn('mix_audio',inspect.signature(reelkit.render_project).parameters)


class ContainerAuditRejectsStrayStreams(unittest.TestCase):
    def test_a_data_stream_is_an_error(self):
        import reelkit,subprocess,tempfile,os
        if not shutil_which('ffmpeg'): self.skipTest('ffmpeg not installed')
        with tempfile.TemporaryDirectory() as d:
            f=os.path.join(d,'tc.mp4')
            subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=black:s=64x64:d=1',
                            '-f','lavfi','-i','sine=frequency=200:duration=1','-map','0:v','-map','1:a',
                            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',
                            '-timecode','00:00:00:00',f],check=True)
            self.assertEqual(reelkit._extra_streams(f),['data'])
            self.assertTrue([p for p in reelkit.container_problems(f)
                             if p[0]=='ERROR' and 'unexpected stream' in p[1]])

    def test_a_clean_file_passes(self):
        import reelkit,subprocess,tempfile,os
        if not shutil_which('ffmpeg'): self.skipTest('ffmpeg not installed')
        with tempfile.TemporaryDirectory() as d:
            f=os.path.join(d,'ok.mp4')
            subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=black:s=64x64:d=1',
                            '-f','lavfi','-i','sine=frequency=200:duration=1','-map','0:v','-map','1:a',
                            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',f],check=True)
            self.assertEqual(reelkit._extra_streams(f),[])


if __name__=='__main__': unittest.main()
