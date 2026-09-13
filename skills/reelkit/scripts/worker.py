#!/usr/bin/env python3
"""One reel, end to end, unattended - the container entrypoint.

Runs the CLAUDE.md stages in order and refuses to spend render minutes on a plan
the geometry gate has not passed:

  scaffold -> transcribe -> [author -> build -> verify]* -> assets -> build
           -> verify -> render -> export

Every model call is a provider command declared in config/providers.json
(transcribe, planAuthor, image). Nothing here knows which vendor is behind one,
and swapping vendors is a config change plus an adapter script.

The gate is fail-closed in both directions. `verify` reporting an ERROR blocks
delivery, and so does `verify` being unable to measure - a run without Playwright
or OpenCV silently skips the card-geometry and face checks, which is the failure
that puts a card on the speaker's face with a green exit code.
"""
import argparse,json,os,subprocess,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from reelkit import GATE_DEPS  # noqa: E402 - one list of gate capabilities, not two
REELKIT=HERE/'reelkit.py'
ASSETS=HERE/'assets.py'

def finding(f):
 """verify.json serialises findings as {level,id,message}. Read that shape, and
 still accept the (level, id, message) tuple the checker builds internally, so a
 consumer cannot be broken by which end of verify.py it happens to be reading."""
 if isinstance(f,dict): return (f.get('level'),f.get('id'),f.get('message'))
 if isinstance(f,(list,tuple)) and len(f)>=3: return (f[0],f[1],f[2])
 return (None,None,str(f))


def log(stage,msg): print(f'[worker] {stage}: {msg}',flush=True)

def run(*cmd,check=True):
 argv=[str(c) for c in cmd]
 if argv[0].endswith('.py'): argv.insert(0,sys.executable)
 r=subprocess.run(argv)
 if check and r.returncode!=0: raise SystemExit(r.returncode)
 return r.returncode

def reelkit(*args,check=True): return run(REELKIT,*args,check=check)
def assets(*args,check=True): return run(ASSETS,*args,check=check)

def gate(project,stage):
 """verify as a delivery gate: it must run, and it must find nothing."""
 code=reelkit('verify','--project',project,check=False)
 vj=Path(project)/'verify.json'
 if not vj.exists(): raise SystemExit(f'[worker] {stage}: verify wrote no verify.json - gate cannot run, blocking delivery')
 v=json.loads(vj.read_text())
 # GATE_DEPS is reelkit's list, imported rather than repeated: this used to be a
 # second hardcoded tuple here, and adding a capability to one left the other
 # silently accepting a gate that had not run.
 skipped=[(k,dep) for k,dep in GATE_DEPS if not v.get(k)]
 if skipped:
  raise SystemExit(f'[worker] {stage}: verify could not measure '
                   + ', '.join(f'{k} ({dep})' for k,dep in skipped)
                   + ' - a gate that cannot run blocks delivery')
 errs=[f for f in map(finding, v.get('findings',[])) if f[0]=='ERROR']
 if code!=0 or errs:
  for level,cid,msg in errs: log(stage,f'ERROR {cid}: {msg}')
  return False
 log(stage,f'gate passed ({len(v.get("beats",[]))} beats measured)')
 return True

def has_slots(project):
 vj=Path(project)/'visuals.json'
 if not vj.exists(): return False
 m=json.loads(vj.read_text())
 return bool([s for s in (m.get('slots') or []) if s.get('prompt')])

def main():
 ap=argparse.ArgumentParser(description='render one reel end to end')
 ap.add_argument('--project',required=True); ap.add_argument('--video')
 ap.add_argument('--max-repairs',type=int,default=2,help='author/build/verify rounds before giving up')
 ap.add_argument('--out',default='final.mp4'); ap.add_argument('--workers',type=int,default=2)
 ap.add_argument('--preview',action='store_true'); ap.add_argument('--skip-render',action='store_true',
   help='stop after the gate - CI, or a human approval step before the render spend')
 a=ap.parse_args(); p=Path(a.project)

 if a.video and not (p/'public/input-video.mp4').exists():
  log('scaffold',a.video); reelkit('scaffold','--project',p,'--video',a.video,'--upscale')
 if not (p/'transcript.json').exists():
  log('transcribe','no transcript.json'); assets('transcribe','--project',p)

 # Plan loop. Without an author command a hand-written plan.json is built and
 # gated once - there is nothing to repair it with, and that is not an error.
 authoring=bool(os.getenv('REELKIT_PLAN_AUTHOR_CMD'))
 passed=False
 for attempt in range(1,max(1,a.max_repairs)+1):
  if authoring and (attempt>1 or not (p/'plan.json').exists()):
   log('plan',f'authoring (round {attempt})'); assets('author','--project',p)
   proposal=p/'graphics-plan.assisted.json'
   if proposal.exists(): (p/'plan.json').write_text(proposal.read_text(encoding='utf-8'),encoding='utf-8')
  if not (p/'plan.json').exists(): raise SystemExit('[worker] plan: no plan.json and no REELKIT_PLAN_AUTHOR_CMD')
  log('build',f'round {attempt}'); reelkit('build','--project',p)
  if gate(p,'plan'): passed=True; break
  if not authoring: break
  log('plan',f'round {attempt} failed the gate, repairing')
 if not passed: raise SystemExit('[worker] plan: gate never passed - refusing to render')

 # Images are an upgrade, not a dependency: a slot with no file falls back to the
 # drawn card and the reel is complete. Only run the stage when it can actually
 # produce something, so an unset adapter does not fail an otherwise good job.
 # An empty asset-cache/ is not a cache: assets.generate creates the directory
 # before it discovers it has nothing to work with.
 cached_assets=any((p/'asset-cache').glob('*.png'))
 if has_slots(p) and (os.getenv('REELKIT_IMAGE_GENERATOR_CMD') or cached_assets):
  log('assets','generating declared image slots'); assets('generate','--project',p)
  assets('verify','--project',p)
  log('build','rebuilding with images'); reelkit('build','--project',p)
  # Images change card geometry, so the gate runs again on what will ship.
  if not gate(p,'assets'): raise SystemExit('[worker] assets: gate failed after image swap - refusing to render')
 elif has_slots(p):
  log('assets','no image adapter configured - declared slots ship as drawn cards')

 if a.skip_render: log('done','gate passed; --skip-render set, stopping before render'); return 0
 log('render',f'workers={a.workers} preview={a.preview}')
 reelkit('render','--project',p,'--workers',a.workers,'--out',a.out,*(['--preview'] if a.preview else []))
 log('done',str(p/a.out)); return 0

if __name__=='__main__': sys.exit(main())
