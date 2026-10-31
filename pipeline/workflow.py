"""Pure, shared workflow guidance; task success is distinct from visual approval."""
STAGES = {'reconstruct':0,'prepare':0,'rig':1,'download':2,'review':3,'equipment':5,'bake':4}

def guidance(character, jobs):
    own=[j for j in jobs if j.get('character')==character['id']]
    current=next((j for j in own if j['status'] in ('queued','running')),own[0] if own else None)
    if current and current['status'] in ('queued','running'):
        return {'stage':STAGES.get(current['action'],0),'label':'查看当前任务','reason':'任务正在执行，完成后检查结果。','running':True}
    if character['rig']['status']=='needs_review' and not character['rig'].get('recovery_available'):
        return {'stage':1,'label':'恢复 Mixamo 人物','reason':'云端人物需要复核，本地模型与历史交付仍保留。'}
    if current and current['status'] in ('failed','interrupted'):
        return {'stage':STAGES.get(current['action'],0),'label':'处理未完成的步骤','reason':current.get('error') or '查看原因后重试当前步骤。','retry':current['id']}
    if not character['prepared']:
        return {'stage':0,'label':'生成模型','reason':'选择原画，生成带贴图的人物。'}
    if not character['model_approved']:
        return {'stage':0,'label':'检查并确认模型','reason':'确认四肢、轮廓和背面后再进入绑定。'}
    if not character['rig']['ready']:
        return {'stage':1,'label':'完成骨骼绑定','reason':'打开 Mixamo 放置关节点，并确认变形。'}
    batches=[b for b in character['batches'] if b['current_rig']]
    if not batches:
        return {'stage':2,'label':'选择人物动作','reason':'选择动作后下载，不需要重新建模。'}
    batch=batches[0]
    group_approved=character['approvals'].get('motions',{}).get(batch['id'],{}).get('fingerprint')==batch['fingerprint']
    files=batch.get('files',[])
    individual_approved=bool(files) and all(character['approvals'].get('animations',{}).get(batch['id'],{}).get(file,{}).get('fingerprint')==batch['fingerprint'] for file in files)
    if not (group_approved or individual_approved):
        return {'stage':3,'batch':batch['id'],'label':'检查人物动作','reason':'检查姿态与变形，确认后可选装备或生成图集。'}
    return {'stage':4,'batch':batch['id'],'label':'预览与导出','reason':'可直接导出空手角色，或先到“武器（可选）”调整握持。'}
