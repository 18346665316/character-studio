extends Node3D

var player: CharacterBody3D
var camera: Camera3D
var camera_yaw := 0.0
var camera_distance := 5.5
var camera_pitch := 0.35
var status: Label
var overview := false
var elapsed := 0.0
var qa := false
var qa_blocked := false
var qa_motions := {}

func material(color: String) -> StandardMaterial3D:
    var value := StandardMaterial3D.new()
    value.albedo_color = Color(color)
    value.roughness = 0.9
    return value

func box(size: Vector3, at: Vector3, color: String, solid := true) -> MeshInstance3D:
    var mesh := MeshInstance3D.new()
    var geometry := BoxMesh.new()
    geometry.size = size
    mesh.mesh = geometry
    mesh.material_override = material(color)
    mesh.position = at
    add_child(mesh)
    if solid:
        var body := StaticBody3D.new()
        var collision := CollisionShape3D.new()
        var shape := BoxShape3D.new()
        shape.size = size
        collision.shape = shape
        mesh.add_child(body)
        body.add_child(collision)
    return mesh

func _ready() -> void:
    qa = "--qa" in OS.get_cmdline_user_args()
    RenderingServer.set_default_clear_color(Color("b5c4c9"))
    var environment := WorldEnvironment.new()
    environment.environment = Environment.new()
    environment.environment.background_mode = Environment.BG_COLOR
    environment.environment.background_color = Color("b5c4c9")
    environment.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    environment.environment.ambient_light_color = Color("dce7ed")
    environment.environment.ambient_light_energy = 0.35
    environment.environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
    add_child(environment)
    var sun := DirectionalLight3D.new()
    sun.rotation_degrees = Vector3(-48, -30, 0)
    sun.light_color = Color("fff1d7")
    sun.light_energy = 0.8
    sun.shadow_enabled = true
    sun.directional_shadow_max_distance = 35
    add_child(sun)
    box(Vector3(24,0.3,24),Vector3(0,-0.15,0),"748e7b")
    box(Vector3(3.5,0.02,21),Vector3(0,0.012,0),"b9b39b",false)
    for x in [-12.0,12.0]: box(Vector3(0.35,1,24),Vector3(x,0.5,0),"8b9e93")
    for z in [-12.0,12.0]: box(Vector3(24,1,0.35),Vector3(0,0.5,z),"8b9e93")
    for setting in [[Vector3(-3,0.5,-1),Vector3(1.6,1,1.6)],[Vector3(3,0.75,-4),Vector3(1.4,1.5,1.4)],[Vector3(4,0.35,3),Vector3(2.0,0.7,1.3)]]:
        box(setting[1],setting[0],"b29b7b")
    # A collision test obstacle directly along the central route.
    box(Vector3(2,1,1),Vector3(0,0.5,-4),"849ba4")
    for x in [-6.5,6.5]:
        for z in [-7.0,0.0,7.0]:
            box(Vector3(0.3,1.5,0.3),Vector3(x,0.75,z),"776c58")
            var crown := MeshInstance3D.new()
            var sphere := SphereMesh.new()
            sphere.radius = 0.95
            sphere.height = 1.9
            crown.mesh = sphere
            crown.position = Vector3(x,2,z)
            crown.material_override = material("486f61")
            add_child(crown)
    player = load("res://player.gd").new()
    add_child(player)
    player.reset()
    camera = Camera3D.new()
    camera.fov = 48
    camera.near = 0.08
    add_child(camera)
    camera.current = true
    _ui()
    _camera(1.0)

func _ui() -> void:
    var canvas := CanvasLayer.new()
    add_child(canvas)
    var panel := PanelContainer.new()
    panel.position = Vector2(24,24)
    canvas.add_child(panel)
    var style := StyleBoxFlat.new()
    style.bg_color = Color(0.07,0.12,0.14,0.90)
    style.set_corner_radius_all(12)
    style.content_margin_left = 18
    style.content_margin_right = 18
    style.content_margin_top = 14
    style.content_margin_bottom = 14
    panel.add_theme_stylebox_override("panel",style)
    var column := VBoxContainer.new()
    column.add_theme_constant_override("separation",8)
    panel.add_child(column)
    var title := Label.new()
    title.text = "CHARACTER STUDIO / 3D"
    title.add_theme_font_size_override("font_size",20)
    column.add_child(title)
    var help := Label.new()
    help.text = "WASD / 方向键 移动 · Shift 快跑\n空格 跳跃 · J / 左键 跳跃挥剑\n1 Walk · 2 Jogging · 3 Run · 4 Fast Run\nQ / E 旋转视角 · 滚轮缩放\nTab 俯视 · R 复位 · 停止姿态代替 Idle"
    column.add_child(help)
    status = Label.new()
    column.add_child(status)

