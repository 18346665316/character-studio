"""Starter action requests; titles are search queries, not verified Mixamo product IDs."""
ROLES = {'idle','walk','run','jump','attack'}
PRESETS = [{'id':'basic_movement','version':1,'name':'基础移动',
            'description':'待机、走路、跑步、跳跃；下载后仍需检查具体表演。',
            'actions':[{'role':role,'title':title,'loop_intent':loop} for role,title,loop in (
                ('idle','Breathing Idle',True),('walk','Walking',True),
                ('run','Running',True),('jump','Standing Jump',False))]}]


def validate_metadata(actions, params):
    roles=params.get('roles',{})
    if not isinstance(roles,dict) or any(title not in actions or role not in ROLES for title,role in roles.items()):
        raise ValueError('动作用途必须对应本次下载标题')
    if len(set(roles.values())) != len(roles): raise ValueError('同一用途只能指定一个动作')
    preset=params.get('preset')
    if preset is not None and not any(preset=={'id':p['id'],'version':p['version']} for p in PRESETS):
        raise ValueError('未知动作预设版本')
    result={}
    if roles: result['roles']=roles.copy()
    if preset is not None: result['preset']=preset.copy()
    return result


def receipt_metadata(params):
    roles=params.get('roles',{})
    return {'action_roles':{title.lower().replace(' ','_')+'.fbx':role for title,role in roles.items()},
            'loop_intent':{title.lower().replace(' ','_')+'.fbx':role in ('idle','walk','run') for title,role in roles.items()},
            **({'preset':params['preset']} if params.get('preset') else {})}
