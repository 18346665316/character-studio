"""Render diagnostic comparisons in .local/quality; never publish production assets.
The local baker copy uses requested counts and tiled diagnostic PNGs. Production
baker, frame limits and delivery format are deliberately not changed here.
"""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import numpy as np
from PIL import Image,ImageDraw
from motion_sampling import analyze


def raster_error(reference,candidate):
    a=np.asarray(reference,dtype=float)/255;b=np.asarray(candidate,dtype=float)/255
    union=(a[:,:,3]>.5)|(b[:,:,3]>.5)
    if not union.any():raise ValueError('Empty diagnostic comparison')
    silhouette=float(np.count_nonzero((a[:,:,3]>.5)^(b[:,:,3]>.5))/np.count_nonzero(union))
    color=float(np.abs(a[:,:,:3]*a[:,:,3:4]-b[:,:,:3]*b[:,:,3:4])[union].mean())
    return silhouette,color


def write_comparison(sheets,counts,duration,selected,directory):
    reference,candidate=counts;legacy=max(8,math.ceil(duration*12-1e-5))
    frames=[];measurements={'legacy_12_reconstructed':[],'auto':[]}
    tiles=[[sheet.crop((i*128,0,(i+1)*128,128)) for i in range(count)] for sheet,count in zip(sheets,counts)]
    for i in range(reference):
        low_index=min(reference-1,round(math.floor(i*legacy/reference)*reference/legacy))
        chosen=min(candidate-1,int(i*candidate/reference))
        images=[tiles[0][i],tiles[0][low_index],tiles[1][chosen]]
        for name,tile in zip(measurements,images[1:]):measurements[name].append(raster_error(images[0],tile))
        frame=Image.new('RGB',(1152,430),'#eef1eb');draw=ImageDraw.Draw(frame)
        for col,(tile,label) in enumerate(zip(images,['30 FPS reference','12 FPS approx (from 30)',f'Auto {selected} FPS'])):
            tile=tile.resize((384,384),Image.Resampling.NEAREST)
            frame.paste(tile,(col*384,38),tile);draw.text((col*384+12,12),label,fill='#283831')
        frames.append(frame)
    ticks=duration*100/reference
    delays=[max(10,(round((i+1)*ticks)-round(i*ticks))*10) for i in range(reference)]
    frames[0].save(directory/'comparison.gif',save_all=True,append_images=frames[1:],duration=delays,loop=0)
    worst=int(np.argmax([value[0] for value in measurements['legacy_12_reconstructed']]))
    frames[worst].save(directory/'peak-comparison.png')
    return {name:{'silhouette_xor_p95':float(np.percentile(np.asarray(values)[:,0],95)),
                  'silhouette_xor_peak':float(np.max(np.asarray(values)[:,0])),
                  'premultiplied_color_error_p95':float(np.percentile(np.asarray(values)[:,1],95))} for name,values in measurements.items()}


def write_review(job,report,outputs):
    lines=['# 自动采样质量审查','', '本轮是诊断实验，未修改生产默认帧率或替换已有图集。已检查原动作来源和绑定；建议由真实运动轨迹产生，不读取动作名称分类。','', '## 规则与限制','', '按 120 Hz 探测骨骼位置、朝向探针及实际武器包围盒，在目标画布下比较 12 / 15 / 20 / 24 / 30 FPS 的保持帧误差。以 30 FPS 为参考，选择额外误差 95 分位不超过 0.75px、峰值不超过 2.5px 的最低档。保留完整时长，分析阶段不受 120 帧上限约束。阈值仍需更多人物、视角和动作校准。','', '轨迹指标是代理：不能覆盖衣服、头发、贴图和所有像素描边变化。循环端点检测只提示需要复核，端点相同也不保证循环速度连续。','', '## 实际结果（128px）','', '| 动作 | 时长 | 自动建议 | 输出帧数 | 低采样近似的轮廓差异 P95 | 自动方案轮廓差异 P95 |','|---|---:|---:|---:|---:|---:|']
    for key,r in outputs.items():
        legacy=r['raster_metrics']['legacy_12_reconstructed']['silhouette_xor_p95'];auto=r['raster_metrics']['auto']['silhouette_xor_p95']
        lines.append(f'| {key} | {r["duration_seconds"]:.2f}s | {r["recommended_fps"]} FPS | {r["candidate_count"]} | {legacy:.1%} | {auto:.1%} |')
    lines+=['', '轮廓差异为同一时刻两幅前景掩码的异或面积 / 并集面积，不是主观质量分数。30 FPS 被选为自动方案时，差异为零是与参考相同的必然结果。','', '## 并排动画','', '每组按同一时钟播放，使用相同相机、分辨率、装备、调色板和像素后处理。左：30 FPS 实际渲染；中：从该参考抽取的低采样近似（不是旧生产图集）；右：按自动建议独立渲染。为避免不同时钟和取景干扰，本次没有拿历史 GIF 直接对比。短跑步动作受到原先至少 8 帧规则影响，中列有效帧率约 15 FPS。']
    for key,r in outputs.items():
        lines+=['',f'### {key}','',f'![{key}]({job / r["comparison"]})','',f'[峰值差异帧]({job / r["peak_comparison"]})']
    lines+=['','## 接入默认流程前的门槛','', '继续用不同武器、尺寸和动作检查阈值；将超过 120 帧的生产图集改为多行或分页；随后让两个渲染后端共同读取采样计划，并保留渲染后的轮廓与循环复核。此次仅完成分析和对照实验。']
    (job/'review.md').write_text('\n'.join(lines)+'\n')


