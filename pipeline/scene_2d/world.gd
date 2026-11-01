extends Node2D

var character: CharacterBody2D
var sprite: AnimatedSprite2D
var shadow: Polygon2D
var info: Label
var active_action := ""
var run_motion := "fast_run"
var action_time := 0.0
var manifest: Dictionary
var qa := false
var elapsed := 0.0
var visited := {}
var distance := 0.0
var qa_collision := false
var anchor_x := 0.0
var display_scale := 1.0
var anchor_y := 0.0
const OBSTACLES := [Rect2(380,220,90,65),Rect2(680,370,110,70),Rect2(220,460,70,60)]

func _ready():
    qa = "--qa" in OS.get_cmdline_user_args()
    texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
    manifest = JSON.parse_string(FileAccess.get_file_as_string("res://assets/manifest.json"))
    RenderingServer.set_default_clear_color(Color("243d3a"))
    for rect in [Rect2(0,0,1100,150),Rect2(0,710,1100,50),Rect2(0,0,35,760),Rect2(1065,0,35,760)]:
        collision(rect)
    for rect in OBSTACLES: collision(rect)
    character = CharacterBody2D.new()
    character.position = Vector2(550,560)
    var shape := CollisionShape2D.new()
    var capsule := CapsuleShape2D.new()
    capsule.radius = 10
    capsule.height = 22
    shape.shape = capsule
    character.add_child(shape)
    add_child(character)
    shadow = Polygon2D.new()
    var ellipse := PackedVector2Array()
    for i in range(32): ellipse.append(Vector2(cos(i*TAU/32)*20,sin(i*TAU/32)*7))
    shadow.polygon = ellipse
    shadow.color = Color(0.06,0.13,0.12,0.4)
    character.add_child(shadow)
    sprite = AnimatedSprite2D.new()
    sprite.scale = Vector2.ONE
    sprite.sprite_frames = SpriteFrames.new()
    character.add_child(sprite)
    for motion in ["walk","jogging","run","fast_run","standing_jump","great_sword_jump_attack"]:
        var data: Dictionary = manifest[motion+"_spritesheet.png"]
        var texture = load("res://assets/"+motion+"_spritesheet.png")
        sprite.sprite_frames.add_animation(motion)
        sprite.sprite_frames.set_animation_speed(motion,float(data.fps))
        sprite.sprite_frames.set_animation_loop(motion,motion not in ["standing_jump","great_sword_jump_attack"])
        for frame in range(int(data.frame_count)):
            var atlas := AtlasTexture.new()
            atlas.atlas = texture
            atlas.region = Rect2((frame%int(data.columns))*int(data.frame_width),int(frame/int(data.columns))*int(data.frame_height),data.frame_width,data.frame_height)
            sprite.sprite_frames.add_frame(motion,atlas)
    # Exported projection anchor keeps all poses attached to the same ground point.
    var reference: Dictionary = manifest["walk_spritesheet.png"]
    var anchor: Array = reference["anchor_px"]
    anchor_x = float(anchor[0])-float(reference.frame_width)*0.5
    anchor_y = float(anchor[1])-float(reference.frame_height)*0.5
    for motion in ["walk","jogging","run","fast_run","standing_jump","great_sword_jump_attack"]:
        var data: Dictionary = manifest[motion+"_spritesheet.png"]
        assert(data.body_height_px == 96, "Expected 96px reference body")
        assert(data.anchor_px == anchor, "Actions must share the projection anchor")
        assert(data.frame_width == reference.frame_width, "Actions must share canvas")
    sprite.position = Vector2(-anchor_x,-anchor_y)
    sprite.play("walk")
    sprite.pause()
    sprite.animation_finished.connect(func(): active_action = "")
    var layer := CanvasLayer.new()
    add_child(layer)
    var panel := PanelContainer.new()
    panel.position = Vector2(24,20)
    layer.add_child(panel)
    var column := VBoxContainer.new()
    panel.add_child(column)
    var label := Label.new()
    label.text = "  CHARACTER STUDIO / 2D  \n  WASD / 方向键移动 · Shift 快跑 · 空格跳跃 · J / 左键挥剑  \n  1–4 选择 Walk / Jogging / Run / Fast Run · F1/F2/F3: 1×/2×/3× · R 复位  "
    column.add_child(label)
    info = Label.new()
    column.add_child(info)
    queue_redraw()

func collision(rect: Rect2):
    var body := StaticBody2D.new()
    var shape := CollisionShape2D.new()
    var box := RectangleShape2D.new()
    box.size = rect.size
    shape.shape = box
    body.position = rect.get_center()
    body.add_child(shape)
    add_child(body)

