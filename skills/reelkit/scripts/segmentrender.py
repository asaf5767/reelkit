#!/usr/bin/env python3
"""Restartable Reelkit rendering as independently durable timeline segments."""
import argparse, copy, hashlib, json, math, os, shutil, subprocess, sys
from pathlib import Path


def run(cmd, cwd=None):
    print('+', ' '.join(map(str,cmd)), flush=True)
    subprocess.run(list(map(str,cmd)), cwd=cwd, check=True)


def probe(path, field='format=duration', count_frames=False):
    cmd=['ffprobe','-v','error']+(['-count_frames'] if count_frames else [])
    return subprocess.check_output(cmd+['-show_entries',field,'-of','default=nw=1:nk=1',path],text=True).strip()


def boundaries(plan, duration, target, grid_fps=10):
    # Everything here is SECONDS. `total` used to be round(duration*fps), i.e.
    # frames, while target/cur/candidates were seconds - so the loop ran until it
    # had walked `duration*fps` seconds and a 12s clip prepared 34 segments whose
    # boundaries ran to 360, far past the end of the media.
    q=lambda t: round(t*grid_fps)/grid_fps
    total=q(duration)
    # Prefer boundaries between visual beats, so no overlay is cut in half.
    # Boundaries lie on the coarsest output frame grid (10fps preview). Then both
    # preview (10fps) and full (30fps) segment durations are integral frame counts.
    # This prevents ceil/round drift from accumulating across joins.
    candidates={q(float(b['end'])) for b in plan['beats'] if 0 < float(b['end']) < duration}
    out=[0.0]; cur=0.0
    while total-cur > target*1.35:
        goal=cur+target
        viable=[x for x in candidates if cur+target*.55 < x < total]
        nxt=min(viable,key=lambda x:abs(x-goal)) if viable else q(min(total,goal))
        if nxt>=total or nxt<=cur: break
        out.append(nxt);cur=nxt
    out.append(total)
    return out


def shift_plan(plan,start,end):
    q=copy.deepcopy(plan); fps=int(q.get('meta',{}).get('fps',30)); dur=end-start
    q.setdefault('meta',{})['duration']=dur
    # Intermediate boundaries are exact on both 10fps and 30fps grids, so they
    # must not trim. Only the final segment inherits Reelkit's global tail trim.
    q['meta']['trimTail']=False
    beats=[]
    for b in q['beats']:
        s,e=float(b['start']),float(b['end'])
        # A beat belongs to the segment where it starts; a grid-quantized boundary
        # may trim its tail by <50ms, preferable to duplicating its animation.
        if start <= s < end:
            b['start']=round(max(0,s-start),4);b['end']=round(min(dur,e-start),4)
            if b['end']>b['start']:beats.append(b)
    q['beats']=beats
    fr=q.get('framing',{}); punches=fr.get('punches',[])
    # Carry the resting zoom state into each segment, then shift future changes.
    state=float(fr.get('scale',1.0))
    for p in sorted(punches,key=lambda x:float(x['at'])):
        if float(p['at'])<=start: state=float(fr.get('scale',1))*float(p['to'])
    fr['scale']=state
    fr['punches']=[dict(p,at=round(float(p['at'])-start,4),
                         **({'from':float(p['from'])*float(plan.get('framing',{}).get('scale',1))/state,
                             'to':float(p['to'])*float(plan.get('framing',{}).get('scale',1))/state} if state else {}))
                    for p in punches if start<float(p['at'])<end]
    aud=q.get('audio')
    if isinstance(aud,dict) and isinstance(aud.get('sfx'),list):
        aud['sfx']=[dict(x,at=round(float(x['at'])-start,4)) for x in aud['sfx'] if start<=float(x['at'])<end]
    return q


def file_sha(path, chunk=1<<20):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(chunk),b''): h.update(b)
    return h.hexdigest()


def segment_key(seg_dir, render_fps, reelkit_path):
    """Fingerprint of the command and every input that decides this segment's
    pixels, so a stale one can never be silently resumed.

    Frame count alone cannot see a changed plan, a re-cut source, a different fps
    or an edited card library - all of which change the render while leaving the
    count identical. The pipeline scripts and the brand presets are in the key
    because build is a pure function of them: change cards.py and last week's
    segment is stale even though it still decodes perfectly."""
    h=hashlib.sha256()
    h.update(f'v1;fps={render_fps};quality=standard\n'.encode())
    scripts=Path(reelkit_path).resolve().parent
    for f in sorted(scripts.glob('*.py')): h.update(f.read_bytes())
    for f in sorted((scripts.parent/'assets'/'brand').glob('*.json')): h.update(f.read_bytes())
    seg=Path(seg_dir)
    for name in ('plan.json','transcript.json'):
        if (seg/name).exists(): h.update((seg/name).read_bytes())
    media=seg/'public'/'input-video.mp4'
    if media.exists(): h.update(file_sha(media).encode())
    return h.hexdigest()