func _physics_process(delta: float) -> void:
    elapsed += delta
    var input := Vector2.ZERO
    if qa:
        # Walk into an obstacle, verify collision, then resume a run across the courtyard.
        if elapsed < 5.5: input = Vector2(0,-1)
        elif elapsed < 6.0:
            qa_blocked = player.position.z > -3.4 and player.position.z < -2.5
        elif elapsed < 7.5: input = Vector2(1,0)
        elif elapsed > 8.0 and elapsed < 8.2: player.trigger_action("standing_jump")
        elif elapsed > 10.5 and elapsed < 10.7: player.trigger_action("great_sword_jump_attack")
        elif elapsed > 13.5 and elapsed < 14.0:
            input = Vector2(0,1)
            player.locomotion = "jogging"
        elif elapsed > 14.0 and elapsed < 14.5:
            input = Vector2(0,1)
            player.locomotion = "run"
        qa_motions[player.current_motion] = true
        player.camera_yaw = 0.0
    else:
        input = Vector2(float(Input.is_physical_key_pressed(KEY_D) or Input.is_physical_key_pressed(KEY_RIGHT))-float(Input.is_physical_key_pressed(KEY_A) or Input.is_physical_key_pressed(KEY_LEFT)),float(Input.is_physical_key_pressed(KEY_S) or Input.is_physical_key_pressed(KEY_DOWN))-float(Input.is_physical_key_pressed(KEY_W) or Input.is_physical_key_pressed(KEY_UP))).limit_length()
        camera_yaw += (float(Input.is_physical_key_pressed(KEY_Q))-float(Input.is_physical_key_pressed(KEY_E))) * delta * 1.7
        player.camera_yaw = camera_yaw
    player.drive(input, Input.is_physical_key_pressed(KEY_SHIFT) or qa and elapsed > 6.0, delta)
    _camera(delta)
    status.text = "%s · Shift: %s · %.0f FPS" % [player.action if not player.action.is_empty() else player.current_motion if player.moving else "STOP",player.locomotion, Engine.get_frames_per_second()]
    if qa and elapsed > 16:
        set_physics_process(false)
        assert(player.jumped and player.attacked,"Jump / attack not triggered")
        assert(player.action.is_empty(),"Action failed to return to locomotion")
        assert(player.peak_height > 0.35,"Physical jump did not leave the ground")
        for motion in ["walk","fast_run","standing_jump","great_sword_jump_attack","jogging","run"]:
            assert(qa_motions.has(motion),"Missing animation state: " + motion)
        assert(qa_blocked,"Character failed obstacle collision")
        assert(player.travel > 8.0,"Character failed to move")
        assert(absf(player.position.y)<0.1,"Character did not settle on ground")
        if DisplayServer.get_name() != "headless":
            await RenderingServer.frame_post_draw
            get_viewport().get_texture().get_image().save_png("res://playground.png")
        print("PLAYGROUND_QA_PASS travel=",player.travel," position=",player.position," obstacle=",qa_blocked," motions=",qa_motions.keys()," jump_peak=",player.peak_height)
        get_tree().quit()
        set_physics_process(false)

func _camera(delta: float) -> void:
    var target := player.position + Vector3(0,1.0,0)
    var offset := Vector3(0,sin(camera_pitch),cos(camera_pitch)).rotated(Vector3.UP,camera_yaw) * camera_distance
    if overview: offset = Vector3(0,9,6)
    var desired := camera.position.lerp(target+offset,minf(8*delta,1))
    var query := PhysicsRayQueryParameters3D.create(target, desired)
    query.exclude = [player.get_rid()]
    var hit := get_world_3d().direct_space_state.intersect_ray(query)
    camera.position = hit.position + hit.normal * 0.2 if hit else desired
    camera.look_at(target)

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseButton and event.pressed:
        if event.button_index == MOUSE_BUTTON_LEFT: player.trigger_action("great_sword_jump_attack")
        if event.button_index == MOUSE_BUTTON_WHEEL_UP: camera_distance = maxf(2.5,camera_distance-0.4)
        if event.button_index == MOUSE_BUTTON_WHEEL_DOWN: camera_distance = minf(10,camera_distance+0.4)
    if event is InputEventKey and event.pressed and not event.echo:
        if event.physical_keycode == KEY_SPACE: player.trigger_action("standing_jump")
        if event.physical_keycode == KEY_J: player.trigger_action("great_sword_jump_attack")
        if event.physical_keycode == KEY_1: player.locomotion = "walk"
        if event.physical_keycode == KEY_2: player.locomotion = "jogging"
        if event.physical_keycode == KEY_3: player.locomotion = "run"
        if event.physical_keycode == KEY_4: player.locomotion = "fast_run"
        if event.physical_keycode == KEY_R: player.reset()
        if event.physical_keycode == KEY_TAB: overview = not overview
