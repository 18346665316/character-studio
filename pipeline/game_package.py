"""Read-only, portable Godot 4 character package from immutable sprite deliveries."""
import io,json,math,zipfile
from pathlib import Path
from PIL import Image
from asset_repository import AssetRepository,name

ROLES=('idle','walk','run','jump')
TEMPLATES=Path(__file__).parent/'game_package'


def build(root,character,selections,variant='game',report_only=False,action_set=False):
    assets=AssetRepository(root);name(character)
    if variant not in ('game','source'): raise ValueError('未知图集版本')
    if not isinstance(selections,dict) or not selections or len(selections)>32: raise ValueError('请选择1–32个动作')
    if not action_set and set(selections)!=set(ROLES): raise ValueError('请为待机、走路、跑步、跳跃各选择一个图集')
    output={};records={};warnings=[];reference=None;animations=[];resources=[];external=[];resource_count=0
    for role in (selections if action_set else ROLES):
        name(role)
        choice=selections[role]
        if not isinstance(choice,dict):raise ValueError('非法动作选择')
        selected_variant=choice.get('variant',variant) if action_set else variant
        if selected_variant not in ('game','source'):raise ValueError('未知图集版本')
        loop=choice.get('loop',role in ('idle','walk','run')) if action_set else role in ('idle','walk','run')
        if type(loop) is not bool:raise ValueError('循环设置须为布尔值')
        delivery=name(choice.get('delivery'));clip=name(choice.get('clip'))
        base=f'deliverables/{character}/{delivery}'
        manifest=json.loads(assets.scoped(base+'/manifest.json',f'deliverables/{character}').read_text())
        if manifest.get('source',{}).get('character')!=character:raise ValueError('图集人物不匹配')
        original=manifest.get(clip+'_spritesheet.png',{})
        info=original.get('game') if selected_variant=='game' else original
        if not info:raise ValueError(f'{role} 缺少所选版本，请先生成精简版或选择完整版本')
        projection=info.get('projection',{})
        anchor=info.get('anchor_px');body=info.get('body_height_px')
        if not body or not isinstance(anchor,list) or len(anchor)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in anchor):
            raise ValueError(f'{role} 缺少人物比例或脚底锚点，请用新工作流重新生成')
        identity=(projection.get('reference_sha256'),body,info.get('view'),projection.get('pixels_per_source_unit'),manifest.get('renderer','godot'))
        if not identity[0] or not identity[3]:raise ValueError('缺少标准站姿来源，请重新生成')
        if reference is None:reference=identity
        if identity!=reference:raise ValueError('动作的绑定、人物比例、视角或渲染器不一致，请使用一致设置重新生成')
        count=info.get('frame_count');size=info.get('frame_width');height=info.get('frame_height');duration=info.get('duration_seconds')
        if type(count)is not int or not 0<count<=4096 or type(size)is not int or size!=height or not 0<size<=1024 or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0:raise ValueError('无效图集尺寸或时序')
        durations=info.get('frame_durations_seconds',[duration/count]*count)
        if len(durations)!=count or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in durations) or abs(sum(durations)-duration)>1e-5:raise ValueError('逐帧时长不匹配')
        sheet=assets.scoped(base+('/game/' if selected_variant=='game' else '/')+clip+'_spritesheet.png',f'deliverables/{character}/{delivery}')
        raw=sheet.read_bytes()
        with Image.open(io.BytesIO(raw)) as im:
            if im.width%size or im.height%size or count>im.width//size*(im.height//size):raise ValueError('图集容量不匹配')
            cols=im.width//size
        output[f'assets/textures/{role}.png']=raw
        # Explicit lossless import, no mipmaps. Godot regenerates relocated paths.
        output[f'assets/textures/{role}.png.import']=b'''[remap]
importer="texture"
type="CompressedTexture2D"
[params]
compress/mode=0
mipmaps/generate=false
process/fix_alpha_border=true
detect_3d/compress_to=0
'''

        external.append(f'[ext_resource type="Texture2D" path="assets/textures/{role}.png" id="{role}"]')
        frames=[]
        for i,seconds in enumerate(durations):
            resource_count+=1;rid=f'Frame_{resource_count}'
            # Each region's origin is the common ground anchor, including mirrored sprites.
            resources.append(f'[sub_resource type="AtlasTexture" id="{rid}"]\natlas = ExtResource("{role}")\nregion = Rect2({i%cols*size}, {i//cols*size}, {size}, {size})')
            frames.append(f'{{"duration": {seconds:.12f}, "texture": SubResource("{rid}")}}')
        animations.append('{"name": &"'+role+'", "speed": 1.0, "loop": '+('true' if loop else 'false')+', "frames": ['+',\n'.join(frames)+']}')
        records[role]={'role_assignment':'user_selected','semantic_validation':'unverified','texture':'assets/textures/'+role+'.png','equipment':manifest.get('equipment'),'quality':original.get('quality',{}),'color_processing':manifest.get('color_processing'),'delivery':delivery,'clip':clip,'variant':selected_variant,'frame_count':count,'duration_seconds':duration,'frame_durations_seconds':durations,'loop':loop,'anchor_px':anchor,'frame_size':size,'sha256':assets.digest(sheet)}
        if action_set:
            records[role]['manual_review']='user_confirmed' if choice.get('reviewed') else 'pending'
            if not choice.get('reviewed'):warnings.append(role+'：尚未人工验收动作与循环效果')
        quality=original.get('quality',{})
        if quality.get('status')=='failed':raise ValueError('所选动作未通过质量检查')
        if quality.get('status')=='review':warnings.append(role+'：存在需人工复核的画面提示')
        if loop and quality.get('loop',{}).get('status')!='passed' and not (action_set and choice.get('reviewed')):warnings.append(role+'：循环接缝尚未验收，预览中已按用途开启循环')
    output['animations.tres']=('[gd_resource type="SpriteFrames" load_steps='+str(resource_count+5)+' format=3]\n'+ '\n\n'.join(external+resources)+'\n[resource]\nanimations = ['+',\n'.join(animations)+']\n').encode()
    default_action='idle' if 'idle' in records else next(iter(records))
    output['character.gd']=(TEMPLATES/'character.gd').read_bytes().replace(b'play_action("idle")',('play_action("'+default_action+'")').encode())
    # Change sprite offset per animation, maintaining each exported anchor precisely.
    offsets={role:[r['frame_size']/2-r['anchor_px'][0],r['frame_size']/2-r['anchor_px'][1]] for role,r in records.items()}
    output['character.gd']+= ('\nconst OFFSETS = '+json.dumps(offsets)+'\n').encode()
    output['character.tscn']=b'''[gd_scene load_steps=3 format=3]
[ext_resource type="Script" path="character.gd" id="1"]
[ext_resource type="SpriteFrames" path="animations.tres" id="2"]
[node name="Character" type="Node2D"]
texture_filter = 1
script = ExtResource("1")
[node name="Sprite" type="AnimatedSprite2D" parent="."]
sprite_frames = ExtResource("2")
animation = &"idle"
'''
    output['character.tscn']=output['character.tscn'].replace(b'animation = &"idle"',('animation = &"'+default_action+'"').encode())
    output['preview.gd']=(TEMPLATES/'preview.gd').read_bytes().replace(b'["idle","walk","run","jump"]',json.dumps(list(records)).encode())
    output['preview.tscn']=b'[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="preview.gd" id="1"]\n[node name="Preview" type="Node2D"]\nscript = ExtResource("1")\n'
    report={'schema':1,'character':character,'body_height_px':reference[1],'view':reference[2],'reference_sha256':reference[0],'pixels_per_source_unit':reference[3],'renderer':reference[4],'actions':records,'warnings':warnings,'scope':'Asset playback only; no movement, physics or gameplay state machine.'}
    reused={}
    for role,record in records.items(): reused.setdefault((record['delivery'],record['clip']),[]).append(role)
    for roles in reused.values():
        if len(roles)>1: warnings.append('同一源动作被指定到多个用途：'+', '.join(roles)+'；语义适用性未验收')
    contract={
        'schema':'character_studio.asset/1.0','asset_id':character,'kind':'character_2d',
        'engine':{'name':'Godot','major':4},'entry_scene':'character.tscn','preview_scene':'preview.tscn',
        'api':{'play_action':{'arguments':['action: String','restart: bool = false'],'returns':'bool; false for unknown action','behavior':'same action continues unless restart=true; completed one-shot stays on last frame'},
               'has_action':{'arguments':['action: String'],'returns':'bool'},
               'get_action':{'returns':'String'},
               'set_mirrored':{'arguments':['value: bool'],'behavior':'horizontal mirror with ground anchor preserved; does not create another view'},
               'signals':{'action_finished':'action: String; emitted only for a completed non-looping action'}},
        'coordinates':{'root':'ground anchor','x_positive':'right','y_positive':'down','units':'pixels','body_height_px':reference[1],'scaling':'integer multiples recommended'},
        'directions':{'available_views':[reference[2]],'default_facing':'source-authored; not normalized','mirroring':'optional horizontal only','multi_direction_ready':False},
        'motion':{'horizontal_displacement':'game-owned; original raster displacement may remain','jump_vertical_displacement':'baked into sprite frames; do not add another visual jump offset without compensation','physics_included':False,'collision_included':False},
        'actions':records,
        'validation':{'structural':'passed','scope':['projection compatibility','frame capacity','positive frame timing','source sheet hashes'],
                      'engine_runtime':'not_run_for_this_export','semantic':'unverified','artistic':'requires_review','warnings':warnings},
        'limitations':['No gameplay controller, hitboxes, damage events or action blending.',
                       'Loop intent is configured; loop seams require review.',
                       'Role assignments are user choices, not proof of motion semantics.',
                       'Equipment is baked into pixels; runtime unequip and independent recoloring are unavailable.']}
    report['asset_contract']='asset.json'
    if report_only: return report
    output['asset.json']=json.dumps(contract,ensure_ascii=False,indent=2).encode()
    output['INTEGRATION.md']=(TEMPLATES/'INTEGRATION.md').read_bytes()
    output['manifest.json']=json.dumps(report,ensure_ascii=False,indent=2).encode()
    output['README.txt']='复制 character_assets 整个文件夹到 Godot 4 项目，实例化 character.tscn。根节点是脚底锚点。调用 play_action("walk") 切换动作。单独打开此包的 project.godot 可预览。人物移动、跳跃物理与动作过渡由游戏处理。最近邻显示，整数倍缩放。\n'.encode()
    prefix=f'character_assets/{character}/';buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for filename,raw in output.items():archive.writestr(prefix+filename,raw)
        archive.writestr('project.godot',f'''config_version=5
[application]
config/name="Studio Character Preview"
run/main_scene="res://{prefix}preview.tscn"
[display]
window/size/viewport_width=960
window/size/viewport_height=540
window/stretch/mode="viewport"
window/stretch/scale_mode="integer"
[rendering]
renderer/rendering_method="gl_compatibility"
textures/default_filters/use_nearest_mipmap_filter=false
textures/canvas_textures/default_texture_filter=0
''')
    return buffer.getvalue()
