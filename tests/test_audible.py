#!/usr/bin/env python3
"""Audibility, measured on real signal (v32 regression).

Run: python3 -m unittest discover -s tests -v

The owner watched a reel built on the whole library and said: "I don't hear any
SFX. Anything." The mix had passed its own gate, because the gate asked whether
the delivered samples DIFFERED from the source at each cue, and "the samples
changed" is not "you can hear it".

Measured on a real reel before the fix - every cue against the same voice chain
with the cues removed, in the band where each stands out most:

    whoosh-short  4.78s   +0.3 dB
    whoosh       11.55s   +0.1 dB
    whoosh-short 21.52s   +1.1 dB
    whoosh       33.72s   -0.0 dB
    riser        45.33s   +0.6 dB
    whoosh-short 44.48s   +0.3 dB

Nothing rose over the voice anywhere. The old gate's verdict on that file was
"6 cue(s) proven audible in the output". After the fix the same six read +8.9 to
+9.9 dB, and the integrated loudness moved 0.4 dB - the cues gained presence,
not level.

Two things caused it, and only one was the suspect. The duck was the obvious
culprit and it costs 0-1.1 dB, measured with it on and off. The real cause was
calibration: cues entered at a fixed -11 dBFS scaled by a taste number, about
0.11 linear, where they needed about 1.0 - roughly 20 dB down.
"""
import os,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/reelkit/scripts'))
import audiomix,loudness  # noqa: E402

SFX=ROOT/'skills/reelkit/assets/sfx'


def ff(*a):
    subprocess.run(['ffmpeg','-y','-v','error',*a],check=True)