def sidecar(out): return Path(str(out)+'.key.json')


def reusable(out, frames, key):
    """A segment may be resumed only when it decodes to the expected length AND
    was produced from exactly these inputs."""
    if not valid_video(out,frames): return False,'not a complete render'
    meta=sidecar(out)
    if not meta.exists(): return False,'no provenance sidecar - cannot prove what produced it'
    try: got=json.loads(meta.read_text()).get('key')
    except Exception: return False,'unreadable sidecar'
    if got!=key: return False,'inputs changed since it was rendered'
    return True,''


def counted(p): return Path(str(p)+'.count.json')


def decoded_frames(p):
    """Decoded frame count for a video, remembered across runs.

    Counting means decoding every frame: ~0.5s per segment locally, paid by the
    prepare check AND the resume check on every pass, for files that have not
    moved. The count is cached beside the file against its size and mtime, so a
    re-cut or re-rendered video re-derives and an untouched one does not.

    Deliberately NOT the .key.json sidecar: that file is provenance, written
    only after a successful render, and reusable() reads a missing key there as
    "cannot prove what produced it". Writing a count into it early would turn
    that precise refusal into the vaguer "inputs changed", so the two records
    stay separate - one says what produced the file, this one says how long it
    decodes.

    Returns None when the count cannot be taken; callers must treat that as
    "not safe to resume", never as zero.
    """
    try: st=p.stat()
    except OSError: return None
    meta=counted(p)
    try:
        c=json.loads(meta.read_text())
        if c.get('size')==st.st_size and c.get('mtime_ns')==st.st_mtime_ns:
            n=c.get('frames')
            if isinstance(n,int) and n>=0: return n
    except Exception: pass
    try: n=int(probe(str(p),'stream=nb_read_frames',count_frames=True).splitlines()[0])
    except Exception: return None
    try: meta.write_text(json.dumps({'size':st.st_size,'mtime_ns':st.st_mtime_ns,'frames':n},indent=1))
    except OSError: pass          # an unwritable cache just means counting again
    return n


def valid_video(p,frames=None):
    """Is this segment safe to resume from?

    Counts DECODED frames, not the header's nb_frames. A truncated MP4 keeps its
    moov atom (faststart writes it first) and still advertises the full count,
    while `ffmpeg -f null -` reports the decode errors and exits 0 anyway - so the
    old check resumed on a file with 2 real frames where 120 belonged and joined
    it into the deliverable.

    The count is cached against size and mtime, which is safe in the direction
    that matters: truncating a file changes its size and rewriting it changes
    its mtime, so a stale count cannot make a damaged segment look complete.
    """
    if not p.exists() or p.stat().st_size<10000:return False
    got=decoded_frames(p)
    if got is None:return False
    return got>0 if frames is None else abs(got-frames)<=1


def select_targets(segs, preview, n):
    """Which segments this run renders. A preview takes the leading ones; every
    other property - boundaries, output paths, expected frame counts - is
    identical to a full run, which is what lets the full pass resume them."""
    return segs[:max(1,min(n,len(segs)))] if preview else segs


def prepare(src, wd, plan, transcript, fps, bounds, i, st, en):
    """Materialise one segment subproject. Idempotent: an already-trimmed source
    with the right frame count is left alone, so preparing a subset first and the
    rest later costs nothing twice."""
    seg=wd/f'segment-{i:03d}'; pub=seg/'public'; pub.mkdir(parents=True,exist_ok=True)
    for name in ['fonts','images','sfx','vendor']:
        if (src/'public'/name).exists() and not (pub/name).exists(): shutil.copytree(src/'public'/name,pub/name)
    for name in ['ASSETS.md']:
        if (src/name).exists():shutil.copy2(src/name,seg/name)
    sp=shift_plan(plan,st,en); sp['meta']['trimTail'] = (i == len(bounds)-2 and plan.get('meta',{}).get('trimTail',True));json.dump(sp,open(seg/'plan.json','w'),ensure_ascii=False,indent=2)
    tw=[]
    for w in transcript:
        # Keep and clip boundary-crossing words rather than silently losing a caption.
        if float(w['end']) > st and float(w['start']) < en:
            v=dict(w);v['start']=round(max(0,float(w['start'])-st),4);v['end']=round(min(en-st,float(w['end'])-st),4)
            if v['end']>v['start']:tw.append(v)
    json.dump(tw,open(seg/'transcript.json','w'),ensure_ascii=False,indent=2)
    media=pub/'input-video.mp4'
    if not valid_video(media,round((en-st)*fps)):
        tmp=str(media)+'.tmp.mp4';run(['ffmpeg','-y','-v','error','-i',src/'public/input-video.mp4','-filter_complex',f'[0:v]trim=start={st}:end={en},setpts=PTS-STARTPTS,fps={fps}[v];[0:a]atrim=start={st}:end={en},asetpts=PTS-STARTPTS[a]','-map','[v]','-map','[a]','-c:v','libx264','-preset','veryfast','-crf','17','-g',fps,'-keyint_min',fps,'-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',tmp]);os.replace(tmp,media)


