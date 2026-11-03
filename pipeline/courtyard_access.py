"""Build a covered passage from unchanged wall pixels and testable floor profiles."""
from io import BytesIO
from pathlib import Path
import json
import numpy as np
from PIL import Image
from asset_repository import read,atomic
from courtyard_expand import partition,placements,connection_ports
from wall_strip import validated_source


def floor_profile(image,anchor,gap=None,baselines=None):
    """Visible lower contour; conservative thin floor band, not image silhouette."""
    alpha=np.asarray(image)[:,:,3]>0
    profile=[];polygons=[];floor_columns=set()
    for x in range(image.width):
        ys=np.flatnonzero(alpha[:,x])
        if not len(ys):continue
        bottom=float(ys[-1])
        ground=min((s*x+k for s,k in baselines),key=lambda y:abs(y-bottom)) if baselines else bottom
        if abs(bottom-ground)<=8:floor_columns.add(x)
        profile.append([x-anchor[0],ground-anchor[1]])
    lookup=dict(profile)
    # Four-pixel strips also supply local foot sorting for long diagonal walls.
    slices=[]
    for x in range(0,image.width,4):
        cols=[i for i in range(x,min(x+4,image.width)) if i-anchor[0] in lookup]
        if not cols:continue
        bottom=float(np.median([lookup[i-anchor[0]] for i in cols]))
        slices.append(dict(x=x,width=min(4,image.width-x),foot_y=bottom))
    for x in range(0,image.width,32):
        cols=[i for i in range(x,min(x+32,image.width)) if i in floor_columns]
        if gap and x<gap[1] and x+32>gap[0]:continue
        if len(cols)<2:continue
        left=cols[0]-anchor[0];right=cols[-1]+1-anchor[0]
        yl=lookup[cols[0]-anchor[0]];yr=lookup[cols[-1]-anchor[0]]
        if abs(yl-yr)>32:continue
        polygons.append([[left,yl-5],[right,yr-5],[right,yr+3],[left,yl+3]])
    return polygons,slices


