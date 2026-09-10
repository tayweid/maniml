from pathlib import Path
from dataclasses import replace
import gzip, hashlib, json, shutil, struct
import numpy as np
from maniml.camera.camera import Camera
from maniml.mobject.geometry import Circle
from maniml.web.geometry import GeometryCache, parse_geometry_message
from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.triangle_scene import TriangleFrame, TriangleMeshCache, prepare_triangle_frame
from maniml.web.triangle_geometry import LyonFillTessellator
from tests.test_generated_geometry import painted_quad
from tests.renderer_fixtures import build_scene
root=Path('/private/tmp/maniml-border-browser-20260910')
root.mkdir(parents=True, exist_ok=True)
source=Path('maniml/web/static')
for name in ('webgpu.js','winding_webgpu.js','geometry_recording.js','player.js','player.html'):
    shutil.copyfile(source/name,root/name)
for name in ('wgsl','winding_wgsl'):
    shutil.copytree(source/name,root/name,dirs_exist_ok=True)
(root/'source_hashes.json').write_text(json.dumps({str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file() and (p.suffix=='.wgsl' or p.name in ('webgpu.js','geometry_recording.js','player.js'))},indent=2))
def pack(h,p):
    h=json.dumps(h).encode(); return b'\x03'+struct.pack('<I',len(h))+h+p
def label(message,name,version=None):
    h,p=parse_geometry_message(message);h['test_frame']=name
    if version: h['format_version']=version
    return pack(h,p)
def save(name,message):
    message=label(message,name);(root/(name+'.bin')).write_bytes(message);return message
camera=Camera(resolution=(320,180));camera.refresh_uniforms()
red,blue=painted_quad((1,0,0,1)),painted_quad((0,0,1,1))
wire=GeometryCache()
def paint(draws):
    return label(serialize_generated_frame(TriangleFrame((320,180),(0,0,0,1),4,draws,supersample=2),camera.uniforms,wire),'paint',4)
paint_frames=[save('paint-red',paint([red])),save('paint-red-cached',paint([red])),save('paint-blue',paint([blue])),save('paint-blue-cached',paint([blue])),save('paint-empty',paint([])),save('paint-return',paint([red]))]
h,p=parse_geometry_message(paint_frames[0]);info=next(iter(h.pop('paint_data').values()));h['format_version']=3;h['batches'][0].pop('paint_hash');h['batches'][0]['paint']=red.paint.tolist();save('paint-legacy3',pack(h,p[:info['offset']]))
shape=Circle(fill_opacity=.55,stroke_width=0,fill_border_width=12,fill_color='#00FF00')
scene=build_scene(shape,resolution=(320,180),samples=4,background=(0,0,0,1))
tess=LyonFillTessellator();mesh=TriangleMeshCache();wire=GeometryCache();border_frames=[]
def border(name,*,gpu=True,cache=wire):
    frame=prepare_triangle_frame(scene,tess,mesh_cache=mesh if gpu else None,fill_borders=True,gpu_borders=gpu)
    return save(name,serialize_generated_frame(replace(frame,supersample=2),scene.camera.uniforms,cache))
border_frames.append(border('border-green'))
border_frames.append(border('border-green-cached'))
shape.set_fill('#FF0000',opacity=.55)
border_frames.append(border('border-red'))
border_frames.append(border('border-red-cached'))
original=scene.render_groups;scene.render_groups=[];border_frames.append(border('border-empty'));scene.render_groups=original
border_frames.append(border('border-return'))
border('border-cpu-reference',gpu=False,cache=None)
scene.camera.frame.scale(.55)
border_frames.append(border('border-zoom'))
border('border-zoom-cpu-reference',gpu=False,cache=None)
(root/'frames.json').write_text(json.dumps({'paint':[parse_geometry_message(m)[0]['test_frame'] for m in paint_frames],'border':[parse_geometry_message(m)[0]['test_frame'] for m in border_frames]}))
player=root/'player';player.mkdir(exist_ok=True)
for name in ('webgpu.js','winding_webgpu.js','geometry_recording.js','player.js'):
    shutil.copyfile(root/name,player/name)
for name in ('wgsl','winding_wgsl'):shutil.copytree(root/name,player/name,dirs_exist_ok=True)
messages=[paint_frames[0],paint_frames[1],paint_frames[2],paint_frames[3],paint_frames[4],border_frames[0],border_frames[1],border_frames[2],border_frames[3],border_frames[4],border_frames[5],border_frames[6]]
segments=[-1,0,1,1,2,3,3,4,4,5,6,7]
(player/'scene.json').write_text(json.dumps({'format_version':5,'scene':'GPU border and retained paint QA','fps':12,'segments':8,'lines':list(range(1,9)),'frames':[{'len':len(m),'segment':s} for m,s in zip(messages,segments)]}))
(player/'scene.bin.gz').write_bytes(gzip.compress(b''.join(messages)))
print(root)
