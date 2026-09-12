#!/usr/bin/env python3
"""Acceptance gate: prove a parallel Reelkit render matches its sequential baseline."""
import argparse, hashlib, json, math, os, subprocess, sys, tempfile


def run(cmd, check=True):
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def probe(path):
    r=run(["ffprobe","-v","error","-count_frames","-show_streams","-show_format","-of","json",path])
    x=json.loads(r.stdout); v=next(s for s in x["streams"] if s["codec_type"]=="video")
    return {"duration":float(x["format"]["duration"]),"frames":int(v.get("nb_read_frames") or v["nb_frames"]),
            "fps":v["r_frame_rate"],"width":v["width"],"height":v["height"]}


def audio_hash(path):
    p=subprocess.Popen(["ffmpeg","-v","error","-i",path,"-map","0:a:0","-f","s16le","-acodec","pcm_s16le","-"],stdout=subprocess.PIPE)
    h=hashlib.sha256()
    for chunk in iter(lambda:p.stdout.read(1024*1024),b""): h.update(chunk)
    if p.wait(): raise RuntimeError("audio decode failed")
    return h.hexdigest()


def exact_frame_hash(path, frames, work):
    out={}
    for f in sorted(set(frames)):
        dst=os.path.join(work,f"{f:08d}.rgba")
        run(["ffmpeg","-v","error","-i",path,"-vf",f"select=eq(n\\,{f})","-vsync","0","-frames:v","1","-f","rawvideo","-pix_fmt","rgba",dst])
        out[f]=hashlib.sha256(open(dst,"rb").read()).hexdigest()
    return out


def metrics(a,b,work):
    log=os.path.join(work,"metrics.log")
    r=run(["ffmpeg","-v","info","-i",a,"-i",b,"-lavfi",
           f"[0:v][1:v]ssim=stats_file={work}/ssim.log;[0:v][1:v]psnr=stats_file={work}/psnr.log",
           "-f","null","-"],check=False)
    open(log,"w").write(r.stderr)
    sm=[]; pm=[]
    for line in open(os.path.join(work,"ssim.log")): sm.append(float(line.split("All:")[1].split()[0]))
    for line in open(os.path.join(work,"psnr.log")):
        val=line.split("psnr_avg:")[1].split()[0]; pm.append(float("inf") if val=="inf" else float(val))
    return min(sm),min(pm)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("sequential"); ap.add_argument("parallel")
    ap.add_argument("--workers",type=int,required=True); ap.add_argument("--project")
    a=ap.parse_args(); sa,sb=probe(a.sequential),probe(a.parallel)
    structural=(sa==sb)
    boundaries=[i*sa["frames"]//a.workers for i in range(1,a.workers)]
    sample=[0,sa["frames"]-1]+[round(i*(sa["frames"]-1)/17) for i in range(18)]
    sample += [x+d for x in boundaries for d in (-1,0,1) if 0<=x+d<sa["frames"]]
    with tempfile.TemporaryDirectory() as w:
        ah,bh=audio_hash(a.sequential),audio_hash(a.parallel)
        adir, bdir = os.path.join(w, "a"), os.path.join(w, "b")
        os.mkdir(adir); os.mkdir(bdir)
        ha=exact_frame_hash(a.sequential,sample,adir)
        hb=exact_frame_hash(a.parallel,sample,bdir)
        ssim,psnr=metrics(a.sequential,a.parallel,w)
    exact=ha==hb; audio=ah==bh
    verify=True
    if a.project:
        verify=run([sys.executable,os.path.join(os.path.dirname(__file__),"reelkit.py"),"verify","--project",a.project,"--json"],check=False).returncode==0
    result={"structural_equal":structural,"sequential":sa,"parallel":sb,"min_ssim":ssim,"min_psnr_db":psnr,
            "exact_sample_frames":sorted(sample),"exact_bitmap_hashes":exact,"audio_hash_equal":audio,"verify_passed":verify}
    print(json.dumps(result,indent=2))
    ok=structural and ssim>=.999 and psnr>=50 and exact and audio and verify
    return 0 if ok else 1
if __name__=="__main__": sys.exit(main())