def build(root,folder,copies=(9,7)):
    from static_props import _publish_annotation,load_package
    import scene_modules as scenes
    from task_lock import task_lock
    root=Path(root);folder=Path(folder)
    if len(copies)!=2 or copies[0]<5 or any(type(n) is not int or not 1<=n<=20 for n in copies):
        raise ValueError('带门院墙至少需要5个A向墙段，重复数须为1–20整数')
    with task_lock(root):
        receipt=read(folder/'access-build.json',{})
        if receipt:
            if receipt.get('copies',list(copies))!=list(copies):raise ValueError('此任务已构建其他尺寸的院门验证场景')
            scenes.load(root,receipt['scene']);load_package(root,receipt['gate'])
            return receipt
        source,digest=validated_source(folder);checks=read(folder/'expansion-checks.json')
        parts=partition(source,checks['axes']);ids=read(folder/'expansion-published.json')
        lines={}
        for index in range(4,8):
            p=np.asarray(parts[index]['sprite']);yy,xx=np.nonzero(p[:,:,3]);slope=.5 if index<6 else -.5
            lines[index]=(slope,float(np.percentile(yy-slope*xx,99.5)))
        from zipfile import ZipFile
        versions=[]
        for index,part in enumerate(parts):
            manifest=load_package(root,ids[str(index)])
            with ZipFile(root/'prop-kits'/manifest['id']/'kit.zip') as z:files={n:z.read(n) for n in manifest['files_sha256']}
            adjacent={0:[4,6],1:[4,7],2:[5,7],3:[5,6]}.get(index,[index])
            polygons,slices=floor_profile(part['sprite'],part['foot'],baselines=[lines[i] for i in adjacent])
            manifest['occlusion_slices']=slices
            manifest['assembly_ports']=connection_ports(manifest['courtyard_part'],checks,digest)
            manifest['provenance']['parent_kit']=manifest['id']
            config=dict(title=manifest['title'],anchor=part['foot'],world_scale=1,behavior='blocking',polygons=polygons)
            versions.append(_publish_annotation(root,files,manifest,config)['id'])
        # Replace five contiguous front A-axis repeat modules with one passage.
        index=5;part=parts[index];length=checks['lengths'][0];span=5
        gate=Image.new('RGBA',(source.width+(span-1)*length,source.height+(span-1)*length//2))
        for i in range(span):gate.alpha_composite(part['sprite'],(i*length,i*length//2))
        pixels=np.asarray(gate).copy();yy,xx=np.indices(pixels.shape[:2]);ys,xs=np.nonzero(pixels[:,:,3])
        ground=float(np.percentile(ys-.5*xs,99.5))
        floor_x=xs[np.abs(ys-.5*xs-ground)<4]
        mid=(int(floor_x.min())+int(floor_x.max()))//2
        opening=[mid-46,mid+46];height=100
        removed=(xx>=opening[0])&(xx<opening[1])&(yy-.5*xx>ground-height)
        pixels[removed]=0;gate=Image.fromarray(pixels)
        # Sorting uses the original floor line even over the lintel, not the cutout roof edge.
        polygons,slices=floor_profile(gate,part['foot'],opening,baselines=[(.5,ground)])
        for strip in slices:
            if opening[0]<=strip['x']<opening[1]:strip['foot_y']=.5*(strip['x']+2)+ground-part['foot'][1]
        parent=load_package(root,ids[str(index)])
        with ZipFile(root/'prop-kits'/parent['id']/'kit.zip') as z:files={n:z.read(n) for n in parent['files_sha256']}
        stream=BytesIO();gate.save(stream,'PNG');files['sprite.png']=files['cutout.png']=stream.getvalue()
        ports=connection_ports(parent['courtyard_part'],checks,digest)
        for port in ports:
            if port['kind']=='end':port['point']=[port['point'][0]+(span-1)*length,port['point'][1]+(span-1)*length//2]
        parent.update(canvas_px=list(gate.size),assembly_ports=ports,occlusion_slices=slices)
        parent.pop('courtyard_part',None)
        parent['provenance']=dict(art_source='program_wall_passage',parent_kit=parent['id'],source_sha256=digest,
            method='repeat_source_wall_and_subtract_rectangular_doorway; no generated_frame_or_door_leaf')
        metadata=dict(opening_source_x=opening,ground_k=ground,clear_height=height,span=span,
            scope='covered open passage; inferred floor contour; test actor radius 8px')
        files['passage.json']=json.dumps(metadata).encode()
        gate_id=_publish_annotation(root,files,parent,dict(title='院墙 · 带瓦顶开放门洞',anchor=part['foot'],world_scale=1,behavior='opening',polygons=polygons))['id']
        scene=scenes.change(root,dict(action='create',title='四合院 · 院门通行与遮挡验证'))
        for identity in versions+[gate_id]:scene=scenes.change(root,dict(action='adopt',scene=scene['id'],revision=scene['revision'],kit=identity))
        layout=placements(parts,checks['lengths'],copies);instances=[]
        for v in layout:
            if v['part']==5:
                # Gate occupies the first five repeated spans of this wall.
                a=(v['shift'][0]+(copies[1]-1)*checks['lengths'][1])//length
                if 0<=a<span:
                    if a:continue
                    v=dict(v,part=8)
            foot=parts[5 if v['part']==8 else v['part']]['foot']
            instances.append(dict(id='access-'+str(len(instances)),module=scene['modules'][v['part']]['id'],position=[foot[d]-[512,300][d]+v['shift'][d] for d in range(2)]))
        gate_instance=next(v for v in instances if v['module']==scene['modules'][8]['id'])
        offset=[gate_instance['position'][d]-part['foot'][d] for d in range(2)]
        center=[mid+offset[0],mid*.5+ground+offset[1]]
        scene=scenes.change(root,dict(action='layout',scene=scene['id'],revision=scene['revision'],instances=instances,spawn=[center[0]-35,center[1]+70]))
        probes=[]
        for sign in (-1,1):probes.append(dict(label='door passage '+str(sign),start=[center[0]-sign*25,center[1]+sign*50],motion=[sign*50,-sign*100],blocked=False))
        for side,x in [('left',opening[0]-20),('right',opening[1]+20)]:
            p=[x+offset[0],x*.5+ground+offset[1]]
            probes.append(dict(label='door jamb '+side,start=[p[0]-25,p[1]+50],motion=[50,-100],blocked=True))
        receipt=dict(scene=scene['id'],gate=gate_id,wall_versions=versions,center=center,probes=probes,copies=list(copies),
            doorway=metadata,physics='pending',occlusion='pending')
        atomic(folder/'access-build.json',receipt)
        return receipt


def validate(root,folder,godot='/Applications/Godot.app/Contents/MacOS/Godot',visible=False):
    from io import BytesIO
    import subprocess,zipfile
    import scene_modules as scenes
    root=Path(root);folder=Path(folder).resolve();receipt=build(root,folder)
    if len(receipt['probes'])==4:
        scene=scenes.load(root,receipt['scene'])
        from static_props import load_package
        for index,module in enumerate(scene['modules'][:8]):
            config=load_package(root,module['source']['id'])['module_settings']
            instance=next(v for v in scene['instances'] if v['module']==module['id'])
            poly=config['polygons'][len(config['polygons'])//2]
            center=[sum(p[d] for p in poly)/4+instance['position'][d] for d in range(2)]
            dx=poly[1][0]-poly[0][0];dy=poly[1][1]-poly[0][1];norm=(dx*dx+dy*dy)**.5
            n=[-dy/norm,dx/norm]
            receipt['probes'].append(dict(label='wall/corner region '+str(index),
                start=[center[d]+n[d]*30 for d in range(2)],motion=[-n[d]*60 for d in range(2)],blocked=True))
        atomic(folder/'access-build.json',receipt)
    game=folder/'access-game';game.mkdir(exist_ok=True)
    with zipfile.ZipFile(BytesIO(scenes.export(root,receipt['scene']))) as z:z.extractall(game)
    commands=[['--headless','--editor','--import'],
        ([] if visible else ['--headless'])+['--script',str(root/'pipeline/tests/courtyard_access_integration.gd'),
          '--',str(folder/'access-build.json'),str(folder/'access-physics.json')]]
    for index,args in enumerate(commands):
        result=subprocess.run([godot,'--path',str(game)]+args,capture_output=True,text=True,timeout=60)
        (folder/('access-engine-'+str(index)+'.log')).write_text(result.stdout+result.stderr)
        if result.returncode or 'ERROR:' in result.stderr:raise ValueError('Godot院门测试失败：'+str(folder/'access-physics.json'))
    report=read(folder/'access-physics.json')
    if not report['passed']:raise ValueError('Godot院门通行测试未通过')
    receipt['physics']='passed radius-8 test actor passage and jamb probes'
    if visible:receipt['occlusion']=report.get('occlusion','pending')
    atomic(folder/'access-build.json',receipt)
    return receipt


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--validate',action='store_true')
    parser.add_argument('--visible',action='store_true')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    result=validate(root,args.folder,visible=args.visible) if args.validate else build(root,args.folder)
    print(json.dumps(result,ensure_ascii=False))
