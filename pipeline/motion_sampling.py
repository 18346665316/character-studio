"""Diagnostic temporal sampling analysis; production frame settings stay unchanged.

Compare sample-and-hold trajectories against a 30 FPS reference in target pixels.
Bone origins, orientation probes and equipped weapon bounds are proxies, not a
substitute for rendered silhouette/texture inspection.
"""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import numpy as np

CANDIDATES=(12,15,20,24,30)
POLICY={'p95_extra_pixels':.75,'peak_extra_pixels':2.5,'reference_fps':30}


def analyze(probe,frame_size,camera_size,view='three_quarter'):
    if frame_size not in (64,128) or not math.isfinite(camera_size) or camera_size<=0 or view not in ('front','side','three_quarter'):
        raise ValueError('Invalid target projection')
    times=np.asarray(probe['times'],dtype=float)
    xyz=np.asarray([[[math.nan]*3 if point is None else point for point in frame] for frame in probe['positions']],dtype=float)
    duration=float(probe['duration'])
    if not math.isfinite(duration) or duration<=0 or times.ndim!=1 or len(times)<2 or xyz.ndim!=3 or xyz.shape[0]!=len(times) or xyz.shape[2]!=3 or not np.isfinite(times).all() or np.any(np.diff(times)<=0) or abs(times[0])>1e-6 or abs(times[-1]-duration)>1e-5:
        raise ValueError('Invalid motion probe or incomplete duration')
    bone_markers=len(probe.get('bone_names',[]))*4
    weapon_markers=probe.get('weapon_marker_count',0)
    if bone_markers<4 or type(weapon_markers) is not int or weapon_markers<0 or xyz.shape[1]!=bone_markers+weapon_markers:
        raise ValueError('Motion probe landmark layout is invalid')
    if not np.isfinite(xyz[:,:bone_markers]).all() or np.any(np.isinf(xyz)) or np.any(np.isnan(xyz).any(axis=2)!=np.isnan(xyz).all(axis=2)):
        raise ValueError('Motion probe contains missing bones or partial markers')
    if np.any(np.isinf(xyz)) or not np.isfinite(xyz).any() or np.any(~np.isfinite(xyz).any(axis=(1,2))):
        raise ValueError('Motion probe contains invalid geometry')
    angle={'front':0,'side':math.pi/2,'three_quarter':math.pi/4}[view]
    points=np.stack((xyz[:,:,0]*math.cos(angle)-xyz[:,:,2]*math.sin(angle),xyz[:,:,1]),axis=-1)*frame_size/camera_size
    # Exact endpoint belongs to loop inspection, not to the held final display frame.
    check_times=times[:-1];truth=points[:-1]
    def held(fps):
        count=max(8,math.ceil(duration*fps-1e-5))
        indices=np.minimum(np.floor(check_times*count/duration+1e-8),count-1)
        sample_times=indices*duration/count
        # Probe at 120 Hz; interpolate each landmark to exact candidate sample times.
        sampled=np.empty_like(truth)
        for marker in range(points.shape[1]):
            for axis in range(2):sampled[:,marker,axis]=np.interp(sample_times,times,points[:,marker,axis])
        return count,np.linalg.norm(sampled-truth,axis=2)
    reference_count,reference_error=held(30)
    rows=[]
    for fps in CANDIDATES:
        count,error=held(fps)
        extra=np.maximum(0,error-reference_error)
        # Maximum across markers per probe time protects a brief hand/weapon peak
        # from being averaged away by many quiet torso bones.
        per_time=np.nanmax(extra,axis=1)
        worst=int(np.argmax(per_time));marker=int(np.nanargmax(extra[worst]))
        bone_count=len(probe.get('bone_names',[]))*4
        label=probe['bone_names'][marker//4] if marker<bone_count else 'weapon_bounds'
        p95=float(np.percentile(per_time,95));peak=float(per_time[worst])
        rows.append({'target_fps':fps,'frame_count':count,'effective_fps':count/duration,'p95_extra_pixels':round(p95,4),'peak_extra_pixels':round(peak,4),'peak_time':round(float(check_times[worst]),4),'peak_marker':label,'passes':p95<=POLICY['p95_extra_pixels'] and peak<=POLICY['peak_extra_pixels']})
    winner=next(row for row in rows if row['passes'])
    seam=np.linalg.norm(points[-1]-points[0],axis=1)
    seam_max=float(np.nanmax(seam))
    return {'duration_seconds':duration,'frame_size':frame_size,'view':view,'camera_size':camera_size,'reference_frame_count':reference_count,'probe_hz':probe['probe_hz'],'weapon_markers':probe.get('weapon_marker_count',0),'policy':POLICY,'recommended':winner,'candidates':rows,'loop_endpoint_max_pixels':round(seam_max,4),'loop_requires_review':seam_max>2.5,'scope':'motion-proxy diagnostic; no automatic production change; endpoint test does not prove seamless loop'}


def run(root,character,files,equipment_id=None):
    from asset_repository import AssetRepository,read,atomic
    from studio_core import new_batch,GODOT
    from mixamo_state import require_ready
    from equipment import load,copy_runtime,stage_model
    from equipment_usage import load as usage_load,recipe,fingerprint
    assets=AssetRepository(root);c=assets.character(character)
    binding=require_ready(character)
    batch_by_id={b['id']:b for b in c['batches'] if b['current_rig']}
    sources={};hashes={}
    for value in files:
        parts=value.split('/')
        if len(parts)!=2 or parts[0] not in batch_by_id or parts[1] not in batch_by_id[parts[0]]['files']:
            raise ValueError('Probe sources must be reviewed current-rig batch/file references')
        b=batch_by_id[parts[0]]
        if not (c['approvals'].get('motions',{}).get(b['id'],{}).get('fingerprint')==b['fingerprint'] or c['approvals'].get('animations',{}).get(b['id'],{}).get(parts[1],{}).get('fingerprint')==b['fingerprint']):
            raise ValueError('Please approve the source animation before quality analysis')
        path=assets.scoped(f'workspaces/{character}/animations/{value}',f'workspaces/{character}/animations')
        sha=assets.digest(path)
        if sha!=b['hashes'][parts[1]]:raise ValueError('Source animation changed')
        if path.stem in sources:raise ValueError('Diagnostic clip names must be unique')
        sources[path.stem]=path;hashes[path.name]=sha
    job=assets.root/'.local/quality'/('sampling-'+new_batch());project=job/'godot'
    shutil.copytree(assets.root/'pipeline/godot',project,ignore=shutil.ignore_patterns('.godot'))
    (project/'animations').mkdir()
    for path in sources.values():shutil.copy2(path,project/'animations'/path.name)
    equipment_pin=None
    if equipment_id:
        config=load(assets.root,character,None,equipment_id)
        if config['rig_sha256']!=binding['bound_sha256']:raise ValueError('Equipment rig mismatch')
        copy_runtime(assets.root,project);stage_model(config,assets.root/'workspaces'/character/'equipment'/equipment_id/'weapon.glb',project)
        atomic(project/'equipment.json',config)
        usage=usage_load(assets.root,character,equipment_id);equipment_pin=fingerprint(usage)
        atomic(project/'equipment_usage.json',recipe(usage,hashes))
    from animation_import import prepare as prepare_animation_import
    prepare_animation_import(project)
    with (job/'analysis.log').open('w') as log:
        for args in ([GODOT,'--headless','--editor','--path',str(project),'--import'],[GODOT,'--headless','--path',str(project),'--script','res://sample_motion.gd','--',str(job/'probe.json')]):
            subprocess.run(args[:1]+['--log-file',str(job/('probe-engine.log' if '--script' in args else 'import-engine.log'))]+args[1:],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
    probes=read(job/'probe.json');reports={}
    if not isinstance(probes,dict) or set(probes)!=set(sources):
        raise ValueError(f'Godot 未生成完整运动探测结果，请检查 {job / "analysis.log"}')
    for key,probe in probes.items():
        # Use actual previous camera projection where available, not silhouette height.
        previous=next((item['info'] for d in c['deliveries'] for item in d['clips'] if item['name']==key and item['info'].get('camera',{}).get('size',0)>0),None)
        if previous:
            camera_size=previous['camera']['size'];view=previous['view'];projection='existing_render_camera'
        else:
            xyz=np.asarray([[[math.nan]*3 if point is None else point for point in frame] for frame in probe['positions']],dtype=float);right=(xyz[:,:,0]-xyz[:,:,2])/math.sqrt(2)
            camera_size=1.12*max(float(np.nanmax(right)-np.nanmin(right)),float(np.nanmax(xyz[:,:,1])-np.nanmin(xyz[:,:,1])))
            view='three_quarter';projection='estimated_landmark_bounds'
        reports[key]={str(size):{**analyze(probe,size,camera_size,view),'projection_source':projection} for size in (64,128)}
    if require_ready(character)['bound_sha256']!=binding['bound_sha256'] or any(assets.digest(path)!=hashes[path.name] for path in sources.values()):
        raise ValueError('分析期间绑定或源动作已变化，请重新分析')
    result={'schema':1,'character':character,'rig_sha256':binding['bound_sha256'],'sources':{k:{'path':str(p.relative_to(assets.root)),'sha256':hashes[p.name]} for k,p in sources.items()},'equipment_id':equipment_id,'equipment_usage_sha256':equipment_pin,'reports':reports,'status':'diagnostic_only'}
    atomic(job/'report.json',result)
    lines=['# 自动采样诊断','', '仅分析，不改变生产采样设置。以 30 FPS 为参考，120 Hz 探测骨骼、朝向探针与实际装备包围盒轨迹。阈值为待校准策略；不等同于最终轮廓与贴图质量验收。','', '| 动作 | 尺寸 | 时长 | 建议 FPS | 帧数 | 95%额外误差(px) | 峰值额外误差(px) | 循环端点差(px) |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for key,sizes in reports.items():
        for size,r in sizes.items():
            w=r['recommended'];lines.append(f'| {key} | {size} | {r["duration_seconds"]:.2f}s | {w["target_fps"]} | {w["frame_count"]} | {w["p95_extra_pixels"]:.2f} | {w["peak_extra_pixels"]:.2f} | {r["loop_endpoint_max_pixels"]:.2f} |')
    (job/'report.md').write_text('\n'.join(lines)+'\n')
    print(job,flush=True)
    return job


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Diagnose temporal sampling without changing production outputs')
    parser.add_argument('--character',required=True);parser.add_argument('--source',action='append',required=True,help='batch/file.fbx');parser.add_argument('--equipment')
    args=parser.parse_args();run(Path(__file__).resolve().parent.parent,args.character,args.source,args.equipment)
