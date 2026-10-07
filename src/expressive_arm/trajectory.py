"""Validated, hardware-independent motion data operations."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from importlib.resources import files

JOINTS = ('shoulder_pan.pos','shoulder_lift.pos','elbow_flex.pos','wrist_flex.pos','wrist_roll.pos','gripper.pos')

def catalog():
    return json.loads(files('expressive_arm').joinpath('motions/catalog.json').read_text(encoding='utf-8'))

def find_expression(name):
    for item in catalog()['expressions']:
        if name in (item['id'],item['name']):return item
    raise ValueError(f'Unknown expression: {name}')

def pose(action):
    if not isinstance(action,dict) or set(action)!=set(JOINTS):raise ValueError('Expected exactly six joint keys')
    for name,value in action.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(f'Invalid numeric joint value: {name}')
    if not 0<=action['gripper.pos']<=100:raise ValueError('Gripper is percent, expected 0..100')
    return dict(action)

def validate_rows(rows):
    if len(rows)<2:raise ValueError('A motion needs at least two frames')
    previous=-math.inf
    for index,row in enumerate(rows):
        t=row.get('t')
        if isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or t<0 or t<=previous:
            raise ValueError(f'Invalid or non-increasing time at row {index}')
        pose(row.get('action'));previous=t
    return rows

def load(name):
    item=find_expression(name)
    raw=files('expressive_arm').joinpath('motions',item['file']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError(f'Checksum mismatch: {name}')
    rows=validate_rows([json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()])
    if len(rows)!=item['frames'] or abs(rows[-1]['t']-item['duration_s'])>1e-8:raise ValueError('Manifest does not match motion')
    return rows

def inspect(name):
    rows=load(name)
    return {'id':find_expression(name)['id'],'frames':len(rows),'duration_s':rows[-1]['t']-rows[0]['t'],
            'max_gap_s':max(b['t']-a['t'] for a,b in zip(rows,rows[1:])),
            'ranges':{key:[min(r['action'][key] for r in rows),max(r['action'][key] for r in rows)] for key in JOINTS}}

def crop(rows,start,end):
    validate_rows(rows)
    if not all(math.isfinite(t) for t in (start,end)) or start<0 or end<=start or end>rows[-1]['t']:
        raise ValueError('Expected 0 <= start < end <= motion duration')
    chosen=[r for r in rows if start<=r['t']<=end]
    if len(chosen)<2:raise ValueError('Selected interval contains fewer than two recorded frames')
    origin=chosen[0]['t']
    return [{**r,'frame':i,'t':r['t']-origin,'action':dict(r['action'])} for i,r in enumerate(chosen)]

def write_rows(rows,path):
    validate_rows(rows)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in rows),encoding='utf-8')

def plot(name,path):
    """Export all six channels as a self-contained SVG with explicit units."""
    from html import escape
    rows=load(name);duration=rows[-1]['t'];w,h=1100,800;left,right=200,1060
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
         '<rect width="100%" height="100%" fill="#F5F5F3"/>',
         f'<text x="40" y="45" font-family="sans-serif" font-size="23">{escape(find_expression(name)["name"])} / {escape(name)} — recorded targets</text>']
    for i,key in enumerate(JOINTS):
        vals=[r['action'][key] for r in rows];lo,hi=min(vals),max(vals);span=max(hi-lo,1);top=88+i*104
        svg.append(f'<text x="40" y="{top+20}" font-family="monospace" font-size="13">{escape(key)}</text>')
        unit='%' if key=='gripper.pos' else 'deg'
        svg.append(f'<text x="40" y="{top+42}" font-family="monospace" font-size="12" fill="#777">{lo:.1f}–{hi:.1f} {unit}</text>')
        svg.append(f'<path d="M{left} {top+70}H{right}" stroke="#C9C4BC" fill="none"/>')
        points=' '.join(f'{left+(r["t"]/duration)*(right-left):.2f},{top+65-(r["action"][key]-lo)/span*55:.2f}' for r in rows)
        svg.append(f'<polyline points="{points}" fill="none" stroke="#D71932" stroke-width="1.6"/>')
    svg.append(f'<text x="{left}" y="745" font-family="monospace" font-size="12">0 s</text><text x="{right-70}" y="745" font-family="monospace" font-size="12">{duration:.2f} s</text></svg>')
    Path(path).write_text('\n'.join(svg),encoding='utf-8')