def compare(job):
    from panel import atomic
    from pixel_finish import finish_batch
    from studio_core import GODOT
    report=json.loads((job/'report.json').read_text());probes=json.loads((job/'probe.json').read_text())
    base=job/'godot';outputs={}
    for key in report['sources']:
        directory=job/(key+'-comparison');project=directory/'godot';staging=directory/'raw';staging.mkdir(parents=True)
        shutil.copytree(base,project,ignore=shutil.ignore_patterns('.godot','animations'))
        inputs=project/'animations';inputs.mkdir()
        r=report['reports'][key]['128'];duration=r['duration_seconds']
        selected=r['recommended']['target_fps'];reference=max(1,math.ceil(duration*30-1e-5));candidate=max(1,math.ceil(duration*selected-1e-5))
        counts={key+'__reference':reference,key+'__auto':candidate}
        for name in counts:shutil.copy2(base/'animations'/(key+'.fbx'),inputs/(name+'.fbx'))
        usage_path=project/'equipment_usage.json'
        if usage_path.exists():
            usage=json.loads(usage_path.read_text());action=usage.get('clips',{}).get(key,{'initial':'inherit','events':[]})
            usage['clips']={name:action for name in counts};atomic(usage_path,usage)
        # Use the current grid-capable renderer with the pinned diagnostic inputs.
        templates=Path(__file__).resolve().parent/'godot'
        shutil.copy2(templates/'temporal_plan.gd',project/'temporal_plan.gd')
        script=(templates/'baker.gd').read_text()
        expected='frame_count = int(sampling.frame_count)'
        if script.count(expected)!=1:raise ValueError('诊断渲染模板已变化，请更新比较器')
        script=script.replace(expected,f'frame_count = int({json.dumps(counts)}[asset_name])\n    sampling.frame_count = frame_count\n    sampling.columns = mini(frame_count,16)\n    sampling.rows = int(ceil(float(frame_count)/16.0))')
        (project/'baker.gd').write_text(script)
        with (directory/'render.log').open('w') as log:
            subprocess.run([GODOT,'--headless','--editor','--path',str(project),'--import','--log-file',str(directory/'import-engine.log')],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
            subprocess.run([GODOT,'--path',str(project),'--rendering-method','gl_compatibility','--log-file',str(directory/'render-engine.log'),'--','--output',str(staging),'--view',r['view'],'--frame-size','256'],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=240)
        # Flatten only within this diagnostic postprocessor for existing pixel finish.
        flat=[]
        for name,count in counts.items():
            source=Image.open(staging/(name+'_spritesheet.png')).convert('RGBA');sheet=Image.new('RGBA',(128*count,128))
            for i in range(count):
                x=i%16*256;y=i//16*256
                tile=source.crop((x,y,x+256,y+256)).resize((128,128),Image.Resampling.BOX);sheet.paste(tile,(i*128,0))
            path=directory/(name+'.png');sheet.save(path);flat.append(path)
        finish_batch(flat,frame_size=128)
        sheets=[Image.open(p).convert('RGBA') for p in flat]
        metrics=write_comparison(sheets,list(counts.values()),duration,selected,directory)
        timings=[json.loads((staging/(name+'_render.json')).read_text()) for name in counts]
        if timings[0]['camera']!=timings[1]['camera'] or any(v['frame_count']!=count or abs(v['duration_seconds']-duration)>1e-5 for v,count in zip(timings,counts.values())):
            raise ValueError('比较图集相机或时序不一致，不能用于采样质量判断')
        timing=json.loads((staging/(key+'__reference_render.json')).read_text())
        # Recheck the recommendation at the exact camera used for this comparison.
        calibrated=analyze(probes[key],128,timing['camera']['size'],r['view'])
        outputs[key]={'recommended_fps':selected,'reference_count':reference,'candidate_count':candidate,'duration_seconds':duration,'camera':timing['camera'],'calibrated_recommendation':calibrated['recommended'],'raster_metrics':metrics,'comparison':str((directory/'comparison.gif').relative_to(job)),'peak_comparison':str((directory/'peak-comparison.png').relative_to(job))}
        print(key,outputs[key],flush=True)
    atomic(job/'comparisons.json',outputs)
    write_review(job,report,outputs)
    return outputs


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('job',type=Path);args=parser.parse_args();compare(args.job.resolve())