func _draw():
    draw_rect(Rect2(35,150,1030,560),Color("779a73"))
    for x in range(45,1055,24):
        for y in range(160,700,24):
            draw_line(Vector2(x,y),Vector2(x+3,y-3),Color("6d8e68"),1)
    draw_rect(Rect2(490,150,120,560),Color("c5b48a"))
    draw_rect(Rect2(35,325,1030,90),Color("c5b48a"))
    for rect in OBSTACLES:
        draw_rect(Rect2(rect.position+Vector2(7,8),rect.size),Color(0,0,0,0.18))
        draw_rect(rect,Color("7b6950"))
        draw_rect(Rect2(rect.position,Vector2(rect.size.x,12)),Color("b6a07a"))
        draw_rect(rect,Color("4d5143"),false,3)
    for x in [110,960]:
        for y in [220,465,625]:
            draw_circle(Vector2(x+4,y+9),30,Color(0,0,0,0.15))
            draw_rect(Rect2(x-5,y,10,23),Color("665443"))
            draw_circle(Vector2(x,y-8),29,Color("345e48"))
            draw_circle(Vector2(x-7,y-15),18,Color("4c7a52"))

func trigger(motion: String):
    if not active_action.is_empty(): return
    active_action = motion
    action_time = 0.0
    sprite.play(motion)

func _physics_process(delta):
    elapsed += delta
    var input := Vector2.ZERO
    var sprint := Input.is_physical_key_pressed(KEY_SHIFT)
    if qa:
        if elapsed < 1: input = Vector2.UP
        elif elapsed < 2:
            input = Vector2.RIGHT
            sprint = true
        elif elapsed < 2.2: trigger("standing_jump")
        elif elapsed > 5 and elapsed < 5.2: trigger("great_sword_jump_attack")
        elif elapsed > 8 and elapsed < 8.5:
            input = Vector2.LEFT
            sprint = true
            run_motion = "jogging"
        elif elapsed > 8.5 and elapsed < 9:
            input = Vector2.LEFT
            sprint = true
            run_motion = "run"
        elif elapsed > 9 and elapsed < 9.1: character.position = Vector2(640,405)
        elif elapsed > 9.1 and elapsed < 10.5: input = Vector2.RIGHT
        elif elapsed > 10.5 and elapsed < 11: qa_collision = character.position.x < 675
    else:
        input = Vector2(float(Input.is_physical_key_pressed(KEY_D) or Input.is_physical_key_pressed(KEY_RIGHT))-float(Input.is_physical_key_pressed(KEY_A) or Input.is_physical_key_pressed(KEY_LEFT)),float(Input.is_physical_key_pressed(KEY_S) or Input.is_physical_key_pressed(KEY_DOWN))-float(Input.is_physical_key_pressed(KEY_W) or Input.is_physical_key_pressed(KEY_UP))).limit_length()
    if active_action == "great_sword_jump_attack": input = Vector2.ZERO
    character.velocity = input * (175 if sprint else 95)
    var previous := character.position
    character.move_and_slide()
    distance += character.position.distance_to(previous)
    if input.x != 0 and active_action.is_empty(): sprite.flip_h = input.x > 0
    sprite.position = Vector2(anchor_x if sprite.flip_h else -anchor_x,-anchor_y)*display_scale
    sprite.scale = Vector2.ONE*display_scale
    if active_action.is_empty():
        if input.length()>0:
            var motion := run_motion if sprint else "walk"
            sprite.play(motion)
        else:
            sprite.animation = "walk"
            sprite.frame = 0
            sprite.pause()
    action_time += delta
    visited[sprite.animation] = true
    info.text = "  %s · Shift: %s · 人物 96px / %d× · %.0f FPS  " % [sprite.animation,run_motion,int(display_scale),Engine.get_frames_per_second()]
    if qa and elapsed > 11:
        set_physics_process(false)
        assert(qa_collision,"Obstacle collision failed")
        assert(active_action.is_empty(),"Action did not finish")
        assert(distance>250,"Movement failed")
        assert(visited.size()==6,"Missing animation state")
        character.position = Vector2(550,505)
        if DisplayServer.get_name() != "headless":
            await RenderingServer.frame_post_draw
            get_viewport().get_texture().get_image().save_png("res://playground.png")
        print("PLAYGROUND_2D_QA_PASS states=",visited.keys()," collision=",qa_collision," travel=",distance)
        get_tree().quit()

func _unhandled_input(event):
    if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT: trigger("great_sword_jump_attack")
    if event is InputEventKey and event.pressed and not event.echo:
        if event.physical_keycode in [KEY_F1,KEY_F2,KEY_F3]: display_scale = float(event.physical_keycode-KEY_F1+1)
        if event.physical_keycode == KEY_SPACE: trigger("standing_jump")
        if event.physical_keycode == KEY_J: trigger("great_sword_jump_attack")
        if event.physical_keycode == KEY_R:
            character.position = Vector2(550,560)
            active_action = ""
        if event.physical_keycode in [KEY_1,KEY_2,KEY_3,KEY_4]: run_motion = ["walk","jogging","run","fast_run"][event.physical_keycode-KEY_1]
