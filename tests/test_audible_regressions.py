#!/usr/bin/env python3
"""Real ffmpeg regressions for preview scope and ceiling-limited ducking."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'skills/reelkit/scripts'))
import audiomix, loudness  # noqa: E402


def ff(*args):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *args], check=True)


class AudibilityRegressions(unittest.TestCase):
    DUCK = {'enabled': True, 'threshold': 0.05, 'ratio': 8,
            'attackMs': 5, 'releaseMs': 250}

    def project(self, directory, starts=(1.5,), video_seconds=3, hot=True):
        root = Path(directory)
        public = root / 'public'
        (public / 'sfx').mkdir(parents=True)
        voice, video = str(public / 'voice.wav'), str(root / 'video.mp4')
        # Continuous speech-shaped surrogate: every audited band has energy,
        # including sibilance at 6 kHz; no quiet gaps to release the duck.
        tones = ((180, .25), (350, .12), (750, .10), (1500, .09),
                 (3000, .07), (6000, .06), (12000, .06))
        expr = '+'.join(f'{amp}*sin(2*PI*{hz}*t)' for hz, amp in tones)
        if not hot:
            expr = '0.04*sin(2*PI*300*t)'
        ff('-f', 'lavfi', '-i', f'aevalsrc={expr}:s=48000:d=3',
           '-c:a', 'pcm_s16le', voice)
        ff('-f', 'lavfi', '-i',
           'aevalsrc=0.065*sin(2*PI*6500*t):s=48000:d=0.1',
           '-af', 'afade=t=in:d=0.005,afade=t=out:st=0.095:d=0.005',
           '-c:a', 'pcm_s16le', str(public / 'sfx/cue.wav'))
        ff('-f', 'lavfi', '-i', f'color=c=black:s=64x64:d={video_seconds}',
           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', video)
        (public / 'index.html').write_text(''.join(
            f'<audio class="clip" src="sfx/cue.wav" data-start="{at}" '
            'data-duration="0.1" data-volume="0.311"></audio>'
            for at in starts), encoding='utf-8')
        return voice, video, str(root / 'out.mp4')

    def test_preview_skips_windows_past_delivered_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            voice, video, out = self.project(
                directory, starts=(0.2, 0.85, 2.0), video_seconds=1, hot=False)
            logs = []
            audiomix.mix(directory, video, voice, out, duck=self.DUCK,
                         log=logs.append)
            cues = audiomix.cues(directory)
            rows = audiomix.prove(out, voice, cues, log=lambda *args: None)
            self.assertEqual(len(rows), 3)
            self.assertGreaterEqual(rows[0]['headroomDb'], loudness.AUDIBLE_MIN)
            for row in rows[1:]:
                self.assertTrue(row['skipped'])
                self.assertNotIn('headroomDb', row)
            self.assertEqual(sum('skipping' in line for line in logs), 2)

            # An all-skipped preview must not claim its cues were audible.
            logs.clear()
            audiomix.prove(out, voice, cues[1:], log=logs.append)
            self.assertTrue(any('no complete cue windows' in line for line in logs))
            self.assertFalse(any('cue(s) audible' in line for line in logs))

            # The guard must still refuse an inaudible in-range measurement.
            with self.assertRaises(SystemExit) as error:
                audiomix.prove(out, out, cues, log=lambda *args: None)
            self.assertIn('1 of 1 cue(s)', str(error.exception))

    def test_short_cue_still_inaudible_gets_one_measured_dry_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            voice, video, out = self.project(directory)
            public = Path(directory) / 'public'
            ff('-i', str(public / 'sfx/cue.wav'), '-af', 'volume=8',
               '-c:a', 'pcm_s16le', str(public / 'sfx/good.wav'))
            with (public / 'index.html').open('a', encoding='utf-8') as html:
                html.write('<audio class="clip" src="sfx/good.wav" '
                           'data-start="0.3" data-duration="0.1" data-volume="1"></audio>')
            cues = audiomix.calibrate(audiomix.cues(directory), voice,
                                      log=lambda *args: None)
            weak = cues[1]
            # Below the volume ceiling on purpose: the fallback must fire on
            # the still-failing measurement, not only at MAX_VOLUME.
            weak['volume'] = 2.0
            audiomix._render(video, voice, [weak], out, None, self.DUCK,
                             lambda *args: None)
            before = loudness.headroom(out, voice, weak['at'])[0]
            self.assertLess(before, loudness.AUDIBLE_MIN,
                            'fixture must defeat the old loop at its ceiling')

            renders, logs = [], []
            original_render = audiomix._render

            def render(*args, **kwargs):
                renders.append([dict(c) for c in args[2]])
                return original_render(*args, **kwargs)

            duck = dict(self.DUCK)
            with patch.object(audiomix, '_render', side_effect=render):
                audiomix.mix(directory, video, voice, out, duck=duck,
                             log=logs.append)
            rows = audiomix.prove(out, voice, audiomix.cues(directory),
                                 log=lambda *args: None)
            self.assertTrue(all(r['headroomDb'] >= loudness.AUDIBLE_MIN for r in rows))
            self.assertLessEqual(len(renders), 7)  # Four normal mixes, one
            # fallback render, up to two measured top-ups.
            self.assertEqual(sum(bool(cs[1].get('bypassDuck')) for cs in renders), 1)
            self.assertLess(renders[-1][1]['volume'], audiomix.MAX_VOLUME)
            self.assertFalse(renders[-1][0].get('bypassDuck', False))
            self.assertEqual(renders[-1][0]['volume'], renders[-2][0]['volume'])
            self.assertEqual(duck, self.DUCK)
            self.assertEqual(sum('bypassing duck' in line for line in logs), 1)


if __name__ == '__main__':
    unittest.main()
