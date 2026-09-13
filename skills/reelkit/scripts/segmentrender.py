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


def valid_video(p,frames=None):
    """Is this segment safe to resume from?

    Counts DECODED frames, not the header's nb_frames. A truncated MP4 keeps its
    moov atom (faststart writes it first) and still advertises the full count,
    while `ffmpeg -f null -` reports the decode errors and exits 0 anyway - so the
    old check resumed on a file with 2 real frames where 120 belonged and joined
    it into the deliverable."""
    if not p.exists() or p.stat().st_size<10000:return False
    try:
        got=int(probe(str(p),'stream=nb_read_frames',count_frames=True).splitlines()[0])
    except Exception:return False
    return got>0 if frames is None else abs(got-frames)<=1


def main():
    a=argparse.ArgumentParser();a.add_argument('--project',required=True);a.add_argument('--out',required=True)
    a.add_argument('--work-dir',required=True);a.add_argument('--segment-seconds',type=float,default=12)
    a.add_argument('--workers',type=int,default=2);a.add_argument('--preview',action='store_true')
    a.add_argument('--prepare-only',action='store_true');a.add_argument('--reelkit',default=str(Path(__file__).with_name('reelkit.py')))
    z=a.parse_args(); src=Path(z.project).resolve(); wd=Path(z.work_dir).resolve();wd.mkdir(parents=True,exist_ok=True)
    plan=json.load(open(src/'plan.json')); transcript=json.load(open(src/'transcript.json')); fps=int(plan.get('meta',{}).get('fps',30))
    duration=float(probe(str(src/'public/input-video.mp4'))); bounds=boundaries(plan,duration,z.segment_seconds)
    # A preview segment is 10fps draft and a full segment is authored fps at
    # standard quality. They are different artefacts, so they get different
    # paths: sharing one meant the resume check kept whatever was on disk and a
    # full render silently shipped the preview's draft frames.
    render_fps=min(fps,10) if z.preview else fps
    suffix='.preview' if z.preview else ''
    manifest={'version':2,'source':str(src),'fps':fps,'renderFps':render_fps,
              'fidelity':'preview' if z.preview else 'full','duration':duration,
              'boundaries':bounds,'segments':[]}
    for i,(st,en) in enumerate(zip(bounds,bounds[1:])):
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
        media=pub/'input-video.mp4'; expected=round((en-st)*render_fps)
        # The trimmed source is cut at the authored fps regardless of render
        # fidelity. Give the check that expectation too: without one it can only
        # ask "does anything decode", which a truncated clip still answers yes to.
        if not valid_video(media,round((en-st)*fps)):
            tmp=str(media)+'.tmp.mp4';run(['ffmpeg','-y','-v','error','-i',src/'public/input-video.mp4','-filter_complex',f'[0:v]trim=start={st}:end={en},setpts=PTS-STARTPTS,fps={fps}[v];[0:a]atrim=start={st}:end={en},asetpts=PTS-STARTPTS[a]','-map','[v]','-map','[a]','-c:v','libx264','-preset','veryfast','-crf','17','-g',fps,'-keyint_min',fps,'-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',tmp]);os.replace(tmp,media)
        manifest['segments'].append({'id':i,'start':st,'end':en,'frames':expected,'project':str(seg),'output':str(wd/f'segment-{i:03d}{suffix}.mp4')})
    json.dump(manifest,open(wd/'manifest.json','w'),indent=2)
    print('prepared',len(manifest['segments']),'durable segments:',bounds)
    if z.prepare_only:return
    for s in manifest['segments']:
        out=Path(s['output'])
        if valid_video(out,s['frames']):print('resume: keeping',out);continue
        run(['python3',z.reelkit,'build','--project',s['project']])
        cmd=['python3',z.reelkit,'render','--project',s['project'],'--out',out,'--workers',z.workers]
        if z.preview:cmd.append('--preview')
        run(cmd)
    concat=wd/'concat.txt';concat.write_text(''.join("file '%s'\n"%s['output'].replace("'","'\\''") for s in manifest['segments']))
    # Segment AAC carries encoder priming at every boundary. Discard it: join only
    # rendered video and mux the original staged audio once, preserving exact sync.
    video=wd/'joined-video.mp4';run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',concat,'-map','0:v:0','-an','-c','copy',video])
    raw=wd/'joined.mp4';run(['ffmpeg','-y','-v','error','-i',video,'-i',src/'public/input-video.mp4','-map','0:v:0','-map','1:a:0','-c','copy','-shortest',raw])
    run(['python3',z.reelkit,'export','--project',src,'--input',raw,'--out',Path(z.out).resolve()])

if __name__=='__main__':main()
