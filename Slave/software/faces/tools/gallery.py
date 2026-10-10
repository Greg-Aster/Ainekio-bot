#!/usr/bin/env python3
"""Render the firmware's actual C face renderer as an offline animated gallery.

Requires Pillow and the native face_preview executable. No separate artwork or
browser approximation: all displayed pixels originate in the firmware renderer.
"""
import argparse
import html
import io
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--renderer',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--dashboard',action='store_true',help='Write the Body Control catalog and previews only')
args=parser.parse_args()
args.out.mkdir(parents=True,exist_ok=True)
catalog=[]
for line in subprocess.check_output([args.renderer,'--list'],text=True).splitlines():
    name,period=line.split();period=int(period)
    images=[]
    # Match the firmware's 15 fps integer-millisecond display interval.
    step=1000//15
    times=range(0,period,step)
    for t in times:
        data=subprocess.check_output([args.renderer,name,str(t)])
        images.append(Image.open(io.BytesIO(data)).convert('RGB'))
    # Preserve the exact expression period through the final partial interval.
    durations=[min(step,period-t) for t in times]
    images[0].save(args.out/(name+'.webp'),save_all=True,append_images=images[1:],duration=durations,loop=0,lossless=True)
    images[0].save(args.out/(name+'.png'))
    emotions={'default','idle','stand','neutral','idle_blink','happy','sad','angry',
              'surprised','sleepy','love','excited','confused','thinking','bored','listening','curious'}
    group='Speaking' if name.startswith('talk_') else 'Expressions' if name in emotions else 'Motion faces'
    catalog.append(dict(name=name,label=name.replace('_',' ').capitalize(),group=group,period_ms=period))
(args.out/'catalog.json').write_text(json.dumps(catalog,indent=2)+'\n')
if args.dashboard:
    print(f'Rendered {len(catalog)} selectable expressions: {args.out}')
    raise SystemExit(0)
cards=''.join(f'<button class="face" data-name="{item["name"]}"><img loading="lazy" src="{item["name"]}.png" alt=""><span>{html.escape(item["name"].replace("_"," "))}</span></button>' for item in catalog)
page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ainekio · Faces</title><style>
:root{color-scheme:dark;font:16px system-ui;background:#0b1014;color:#eaf2f7}*{box-sizing:border-box}body{max-width:1160px;margin:auto;padding:32px 20px}header{margin-bottom:24px}h1{font-size:32px;letter-spacing:-1px;margin:0 0 8px}p{color:#9baebc;line-height:1.6}main{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(260px,1fr);gap:24px}.viewer{position:sticky;top:24px;align-self:start;background:#111b22;border:1px solid #243642;border-radius:18px;padding:18px}.screen{background:#000;border-radius:12px;overflow:hidden;aspect-ratio:320/170;display:grid;place-items:center}.screen img{width:100%;height:auto}.details{display:flex;justify-content:space-between;align-items:center;gap:8px}.details h2{text-transform:capitalize;font-size:20px}.catalog{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.face{font:inherit;color:inherit;cursor:pointer;border:1px solid #263640;border-radius:10px;background:#111a20;padding:8px;text-align:left}.face[aria-pressed=true]{border-color:#27dfff;background:#112c36}.face:hover{border-color:#66c8dd}.face img{width:100%;display:block;border-radius:5px}.face span{display:block;margin:8px 2px 2px;font-size:13px;text-transform:capitalize}input{width:100%;background:#13212a;border:1px solid #314653;border-radius:8px;padding:12px;color:inherit;font:inherit;margin-bottom:14px}button.control{background:#153541;border:1px solid #286071;border-radius:8px;padding:9px 13px;color:#d3f9ff;font:inherit;cursor:pointer}code{color:#55dfff}small{color:#9baebc}footer{margin-top:28px;color:#8298a7;font-size:13px}@media(max-width:700px){main{grid-template-columns:1fr}.viewer{position:relative;top:0}body{padding:20px 14px}}
</style><header><h1>Ainekio expressions</h1><p>Cyan light, curved brackets and expressive symbols. Select a face to see its animation.</p></header>
<main><section class="viewer"><div class="screen"><img id="display" src="default.webp" alt="Resting face with cyan pupils and curved outer lights"></div><div class="details"><h2 id="name">Default</h2><button class="control" id="pause">Pause</button></div><p>Body Control → Face or sound asset → enter <code id="command">default</code> → Face.</p><small>320 × 170 pixels · RGB565 · preview of the firmware renderer</small></section><section><input type="search" id="filter" aria-label="Find an expression" placeholder="Find an expression…"><div class="catalog">CARDS</div></section></main><footer>Visual preview only. Selecting a face here does not send a command to the robot.</footer>
<script>let selected='default',paused=false;const display=document.querySelector('#display');function refresh(){display.src=selected+(paused?'.png':'.webp');display.alt=selected.replaceAll('_',' ')+' expression';document.querySelector('#pause').textContent=paused?'Play':'Pause';}for(const button of document.querySelectorAll('.face')){button.setAttribute('aria-pressed',button.dataset.name===selected);button.addEventListener('click',()=>{selected=button.dataset.name;document.querySelector('#name').textContent=selected.replaceAll('_',' ');document.querySelector('#command').textContent=selected;for(const b of document.querySelectorAll('.face'))b.setAttribute('aria-pressed',b===button);refresh();});}document.querySelector('#pause').onclick=()=>{paused=!paused;refresh();};document.querySelector('#filter').oninput=e=>{for(const b of document.querySelectorAll('.face'))b.hidden=!b.dataset.name.replaceAll('_',' ').includes(e.target.value.toLowerCase());};</script></html>'''
(args.out/'index.html').write_text(page.replace('CARDS',cards))
featured=['default','happy','sad','angry','surprised','sleepy','love','excited','confused','thinking','wave','run','crawl','dance','dead','curious']
sheet=Image.new('RGB',(4*340,4*210+80),'#0b1014');draw=ImageDraw.Draw(sheet)
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',18)
draw.text((20,22),'AINEKIO / WIDE LCD EXPRESSIONS',font=font,fill='#eaf2f7')
for i,name in enumerate(featured):
    x=(i%4)*340+10;y=(i//4)*210+70
    sheet.paste(Image.open(args.out/(name+'.png')),(x,y))
    draw.text((x+8,y+176),name.replace('_',' '),font=font,fill='#a8c2d0')
sheet.save(args.out/'contact-sheet.png')
print(f'Rendered {len(catalog)} expressions: {args.out}/index.html')
