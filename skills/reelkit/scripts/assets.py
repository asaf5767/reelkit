#!/usr/bin/env python3
"""Deterministic external authoring and image-asset bridge for Reelkit.

Provider commands are explicit adapters, not hidden network calls:
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
def author(project):
 p=Path(project); transcript=json.loads((p/'transcript.json').read_text()); request=p/'author-request.json'; response=p/'author-response.json'
 atomic_json(request,{'contract':'Return a complete Reelkit graphics plan. Mandatory scroll-stop hook; runners-up; concrete literal/process visuals only; preserve cut timing.','transcript':transcript})
 adapter=os.getenv('REELKIT_PLAN_AUTHOR_CMD')
 if not adapter: raise SystemExit('REELKIT_PLAN_AUTHOR_CMD is required for assisted authoring')
 command(adapter,{'request':request,'response':response}); proposal=json.loads(response.read_text())
 atomic_json(p/'graphics-plan.assisted.json',proposal); print(p/'graphics-plan.assisted.json')
def generate(project):
 p=Path(project); manifest=json.loads((p/'visuals.json').read_text()); adapter=os.getenv('REELKIT_IMAGE_GENERATOR_CMD')
 cache=p/'asset-cache'; public=p/'public/images'; cache.mkdir(exist_ok=True); public.mkdir(parents=True,exist_ok=True); rows=[]
 for slot in manifest.get('slots',[]):
  prompt=slot.get('prompt','').strip(); box=slot.get('box') or [0,0,1024,1024]
  if not prompt: continue
  key=hashlib.sha256(json.dumps({'prompt':prompt,'box':box,'alpha':slot.get('alpha',False),'provider':'fal.ai'},sort_keys=True).encode()).hexdigest()
  cached=cache/f'{key}.png'; target=public/f"{slot['id']}.png"
  if cached.exists(): status='cache-hit'
  else:
   if not adapter: raise SystemExit(f'missing cached asset {slot["id"]}; REELKIT_IMAGE_GENERATOR_CMD is required')
   command(adapter,{'prompt':prompt,'output':cached,'width':box[2],'height':box[3]}); status='generated'
  target.write_bytes(cached.read_bytes()); rows.append({'id':slot['id'],'key':key,'sha256':sha(cached),'status':status,'file':str(target.relative_to(p))})
 atomic_json(p/'asset-ledger.json',{'version':1,'provider':'fal.ai','assets':rows}); print(json.dumps(rows,indent=2))
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
 for c in ('author','generate','verify'): q=sub.add_parser(c); q.add_argument('--project',required=True)
 a=ap.parse_args(); globals()[a.cmd](a.project)
