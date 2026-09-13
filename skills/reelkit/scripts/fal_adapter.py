#!/usr/bin/env python3
"""Minimal fal.ai adapter. Secret comes only from FAL_KEY at process runtime."""
import argparse,json,os,time,urllib.request
from pathlib import Path

def request(url,data,key):
 q=urllib.request.Request(url,data=json.dumps(data).encode(),headers={'Authorization':'Key '+key,'Content-Type':'application/json'})
 with urllib.request.urlopen(q,timeout=90) as r:return json.load(r)
def get(url,key):
 q=urllib.request.Request(url,headers={'Authorization':'Key '+key})
 with urllib.request.urlopen(q,timeout=90) as r:return json.load(r)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--prompt',required=True);ap.add_argument('--out',required=True);ap.add_argument('--width',type=int,required=True);ap.add_argument('--height',type=int,required=True);ap.add_argument('--model',required=True);a=ap.parse_args()
 key=os.getenv('FAL_KEY');
 if not key: raise SystemExit('FAL_KEY is required (runtime secret; never store it in project files)')
 aspect='landscape_4_3' if a.width>a.height else ('portrait_4_3' if a.height>a.width else 'square_hd')
 body={'prompt':a.prompt,'image_size':aspect,'num_images':1,'enable_safety_checker':True}
 first=request('https://queue.fal.run/'+a.model,body,key)
 result=first
 if first.get('request_id'):
  status=first.get('status_url'); response=first.get('response_url')
  while status:
   st=get(status,key)
   if st.get('status')=='COMPLETED':break
   if st.get('status') in ('FAILED','CANCELLED'):raise SystemExit('fal generation '+st.get('status','failed'))
   time.sleep(1.5)
  result=get(response,key)
 images=result.get('images') or result.get('data',{}).get('images') or []
 if not images: raise SystemExit('fal returned no image')
 url=images[0].get('url'); Path(a.out).parent.mkdir(parents=True,exist_ok=True)
 urllib.request.urlretrieve(url,a.out)
 print(json.dumps({'model':a.model,'output':a.out,'request_id':first.get('request_id')}))
if __name__=='__main__':main()