def main():
    a=argparse.ArgumentParser();a.add_argument('--project',required=True);a.add_argument('--out',required=True)
    a.add_argument('--work-dir',required=True);a.add_argument('--segment-seconds',type=float,default=12)
    a.add_argument('--workers',type=int,default=2)
    a.add_argument('--preview',action='store_true',
                   help='render only the leading segments, at full fidelity, into the same '
                        'segment files a full render uses - so the full pass resumes them')
    a.add_argument('--preview-segments',type=int,default=1,help='how many leading segments --preview covers')
    a.add_argument('--prepare-only',action='store_true');a.add_argument('--reelkit',default=str(Path(__file__).with_name('reelkit.py')))
    z=a.parse_args(); src=Path(z.project).resolve(); wd=Path(z.work_dir).resolve();wd.mkdir(parents=True,exist_ok=True)
    plan=json.load(open(src/'plan.json')); transcript=json.load(open(src/'transcript.json')); fps=int(plan.get('meta',{}).get('fps',30))
    duration=float(probe(str(src/'public/input-video.mp4'))); bounds=boundaries(plan,duration,z.segment_seconds)
    # Every segment is rendered at the authored fps and standard quality, preview
    # or not. A preview is a SUBSET of the full render's segments, never a
    # lower-fidelity version of all of them - that is what makes its output
    # reusable instead of something the full pass has to throw away and redo.
    segs=[{'id':i,'start':st,'end':en,'frames':round((en-st)*fps),
           'project':str(wd/f'segment-{i:03d}'),'output':str(wd/f'segment-{i:03d}.mp4')}
          for i,(st,en) in enumerate(zip(bounds,bounds[1:]))]
    targets=select_targets(segs,z.preview,z.preview_segments); n=len(targets)
    manifest={'version':3,'source':str(src),'fps':fps,'renderFps':fps,'fidelity':'full',
              'mode':'preview-subset' if z.preview else 'full','coveredSegments':n,
              'duration':duration,'boundaries':bounds,'segments':segs}
    for s in targets: prepare(src,wd,plan,transcript,fps,bounds,s['id'],s['start'],s['end'])
    json.dump(manifest,open(wd/'manifest.json','w'),indent=2)
    covered=round(targets[-1]['end']-targets[0]['start'],2) if targets else 0
    print(f"prepared {len(targets)} of {len(segs)} durable segments: {bounds}")
    if z.preview:
        print(f"preview: rendering segments 0-{n-1} ({covered}s of {round(duration,2)}s) at "
              f"{fps}fps standard - a full render over this work-dir resumes them")
    if z.prepare_only:return
    for s in targets:
        out=Path(s['output'])
        key=segment_key(s['project'],fps,z.reelkit)
        ok,why=reusable(out,s['frames'],key)
        if ok:print('resume: keeping',out);continue
        if out.exists():print(f'resume: re-rendering {out.name} - {why}')
        run(['python3',z.reelkit,'build','--project',s['project']])
        run(['python3',z.reelkit,'render','--project',s['project'],'--out',out,'--workers',z.workers])
        # Written only after a successful render, so an interrupted one leaves no
        # claim behind and the next run redoes it.
        sidecar(out).write_text(json.dumps({'key':key,'frames':s['frames'],'fps':fps,
                                            'segment':s['id']},indent=1))
    concat=wd/'concat.txt';concat.write_text(''.join("file '%s'\n"%s['output'].replace("'","'\\''") for s in targets))
    # Segment AAC carries encoder priming at every boundary. Discard it: join only
    # rendered video and mux the original staged audio once, preserving exact sync.
    video=wd/'joined-video.mp4';run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',concat,'-map','0:v:0','-an','-c','copy',video])
    raw=wd/'joined.mp4';run(['ffmpeg','-y','-v','error','-i',video,'-i',src/'public/input-video.mp4','-map','0:v:0','-map','1:a:0','-c','copy','-shortest',raw])
    run(['python3',z.reelkit,'export','--project',src,'--input',raw,'--out',Path(z.out).resolve()])

if __name__=='__main__':main()
