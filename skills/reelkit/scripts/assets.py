#!/usr/bin/env python3
"""Deterministic external authoring and image-asset bridge for Reelkit.

Provider commands are explicit adapters, not hidden network calls:
  REELKIT_TRANSCRIBE_CMD='whisper-adapter --audio {audio} --out {out} --lang {lang} --model {model}'
  REELKIT_PLAN_AUTHOR_CMD='author-model --request {request} --response {response}'
  REELKIT_IMAGE_GENERATOR_CMD='fal-adapter --prompt {prompt} --out {output} --width {width} --height {height}'
Once generated, assets and hashes are cached in the project checkpoint. Re-renders never call providers.
"""
import argparse,hashlib,json,os,shlex,subprocess,tempfile
from pathlib import Path

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def atomic_json(path,obj):
 p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=p.parent,delete=False) as f: json.dump(obj,f,ensure_ascii=False,indent=2); f.write('\n'); n=f.name
 os.replace(n,p)
def command(template, values):
 cmd=template.format(**{k:shlex.quote(str(v)) for k,v in values.items()}); subprocess.run(cmd,shell=True,check=True)
def cfg():
 return json.loads((Path(__file__).parent.parent/'config/providers.json').read_text())
def words_are_word_level(words):
 """Segment-level output silently destroys every downstream time. Words in any
 language carry no internal space, so a transcript whose entries do is segments."""
 spaced=sum(1 for w in words if ' ' in w['text'].strip())
 return spaced <= max(1,int(0.2*len(words)))
def transcribe(project):
 p=Path(project); audio=p/'audio.mp3'
 if not audio.exists(): raise SystemExit(f'{audio} missing - run `reelkit.py scaffold` first')
 c=cfg()['transcribe']; model=os.getenv('REELKIT_TRANSCRIBE_MODEL',c['model']); lang=os.getenv('REELKIT_TRANSCRIBE_LANG',c['language'])
 out=p/'transcript.json'; cache=p/'asset-cache'; cache.mkdir(exist_ok=True)
 key=hashlib.sha256(json.dumps({'audio':sha(audio),'model':model,'lang':lang,'granularity':c['granularity']},sort_keys=True).encode()).hexdigest()
 cached=cache/f'transcript-{key}.json'
 if cached.exists(): status='cache-hit'
 else:
  adapter=os.getenv(c['commandEnv'])
  if not adapter: raise SystemExit(f"{c['commandEnv']} is required to transcribe (no cached transcript for this audio/model)")
  command(adapter,{'audio':audio,'out':cached,'lang':lang,'model':model}); status='transcribed'
 words=json.loads(cached.read_text())
 if isinstance(words,dict): words=words.get('words') or words.get('segments') or []
 if not words: raise SystemExit('transcribe adapter returned no words')
 for w in words:
  if not all(k in w for k in ('text','start','end')): raise SystemExit('transcribe adapter must return {text,start,end} per word')
 if not words_are_word_level(words): raise SystemExit('transcribe adapter returned segment-level text; reelkit needs word-level timestamps')
 atomic_json(out,words); atomic_json(p/'transcript-ledger.json',{'version':1,'model':model,'language':lang,'status':status,'key':key,'words':len(words),'sha256':sha(cached)})
 print(f'{out} ({len(words)} words, {status}, {model}/{lang})')
def author(project):
 p=Path(project); transcript=json.loads((p/'transcript.json').read_text()); request=p/'author-request.json'; response=p/'author-response.json'
 atomic_json(request,{'contract':'Return a complete Reelkit graphics plan. Mandatory scroll-stop hook; runners-up; concrete literal/process visuals only; preserve cut timing.','transcript':transcript})
 adapter=os.getenv('REELKIT_PLAN_AUTHOR_CMD')
 if not adapter: raise SystemExit('REELKIT_PLAN_AUTHOR_CMD is required for assisted authoring')
 command(adapter,{'request':request,'response':response}); proposal=json.loads(response.read_text())
 atomic_json(p/'graphics-plan.assisted.json',proposal); print(p/'graphics-plan.assisted.json')
def generate(project):
 p=Path(project); manifest=json.loads((p/'visuals.json').read_text()); adapter=os.getenv('REELKIT_IMAGE_GENERATOR_CMD')
 cfg=json.loads((Path(__file__).parent.parent/'config/providers.json').read_text()); image_cfg=cfg['image']; tier=os.getenv('REELKIT_IMAGE_TIER','iteration'); model=image_cfg['finalModel' if tier=='final' else 'iterationModel']; cache=p/'asset-cache'; public=p/'public/images'; cache.mkdir(exist_ok=True); public.mkdir(parents=True,exist_ok=True); rows=[]
 for slot in manifest.get('slots',[]):
  prompt=slot.get('prompt','').strip(); box=slot.get('box') or [0,0,1024,1024]
  if not prompt: continue
  key=hashlib.sha256(json.dumps({'prompt':prompt,'box':box,'alpha':slot.get('alpha',False),'provider':'fal.ai','model':model},sort_keys=True).encode()).hexdigest()
  cached=cache/f'{key}.png'; target=public/f"{slot['id']}.png"
  if cached.exists(): status='cache-hit'
  else:
   if not adapter: raise SystemExit(f'missing cached asset {slot["id"]}; REELKIT_IMAGE_GENERATOR_CMD is required')
   command(adapter,{'prompt':prompt,'output':cached,'width':box[2],'height':box[3],'model':model}); status='generated'
  target.write_bytes(cached.read_bytes()); rows.append({'id':slot['id'],'key':key,'sha256':sha(cached),'status':status,'model':model,'estimatedCostUsd':None,'file':str(target.relative_to(p))})
 atomic_json(p/'asset-ledger.json',{'version':1,'provider':'fal.ai','model':model,'assets':rows}); print(json.dumps(rows,indent=2))
def verify(project):
 p=Path(project); ledger=json.loads((p/'asset-ledger.json').read_text())
 bad=[]
 for x in ledger['assets']:
  f=p/x['file'];
  if not f.exists() or sha(f)!=x['sha256']: bad.append(x['id'])
 if bad: raise SystemExit('asset hash mismatch: '+','.join(bad))
 print(f"asset cache verified: {len(ledger['assets'])} file(s)")
if __name__=='__main__':
 ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
 for c in ('transcribe','author','generate','verify'): q=sub.add_parser(c); q.add_argument('--project',required=True)
 a=ap.parse_args(); globals()[a.cmd](a.project)
