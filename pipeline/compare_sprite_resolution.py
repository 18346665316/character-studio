"""Build a playable resolution comparison from a shared high-resolution render."""
import json
from pathlib import Path
import shutil
from PIL import Image, ImageDraw


def build(root):
    source=root/'.local/quality/sprite-resolution/raw'
    original=root/'.local/playgrounds_2d/hunyuan-guard/20261101-074902-d5bbd8a0'
    project=root/'.local/playgrounds_2d/hunyuan-guard/resolution-comparison'
    shutil.copytree(root/'pipeline/scene_2d',project,dirs_exist_ok=True)
    manifest=json.loads((original/'assets/manifest.json').read_text())
    raw_size=512
    with Image.open(source/'walk_spritesheet.png') as sheet:
        rect=sheet.crop((0,0,raw_size,raw_size)).getbbox()
    body_height=rect[3]-rect[1]
    board=Image.new('RGB',(840,400),'#d4d5cd');draw=ImageDraw.Draw(board)
    entries=[('Previous',None),('48px',48),('64px',64),('96px',96)]
    for column,(label,target) in enumerate(entries):
        draw.text((column*210+12,10),label,fill='black')
        if target is None:
            with Image.open(original/'assets/walk_spritesheet.png') as sheet:
                frame=sheet.crop((0,0,64,64));bounds=frame.getbbox();frame=frame.crop(bounds)
        else:
            assets=project/'assets'/str(target);assets.mkdir(parents=True,exist_ok=True)
            size=round(raw_size*target/body_height)
            data={}
            for key in manifest:
                if not key.endswith('_spritesheet.png'):continue
                timing=json.loads((source/key.replace('_spritesheet.png','_render.json')).read_text())
                count=int(timing['frame_count']);cols=int(timing['columns']);rows=int(timing['rows'])
                output=Image.new('RGBA',(cols*size,rows*size))
                with Image.open(source/key) as sheet:
                    for index in range(count):
                        x=index%cols;y=index//cols
                        frame=sheet.crop((x*raw_size,y*raw_size,(x+1)*raw_size,(y+1)*raw_size))
                        frame=frame.resize((size,size),Image.Resampling.LANCZOS)
                        output.paste(frame,(x*size,y*size))
                output.save(assets/key)
                timing.update(frame_width=size,frame_height=size,body_height_target=target)
                data[key]=timing
            (assets/'manifest.json').write_text(json.dumps(data,indent=2))
            with Image.open(assets/'walk_spritesheet.png') as sheet:
                frame=sheet.crop((0,0,size,size));bounds=frame.getbbox();frame=frame.crop(bounds)
        # All four examples have equal apparent character height.
        frame=frame.resize((round(frame.width*192/frame.height),192),Image.Resampling.NEAREST)
        board.paste(frame,(column*210+80-frame.width//2,45),frame)
        draw.text((column*210+12,265),'Equal display height',fill='black')
    board.save(project/'comparison.png')
    s=(project/'world.gd').read_text()
    start=s.index('    for motion in ["walk"');end=s.index('    var layer :=',start)
    loader=s[start:end]
    loader=loader[:loader.index('    sprite.animation_finished.connect')]
    loader=loader.replace('"res://assets/"','"res://assets/"+str(resolution)+"/"').replace('"res://assets/walk_spritesheet.png"','"res://assets/"+str(resolution)+"/walk_spritesheet.png"')
    loader=loader.replace('Rect2i(0,0,64,64)','Rect2i(0,0,cell,cell)').replace('    var used := first.get_used_rect()','    var used := first.get_used_rect()\n    var factor := 96.0 / float(used.size.y)\n    sprite.scale = Vector2.ONE*factor').replace('(used.get_center().x-32)*3','(used.get_center().x-cell/2.0)*factor').replace('(used.end.y-32)*3','(used.end.y-cell/2.0)*factor')
    loader='''func set_resolution(value: int):
    resolution = value
    var old_animation := sprite.animation
    var old_frame := sprite.frame
    var was_playing := sprite.is_playing()
    manifest = JSON.parse_string(FileAccess.get_file_as_string("res://assets/"+str(value)+"/manifest.json"))
    var cell := int(manifest["walk_spritesheet.png"].frame_width)
    sprite.sprite_frames = SpriteFrames.new()
'''+loader+'''    sprite.animation = old_animation if sprite.sprite_frames.has_animation(old_animation) else "walk"
    sprite.frame = mini(old_frame,sprite.sprite_frames.get_frame_count(sprite.animation)-1)
    if was_playing: sprite.play()
'''
    s=s[:start]+'''    set_resolution(64)
    sprite.animation_finished.connect(func(): active_action = "")
'''+s[end:]
    s=s.replace('var anchor_x := 0.0','var anchor_x := 0.0\nvar resolution := 64').replace('    manifest = JSON.parse_string(FileAccess.get_file_as_string("res://assets/manifest.json"))\n','')
    s=s.replace('1–4 选择 Walk / Jogging / Run / Fast Run · R 复位','F1 / F2 / F3：48 / 64 / 96 像素（显示大小相同）\\n  1–4 切换动作 · R 复位')
    s=s.replace('    column.add_child(label)\n','''    column.add_child(label)
    var choices := HBoxContainer.new()
    column.add_child(choices)
    for size in [48,64,96]:
        var button := Button.new()
        button.text = str(size)+"px"
        button.pressed.connect(func(): set_resolution(size))
        choices.add_child(button)
''')
    s=s.replace('info.text = "  %s · Shift: %s · %.0f FPS  " % [sprite.animation,run_motion,Engine.get_frames_per_second()]','info.text = "  人物 %dpx · %s · %.0f FPS  " % [resolution,sprite.animation,Engine.get_frames_per_second()]')
    s=s.replace('        if event.physical_keycode == KEY_SPACE:', '''        if event.physical_keycode == KEY_F1: set_resolution(48)
        if event.physical_keycode == KEY_F2: set_resolution(64)
        if event.physical_keycode == KEY_F3: set_resolution(96)
        if event.physical_keycode == KEY_SPACE:''')
    s=s.replace('    if qa:\n        if elapsed < 1:', '    if qa:\n        if elapsed > 0.2 and elapsed < 0.25: set_resolution(48)\n        if elapsed > 4 and elapsed < 4.05: set_resolution(64)\n        if elapsed > 7 and elapsed < 7.05: set_resolution(96)\n        if elapsed < 1:')
    s+='\n'+loader
    (project/'world.gd').write_text(s)
    print(project)
    return project

if __name__=='__main__': build(Path(__file__).resolve().parents[1])
