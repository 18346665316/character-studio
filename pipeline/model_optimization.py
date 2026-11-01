"""Immutable Blender optimization experiments before Mixamo binding."""
from task_lock import serialized
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import zipfile
from PIL import Image, ImageDraw
import numpy as np


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(reference,candidate,size):
    a=reference.resize((size,size),Image.Resampling.LANCZOS)
    b=candidate.resize((size,size),Image.Resampling.LANCZOS)
    aa=np.asarray(a);bb=np.asarray(b);ma=aa[:,:,3]>127;mb=bb[:,:,3]>127
    union=ma|mb
    # Composite onto identical neutral background before measuring color.
    bg=Image.new('RGBA',(size,size),(235,238,232,255))
    ca=np.asarray(Image.alpha_composite(bg,a).convert('RGB')).astype(float)
    cb=np.asarray(Image.alpha_composite(bg,b).convert('RGB')).astype(float)
    return {'silhouette_iou':float((ma&mb).sum()/max(1,union.sum())),
            'rgb_mae':float(abs(ca-cb)[union].mean()) if union.any() else 0}


@serialized(lambda root, *args, **kwargs: root)
def optimize(root,character,prepared_id,source_fingerprint):
    root=Path(root);ws=root/'workspaces'/character
    source=ws/'models/prepared'/prepared_id
    if digest(source/'prepare.json')!=source_fingerprint:raise ValueError('模型来源已变化，请重新创建优化任务')
    info=json.loads((source/'prepare.json').read_text())
    destination=ws/'models/optimizations'/uuid.uuid4().hex[:12]
    destination.mkdir(parents=True)
    blender=os.environ.get('BLENDER_BIN','/Applications/Blender.app/Contents/MacOS/Blender')
    with (destination/'blender.log').open('w') as log:
        subprocess.run([blender,'--background','--factory-startup','--python-exit-code','1','--python',str(root/'pipeline/blender/optimize_model.py'),'--','--source',str(source/'preview.glb'),'--output',str(destination)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
    geometry=json.loads((destination/'geometry.json').read_text())
    with Image.open(destination/'original/view_0.png') as reference:
        pixels=np.asarray(reference.convert('RGBA'));visible=pixels[:,:,3]>127
        if not visible.any() or pixels[:,:,:3][visible].mean()<5:raise ValueError('对比渲染缺失颜色，拒绝发布候选')
    report={'schema':1,'source_prepared':prepared_id,'source_fingerprint':source_fingerprint,'source_sha256':info['source_sha256'],'variants':[],'animation_review':'not_tested','notes':'Static comparison only. Decimation is not retopology; face, hands and joint deformation require human review after a new binding.'}
    board=Image.new('RGB',(4*256, len(geometry['variants'])*300),(242,244,240));draw=ImageDraw.Draw(board)
    for row,variant in enumerate(geometry['variants']):
        key=variant['id'];folder=destination/key;metrics={}
        for col,angle in enumerate((0,90,180,270)):
            with Image.open(destination/'original'/f'view_{angle}.png') as a,Image.open(folder/f'view_{angle}.png') as b:
                for size in (64,128):metrics.setdefault(str(size),[]).append(compare(a.convert('RGBA'),b.convert('RGBA'),size))
                thumb=b.convert('RGBA').resize((256,256),Image.Resampling.LANCZOS);board.paste(thumb,(col*256,row*300+36),thumb)
        draw.text((12,row*300+10),f'{key}: {variant["triangles"]} triangles',fill=(35,55,42))
        if key!='original':
            shutil.copy2(source/'albedo.png',folder/'albedo.png')
            with zipfile.ZipFile(folder/'mixamo.zip','w',zipfile.ZIP_DEFLATED) as bundle:
                for name in ('model.obj','model.mtl','albedo.png'):bundle.write(folder/name,name)
            receipt={**info,'triangles_before':geometry['original_triangles'],'triangles_after':variant['triangles'],'optimization':{'method':'Blender Decimate Collapse','experiment':destination.name,'target':variant['target'],'parent_prepared':prepared_id},'visual_review':'pending','uv_coverage':None,'retained_component_faces':None,'cleanup':'Welded coincident UV seam vertices and reduced triangle count. No automatic retopology or joint-specific protection.'}
            (folder/'prepare.json').write_text(json.dumps(receipt,indent=2)+'\n')
            previews=folder/'previews';previews.mkdir();contact=Image.new('RGB',(1024,256),(242,244,240))
            for col,angle in enumerate((0,90,180,270)):
                with Image.open(folder/f'view_{angle}.png') as im:contact.paste(im.resize((256,256)),(col*256,0),im.resize((256,256)).getchannel('A'))
            contact.save(previews/'contact_sheet.png')
        report['variants'].append({**variant,'artifacts':{name:digest(folder/name) for name in ('model.obj','model.mtl','albedo.png','preview.glb','mixamo.zip','prepare.json')} if key!='original' else {},'metrics':{size:{'minimum_silhouette_iou':min(m['silhouette_iou'] for m in values),'mean_rgb_mae':sum(m['rgb_mae'] for m in values)/len(values)} for size,values in metrics.items()},'visual_review':'pending'})
    board.save(destination/'comparison.png')
    for size in (64,128):
        pixels=Image.new('RGB',(4*256,len(geometry['variants'])*(256+36)),(242,244,240));labels=ImageDraw.Draw(pixels)
        for row,variant in enumerate(geometry['variants']):
            labels.text((12,row*292+10),f'{variant["id"]}: {variant["triangles"]} triangles / {size}px',fill=(35,55,42))
            for col,angle in enumerate((0,90,180,270)):
                with Image.open(destination/variant['id']/f'view_{angle}.png') as im:
                    thumb=im.convert('RGBA').resize((size,size),Image.Resampling.LANCZOS).resize((256,256),Image.Resampling.NEAREST)
                    pixels.paste(thumb,(col*256,row*292+36),thumb)
        pixels.save(destination/f'comparison_{size}.png')
    (destination/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return destination


@serialized(lambda root, *args, **kwargs: root)
def activate(root,character,experiment,variant):
    root=Path(root);ws=root/'workspaces'/character
    folder=ws/'models/optimizations'/experiment
    report=json.loads((folder/'report.json').read_text())
    if digest(ws/'models'/f'{character}.obj')!=report['source_sha256']:raise ValueError('人物模型已变化，请重新优化当前模型')
    if variant not in [v['id'] for v in report['variants'] if v['id']!='original']:raise ValueError('未知优化版本')
    source=folder/variant
    parent=ws/'models/prepared'/report['source_prepared']
    if digest(parent/'prepare.json')!=report['source_fingerprint']:raise ValueError('优化来源已变化')
    metadata=next(v for v in report['variants'] if v['id']==variant)
    for name,sha in metadata.get('artifacts',{}).items():
        if digest(source/name)!=sha:raise ValueError('优化候选文件已变化，请重新生成')
    if not metadata.get('artifacts'):raise ValueError('候选缺少完整性记录，请重新生成')
    # Publish via rename; never let a partial upload package become current.
    target=ws/'models/prepared'/uuid.uuid4().hex[:12];staging=target.with_name('.'+target.name)
    shutil.copytree(source,staging)
    for name in ('prepare.json','mixamo.zip'):os.utime(staging/name,None)
    staging.rename(target)
    return target
