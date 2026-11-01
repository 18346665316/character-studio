"""Blender renderer adapter; shared input validation and delivery remain in studio_core."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from PIL import Image


def render(root, project, staging, job, view, render_size, godot):
    blender = os.environ.get('BLENDER_BIN','/Applications/Blender.app/Contents/MacOS/Blender')
    if not Path(blender).is_file() and shutil.which(blender) is None:
        raise ValueError('未找到 Blender，请安装或设置 BLENDER_BIN；也可选择 Godot 渲染')
    bridge = job/'blender-input'
    bridge.mkdir()
    frames = job/'blender-frames'
    frames.mkdir()
    shutil.copy2(root/'pipeline/blender/export.gd',project/'blender_export.gd')
    with (job/'blender-export.log').open('w') as log:
        subprocess.run([godot,'--headless','--path',str(project),'--script','blender_export.gd',
                        '--log-file',str(job/'blender-export-engine.log'),'--','--output',str(bridge)],
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
    if (project/'projection.json').is_file(): shutil.copy2(project/'projection.json',bridge/'projection.json')
    with (job/'blender-render.log').open('w') as log:
        subprocess.run([blender,'--background','--factory-startup','--python-exit-code','1',
                        '--python',str(root/'pipeline/blender/render.py'),'--','--input',str(bridge),
                        '--output',str(frames),'--view',view,'--frame-size',str(render_size)],
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200)
    assemble(bridge,frames,staging,render_size)


def assemble(bridge, frames, staging, size):
    clips=json.loads((bridge/'clips.json').read_text())
    if not clips: raise ValueError('Blender 未输出动画清单')
    for clip in clips:
        name=clip['name']
        if Path(name).name!=name or type(clip.get('frame_count')) is not int or clip['frame_count']<1:
            raise ValueError('Blender 动画清单无效')
        from sheet_layout import blank
        sheet,cols,rows=blank(size,clip['frame_count'])
        for i in range(clip['frame_count']):
            with Image.open(frames/f'{name}_{i:03d}.png') as frame:
                if frame.size!=(size,size): raise ValueError('Blender 帧尺寸不一致')
                sheet.paste(frame.convert('RGBA'),((i%cols)*size,(i//cols)*size))
        sheet.save(staging/f'{name}_spritesheet.png')
        timing=json.loads((frames/f'{name}_render.json').read_text())
        if timing.get('renderer')!='blender' or timing.get('frame_count')!=clip['frame_count'] or timing.get('duration_seconds')!=clip['duration_seconds']:
            raise ValueError('Blender 动画时序与输入不一致')
        timing.update(columns=cols,rows=rows)
        (staging/f'{name}_render.json').write_text(json.dumps(timing,indent=2)+'\n')