class TheMeterMeasuresWhatItClaims(unittest.TestCase):
    """A perceptual gate that cannot be checked against known signal is just a
    different number to trust blindly."""

    def tone(self, d, hz, seconds=1.0, vol=1.0):
        p=str(Path(d)/f'{hz}.wav')
        ff('-f','lavfi','-i',f'sine=frequency={hz}:duration={seconds}',
           '-af',f'volume={vol}','-c:a','pcm_s16le',p)
        return p

    def test_energy_lands_in_the_band_that_holds_it(self):
        with tempfile.TemporaryDirectory() as d:
            b=loudness.band_db(loudness._decode(self.tone(d,1500)))
            self.assertEqual(max(b,key=b.get),(1000,2000))
            b=loudness.band_db(loudness._decode(self.tone(d,6000)))
            self.assertEqual(max(b,key=b.get),(4000,8000))

    def test_a_quieter_tone_reads_quieter_by_the_amount_it_was_quietened(self):
        with tempfile.TemporaryDirectory() as d:
            loud=loudness.band_db(loudness._decode(self.tone(d,1500,vol=1.0)))
            soft=loudness.band_db(loudness._decode(self.tone(d,1500,vol=0.1)))
            self.assertAlmostEqual(loud[(1000,2000)]-soft[(1000,2000)],20.0,delta=1.0)

    def test_silence_reads_as_a_floor_not_an_exception(self):
        with tempfile.TemporaryDirectory() as d:
            p=str(Path(d)/'q.wav')
            ff('-f','lavfi','-i','anullsrc=r=48000:cl=mono','-t','1','-c:a','pcm_s16le',p)
            self.assertLess(max(loudness.band_db(loudness._decode(p)).values()),-90)

    def test_a_file_against_itself_has_no_headroom(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.tone(d,1500,2.0)
            self.assertAlmostEqual(loudness.headroom(p,p,0.5)[0],0.0,delta=0.3)

    def test_a_cue_over_a_voice_reads_the_gain_it_was_given(self):
        """The measurement the whole gate rests on, against known signal."""
        with tempfile.TemporaryDirectory() as d:
            voice=self.tone(d,300,2.0,vol=0.3)
            cue=self.tone(d,6000,2.0,vol=0.3)
            mixed=str(Path(d)/'m.wav')
            ff('-i',voice,'-i',cue,'-filter_complex',
               '[0:a][1:a]amix=inputs=2:normalize=0','-c:a','pcm_s16le',mixed)
            got,band,_m,_v=loudness.headroom(mixed,voice,0.5)
            self.assertEqual(band,(4000,8000),'the cue is heard in its own band')
            self.assertGreater(got,20,'a cue this exposed is unmistakably audible')


class ARiserIsMeasuredWhereItArrives(unittest.TestCase):
    def test_the_peak_of_a_ramp_is_not_its_start(self):
        self.assertGreater(loudness.peak_offset(str(SFX/'riser.mp3')),0.3)

    def test_the_peak_of_a_transient_is_its_start(self):
        self.assertLess(loudness.peak_offset(str(SFX/'pop.mp3')),0.2)


class TheGateRefusesWhatCannotBeHeard(unittest.TestCase):
    """End to end through the real mixer, on signal built so the answer is known
    before the measurement runs."""

    def project(self, d, cue, at=1.5, volume=1.0):
        pub=Path(d)/'public'; (pub/'sfx').mkdir(parents=True)
        ff('-f','lavfi','-i','sine=frequency=300:duration=3','-af','volume=0.3',
           '-c:a','aac',str(pub/'voice.m4a'))
        ff('-i',str(cue),'-c:a','libmp3lame',str(pub/'sfx'/'cue.mp3'))
        ff('-f','lavfi','-i','color=c=black:s=64x64:d=3','-c:v','libx264',
           '-pix_fmt','yuv420p',str(Path(d)/'video.mp4'))
        (pub/'index.html').write_text(
            f'<html><audio id="sfx-000-cue" class="clip" src="sfx/cue.mp3" '
            f'data-start="{at}" data-duration="0.5" data-volume="{volume}"></html>',
            encoding='utf-8')
        return str(pub/'voice.m4a')

    def test_a_real_cue_is_calibrated_until_it_clears_the_voice(self):
        with tempfile.TemporaryDirectory() as d:
            voice=self.project(d,SFX/'whoosh.mp3')
            out=str(Path(d)/'out.mp4')
            audiomix.mix(d,str(Path(d)/'video.mp4'),voice,out,log=lambda *a: None)
            ref=str(Path(d)/'ref.wav'); audiomix.voice_only(voice,ref)
            got,band,_m,_v=loudness.headroom(out,ref,1.5)
            self.assertGreaterEqual(got,loudness.AUDIBLE_MIN,
                                    f'only {got} dB over the voice in {band}')

    def test_calibration_replaces_the_authored_volume_rather_than_scaling_it(self):
        """The authored number is the OLD absolute calibration - about -19 dB by
        the time it reached the graph. Folding it in underneath a relative
        target carries the old mistake forward; measured, it asked for -0.3 dB
        where the cue needed +14."""
        with tempfile.TemporaryDirectory() as d:
            voice=self.project(d,SFX/'whoosh.mp3',volume=0.05)
            ref=str(Path(d)/'ref.wav'); audiomix.voice_only(voice,ref)
            cues=audiomix.cues(d)
            quiet=audiomix.calibrate([dict(cues[0],volume=0.05)],ref,log=lambda *a: None)
            loud=audiomix.calibrate([dict(cues[0],volume=0.95)],ref,log=lambda *a: None)
            self.assertEqual(quiet[0]['authoredVolume'],0.05)
            self.assertEqual(loud[0]['authoredVolume'],0.95)
            self.assertEqual(quiet[0]['volume'],loud[0]['volume'],
                             'the calibrated level must not depend on the authored one')

    def test_a_cue_is_never_turned_DOWN_to_meet_the_bar(self):
        """The bar is a floor, not a setpoint. A first cut of this set each cue
        `target` dB above the voice at that instant, which attenuated cues in
        quiet passages - 10 dB above near-silence is still near-silence."""
        with tempfile.TemporaryDirectory() as d:
            pub=Path(d)/'public'; (pub/'sfx').mkdir(parents=True)
            ff('-f','lavfi','-i','sine=frequency=80:duration=3','-af','volume=0.01',
               '-c:a','aac',str(pub/'voice.m4a'))
            ff('-i',str(SFX/'whoosh.mp3'),'-c:a','libmp3lame',str(pub/'sfx'/'cue.mp3'))
            (pub/'index.html').write_text(
                '<html><audio id="sfx-000-cue" class="clip" src="sfx/cue.mp3" '
                'data-start="1.5" data-duration="0.5" data-volume="1.0"></html>',
                encoding='utf-8')
            ref=str(Path(d)/'ref.wav'); audiomix.voice_only(str(pub/'voice.m4a'),ref)
            cal=audiomix.calibrate(audiomix.cues(d),ref,log=lambda *a: None)
            self.assertGreater(cal[0]['volume'],0.02,
                               'a near-silent passage must not silence the cue too')

    def test_an_inaudible_mix_is_refused(self):
        rows=[{'src':'cue','at':1.5,'headroomDb':0.3,'band':[4000,8000],
               'mixedDb':-30.0,'voiceDb':-30.3}]
        with self.assertRaises(SystemExit) as e:
            audiomix.prove('o','r',[{'src':'cue','start':1.5}],log=lambda *a: None,rows=rows)
        self.assertIn('A cue a human cannot hear is a failed export',str(e.exception))


class TheReferenceIsTheProcessedVoice(unittest.TestCase):
    """Measuring against the RAW source instead flatters every cue by whatever
    the voice chain added - 3-6 dB on a real reel, enough to turn an inaudible
    mix into a passing one."""

    def test_the_reference_carries_the_same_chain_as_the_mix(self):
        with tempfile.TemporaryDirectory() as d:
            src=str(Path(d)/'v.wav')
            ff('-f','lavfi','-i','sine=frequency=300:duration=2','-af','volume=0.2',
               '-c:a','pcm_s16le',src)
            plain=str(Path(d)/'plain.wav'); lifted=str(Path(d)/'lifted.wav')
            audiomix.voice_only(src,plain)
            audiomix.voice_only(src,lifted,voice={'enabled':True,'compressor':
                                                  {'thresholdDb':-30,'ratio':2,'makeupDb':6},
                                                  'limiter':{'enabled':False}})
            self.assertGreater(loudness.level_db(lifted),loudness.level_db(plain)+2,
                               'the reference must move when the voice chain does')

    def test_no_chain_means_the_reference_is_the_source(self):
        with tempfile.TemporaryDirectory() as d:
            src=str(Path(d)/'v.wav')
            ff('-f','lavfi','-i','sine=frequency=300:duration=1','-c:a','pcm_s16le',src)
            out=str(Path(d)/'r.wav')
            audiomix.voice_only(src,out)
            self.assertTrue(os.path.exists(out))
            self.assertAlmostEqual(loudness.level_db(out),loudness.level_db(src),delta=0.5)


if __name__=='__main__':
    unittest.main()
