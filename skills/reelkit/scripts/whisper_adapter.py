#!/usr/bin/env python3
"""Reference transcribe adapter: local Whisper through the HyperFrames CLI.

The default seam, so a clean checkout transcribes with no key and no new
dependency. A hosted adapter (any vendor) is a sibling script with the same
four flags and the same output contract - swap it in providers.json, not here.

Contract: write a JSON array of {text,start,end}, one entry per WORD. Callers
reject segment-level output; every caption line and beat boundary is derived
from these times.
"""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from reelkit import HF  # noqa: E402  - one pinned renderer version for the whole repo

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--audio',required=True);ap.add_argument('--out',required=True)
 ap.add_argument('--lang',required=True);ap.add_argument('--model',required=True);a=ap.parse_args()
 with tempfile.TemporaryDirectory() as d:
  # HyperFrames writes transcript.json beside -d; keep it off the project dir so
  # a failed run cannot leave a half-written transcript where the pipeline looks.
  cmd=['npx','-y',HF,'transcribe',a.audio,'-d',d,'--json',
       '--model',a.model,'--language',a.lang,'--timeout','1800000']
  r=subprocess.run(cmd,capture_output=True,text=True)
  src=Path(d)/'transcript.json'
  if r.returncode!=0 or not src.exists(): raise SystemExit('whisper transcribe failed: '+(r.stderr or r.stdout)[-800:])
  words=json.loads(src.read_text(encoding='utf-8'))
 if isinstance(words,dict): words=words.get('words') or words.get('segments') or []
 words=[{'text':w['text'],'start':float(w['start']),'end':float(w['end'])} for w in words]
 Path(a.out).parent.mkdir(parents=True,exist_ok=True)
 Path(a.out).write_text(json.dumps(words,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
 print(json.dumps({'model':a.model,'language':a.lang,'words':len(words),'output':a.out}))
if __name__=='__main__':main()
