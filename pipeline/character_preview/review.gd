extends Node3D
## Neutral character-only inspection. No movement controller or gameplay state.
var model: Node3D
var animation_player: AnimationPlayer
var skeleton: Skeleton3D
var spec: Dictionary
var orbit: Node3D
var camera: Camera3D
var yaw := 0.35
var pitch := -0.08
var distance := 4.0
var dragging := false
var playing := true
var scrubbing := false
var speed := 1.0
var timeline: HSlider
var time_label: Label
var choice: OptionButton
var play_button: Button
var accessory_checkbox: CheckBox
var model_mesh: MeshInstance3D
var original_mesh: Mesh
var body_mesh: Mesh
var report := {"actions": {}, "visual_review": "pending", "scope": "character-only"}
var bones_visible := false
var bone_lines: MeshInstance3D
var in_place := false
var source_clips := {}
var heading_parent: Node3D
var heading_angle: SpinBox
var heading_status: Label
var heading_slider: HSlider
var heading_values := {}

func _ready() -> void:
    spec = JSON.parse_string(FileAccess.get_file_as_string("res://review.json"))
    _stage()
    _character()
    heading_values = spec.get("headings", {}).duplicate(true)
    if not heading_values.is_empty():
        heading_parent = load("res://heading_runtime.gd").wrap_model(model, 0.0)
    _ui()
    _play_action(str(spec.get("heading_action", choice.get_item_text(0))))
    if spec.has("equipment_draft"):
        spec.equipment_draft.source_units_per_meter=1.0/model.scale.x
        var editor = load("res://equipment_editor.gd").new()
        add_child(editor)
        editor.setup(self)
    var args := OS.get_cmdline_user_args()
    if "--capture" in args:
        _capture_all()

func _character() -> void:
    var names: Array = spec.files.keys()
    names.sort()
    var first := "idle.fbx" if "idle.fbx" in names else str(names[0])
    model = load("res://assets/" + first).instantiate()
    model.name = "Character"
    add_child(model)
    animation_player = _find(model, "AnimationPlayer") as AnimationPlayer
    skeleton = _find(model, "Skeleton3D") as Skeleton3D
    model_mesh = _find(model, "MeshInstance3D") as MeshInstance3D
    original_mesh = model_mesh.mesh
    var library := AnimationLibrary.new()
    for filename in names:
        var extra: Node3D = load("res://assets/" + str(filename)).instantiate()
        var player := _find(extra, "AnimationPlayer") as AnimationPlayer
        var clip := _longest(player).duplicate() as Animation
        var action := str(filename).get_basename()
        clip.loop_mode = Animation.LOOP_LINEAR if action in ["idle", "walking", "walk", "running", "run"] else Animation.LOOP_NONE
        library.add_animation(action, clip)
        source_clips[action] = clip.duplicate()
        var hip := clip.find_track(NodePath("Skeleton3D:mixamorig_Hips"), Animation.TYPE_POSITION_3D)
        var roots := []
        if hip >= 0:
            for key in range(clip.track_get_key_count(hip)):
                var value: Vector3 = clip.track_get_key_value(hip, key)
                roots.append([clip.track_get_key_time(hip, key), value.x, value.y, value.z])
        report.actions[action] = {"duration": clip.length, "tracks": clip.get_track_count(), "root_position_keys": roots, "loop": clip.loop_mode == Animation.LOOP_LINEAR}
        extra.free()
    animation_player.add_animation_library("review", library)
    var box: AABB = model_mesh.transform * model_mesh.get_aabb()
    var factor := 1.8 / box.size.y
    model.scale = Vector3.ONE * factor
    model.position = Vector3(-box.get_center().x, -box.position.y, -box.get_center().z) * factor
    for surface in range(original_mesh.get_surface_count()):
        var material := model_mesh.get_active_material(surface).duplicate() as BaseMaterial3D
        material.roughness = 1.0
        material.metallic = 0.0
        material.albedo_color = Color.WHITE
        model_mesh.set_surface_override_material(surface, material)
    report["mesh_triangles"] = spec.inspection[first].triangles
    report["bones"] = skeleton.get_bone_count()
    report["height_meters"] = 1.8
    _prepare_accessory_comparison()

func _prepare_accessory_comparison() -> void:
    # Optional reviewed signature belongs to this character's review.json, never a global rule.
    var expected: Array = spec.get("reviewed_accessory_faces", [])
    if expected.is_empty():
        return
    var helper: Script = load("res://visual_cleanup.gd")
    body_mesh = helper.hide_reviewed_components(original_mesh, PackedInt32Array(expected))
    report["accessory_comparison"] = {"source_preserved": true, "reviewed_component_faces": expected}

func _find(node: Node, type_name: String) -> Node:
    if node.is_class(type_name):
        return node
    for child in node.get_children():
        var found := _find(child, type_name)
        if found:
            return found
    return null

func _longest(player: AnimationPlayer) -> Animation:
    var result: Animation
    for clip_name in player.get_animation_list():
        var clip := player.get_animation(clip_name)
        if clip_name != "RESET" and (not FileAccess.file_exists("res://heading_runtime.gd") or load("res://heading_runtime.gd").has_motion(clip)) and (result == null or clip.length > result.length):
            result = clip
    return result

func _stage() -> void:
    var world := WorldEnvironment.new()
    var environment := Environment.new()
    environment.background_mode = Environment.BG_COLOR
    environment.background_color = Color("222b32")
    environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    environment.ambient_light_color = Color("dbe5ed")
    environment.ambient_light_energy = 0.45
    world.environment = environment
    add_child(world)
    for settings in [[Vector3(-35, -35, 0), 0.7, Color("fff3e4")], [Vector3(-20, 135, 0), 0.4, Color("ceddeb")]]:
        var light := DirectionalLight3D.new()
        light.rotation_degrees = settings[0]
        light.light_energy = settings[1]
        light.light_color = settings[2]
        light.shadow_enabled = false
        add_child(light)
    var platform := MeshInstance3D.new()
    var cylinder := CylinderMesh.new()
    cylinder.top_radius = 1.15
    cylinder.bottom_radius = 1.15
    cylinder.height = 0.035
    var material := StandardMaterial3D.new()
    material.albedo_color = Color("3e4950")
    material.roughness = 1.0
    cylinder.material = material
    platform.mesh = cylinder
    platform.position.y = -0.025
    add_child(platform)
    orbit = Node3D.new()
    orbit.position = Vector3(-0.30, 1.10, 0)
    add_child(orbit)
    camera = Camera3D.new()
    camera.fov = 42
    orbit.add_child(camera)
    camera.current = true
    var arrow := MeshInstance3D.new()
    var lines := ImmediateMesh.new()
    var arrow_material := StandardMaterial3D.new()
    arrow_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
    arrow_material.albedo_color = Color("5bd4b5")
    lines.surface_begin(Mesh.PRIMITIVE_LINES, arrow_material)
    for point in [Vector3(0,0.015,0),Vector3(0,0.015,0.85),Vector3(0,0.015,0.85),Vector3(-0.12,0.015,0.65),Vector3(0,0.015,0.85),Vector3(0.12,0.015,0.65)]:
        lines.surface_add_vertex(point)
    lines.surface_end()
    arrow.mesh = lines
    add_child(arrow)
    _orbit()
    bone_lines = MeshInstance3D.new()
    bone_lines.name = "SkeletonOverlay"
    add_child(bone_lines)

func _label(value: String, font_size := 18) -> Label:
    var label := Label.new()
    label.text = value
    label.add_theme_font_size_override("font_size", font_size)
    label.add_theme_color_override("font_color", Color("e0e8eb"))
    return label

func _button(value: String, callback: Callable) -> Button:
    var button := Button.new()
    button.text = value
    button.custom_minimum_size.y = 38
    button.pressed.connect(callback)
    return button

func _ui() -> void:
    var layer := CanvasLayer.new()
    add_child(layer)
    var panel := PanelContainer.new()
    layer.add_child(panel)
    panel.set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT)
    panel.position = Vector2(24, 24)
    panel.custom_minimum_size = Vector2(330, 0)
    var style := StyleBoxFlat.new()
    style.bg_color = Color(0.045, 0.065, 0.08, 0.95)
    style.set_corner_radius_all(12)
    style.content_margin_left = 22
    style.content_margin_right = 22
    style.content_margin_top = 20
    style.content_margin_bottom = 20
    panel.add_theme_stylebox_override("panel", style)
    var column := VBoxContainer.new()
    column.add_theme_constant_override("separation", 12)
    var scroll := ScrollContainer.new()
    scroll.custom_minimum_size = Vector2(350, 640)
    panel.add_child(scroll)
    scroll.add_child(column)
    column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    column.add_child(_label("STUDIO / CHARACTER", 15))
    column.add_child(_label("人物检查", 30))
    column.add_child(_label(str(spec.character), 17))
    column.add_child(_label("%d 三角面 · %d 骨骼" % [report.mesh_triangles, report.bones], 15))
    choice = OptionButton.new()
    choice.custom_minimum_size.y = 40
    for action in report.actions:
        choice.add_item(action)
    choice.item_selected.connect(func(index: int): _play_action(choice.get_item_text(index)))
    column.add_child(choice)
    if heading_parent and not spec.has("equipment_draft"):
        column.add_child(_label("朝向校准 · 固定水平补偿", 16))
        heading_angle = SpinBox.new()
        heading_angle.min_value = -180
        heading_angle.max_value = 180
        heading_angle.step = 0.1
        heading_angle.suffix = "°"
        heading_angle.value_changed.connect(func(value: float):
            heading_parent.rotation_degrees.y = value
            heading_slider.set_value_no_signal(value)
            heading_status.text = "未保存 · 确认后重新生成图集")
        column.add_child(heading_angle)
        heading_slider = HSlider.new()
        heading_slider.min_value = -180
        heading_slider.max_value = 180
        heading_slider.step = 0.1
        heading_slider.value_changed.connect(func(value: float): heading_angle.value = value)
        column.add_child(heading_slider)
        var row := HBoxContainer.new()
        row.add_child(_button("试用参考角度", func():
            var record: Dictionary = heading_values.get(choice.get_item_text(choice.selected) + ".fbx", {})
            heading_angle.value = float(record.get("estimated_degrees", 0.0))))
        row.add_child(_button("重置", func(): heading_angle.value = 0.0))
        row.add_child(_button("确认并保存", _save_heading))
        column.add_child(row)
        heading_status = _label("", 13)
        heading_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
        column.add_child(heading_status)
        column.add_child(_label("估计仅供参考；确认保存后才影响新图集\n切换动作将丢弃未保存调整", 12))
    play_button = _button("暂停", func():
        playing = not playing
        play_button.text = "暂停" if playing else "播放"
        animation_player.speed_scale = speed if playing else 0.0)
    column.add_child(play_button)
    var speed_choice := OptionButton.new()
    for value in [0.25, 0.5, 1.0, 1.5]:
        speed_choice.add_item("%.2f ×" % value)
    speed_choice.select(2)
    speed_choice.item_selected.connect(func(index: int):
        speed = [0.25, 0.5, 1.0, 1.5][index]
        animation_player.speed_scale = speed if playing else 0.0)
    column.add_child(speed_choice)
    timeline = HSlider.new()
    timeline.step = 1.0 / 30.0
    timeline.drag_started.connect(func(): scrubbing = true)
    timeline.drag_ended.connect(func(_changed: bool): scrubbing = false)
    timeline.value_changed.connect(func(value: float):
        if scrubbing:
            animation_player.seek(value, true))
    column.add_child(timeline)
    time_label = _label("", 15)
    column.add_child(time_label)
    var inplace := CheckBox.new()
    inplace.text = "锁定水平根位移（原地预览）"
    inplace.toggled.connect(_set_in_place)
    column.add_child(inplace)
    var bones := CheckBox.new()
    bones.text = "显示骨骼"
    bones.toggled.connect(func(value: bool): bones_visible = value)
    column.add_child(bones)
    if body_mesh:
        accessory_checkbox = CheckBox.new()
        accessory_checkbox.text = "隐藏已确认的悬浮附件（对比）"
        accessory_checkbox.toggled.connect(func(value: bool): model_mesh.mesh = body_mesh if value else original_mesh)
        column.add_child(accessory_checkbox)
    for settings in [["正面", 0.0], ["侧面", PI / 2], ["背面", PI]]:
        var angle: float = settings[1]
        column.add_child(_button(settings[0], func():
            yaw = angle
            _orbit()))
    column.add_child(_label("右键拖动旋转 · 滚轮缩放\n左右方向键逐帧 · 空格播放/暂停", 14))
    column.add_child(_label("仅检查人物资产，不含游戏逻辑", 14))

func _play_action(action: String) -> void:
    if choice:
        for index in range(choice.item_count):
            if choice.get_item_text(index) == action:
                choice.select(index)
    if play_button:
        play_button.text = "暂停" if playing else "播放"
    if heading_parent:
        var record: Dictionary = heading_values.get(action + ".fbx", {"degrees":0.0})
        heading_parent.rotation_degrees.y = float(record.get("degrees", 0.0)) if record.get("status") == "confirmed" else 0.0
        if heading_angle:
            heading_angle.set_value_no_signal(heading_parent.rotation_degrees.y)
            heading_slider.set_value_no_signal(heading_angle.value)
            heading_status.text = "已确认" if record.get("status") == "confirmed" else str(record.get("reason", "待校准"))
    animation_player.play("review/" + action)
    animation_player.advance(0)
    animation_player.speed_scale = speed if playing else 0.0
    if timeline:
        timeline.max_value = report.actions[action].duration

func _set_in_place(value: bool) -> void:
    in_place = value
    for action in source_clips:
        var clip: Animation = source_clips[action].duplicate()
        if value:
            for track in range(clip.get_track_count()):
                if clip.track_get_type(track) == Animation.TYPE_POSITION_3D and str(clip.track_get_path(track)).ends_with(":mixamorig_Hips"):
                    var first := clip.position_track_interpolate(track, 0.0)
                    for key in range(clip.track_get_key_count(track)):
                        var position_value: Vector3 = clip.track_get_key_value(track, key)
                        position_value.x = first.x
                        position_value.z = first.z
                        clip.track_set_key_value(track, key, position_value)
        var library := animation_player.get_animation_library("review")
        library.remove_animation(action)
        library.add_animation(action, clip)
    _play_action(choice.get_item_text(choice.selected))

func _unhandled_input(event: InputEvent) -> void:
    if spec.has("equipment_draft") and (event is InputEventMouse or event is InputEventGesture):
        return
    if event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_RIGHT:
            dragging = event.pressed
        elif event.pressed and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
            distance = clampf(distance + (-0.1 if event.button_index == MOUSE_BUTTON_WHEEL_UP else 0.1), 0.25 if spec.has("equipment_draft") else 2.0, 7.0)
    if event is InputEventMouseMotion and dragging:
        yaw -= event.relative.x * 0.006
        pitch = clampf(pitch - event.relative.y * 0.004, -0.8, 0.5)
    if event is InputEventKey and event.pressed:
        if event.keycode == KEY_SPACE:
            play_button.pressed.emit()
        elif event.keycode in [KEY_LEFT, KEY_RIGHT]:
            playing = false
            play_button.text = "播放"
            animation_player.speed_scale = 0.0
            var frame := -1.0 / 30.0 if event.keycode == KEY_LEFT else 1.0 / 30.0
            animation_player.seek(clampf(animation_player.current_animation_position + frame, 0, animation_player.current_animation_length), true)
    _orbit()

func _orbit() -> void:
    orbit.rotation = Vector3(pitch, yaw, 0)
    camera.position = Vector3(0, 0, distance)

func _process(_delta: float) -> void:
    if animation_player and timeline and not animation_player.current_animation.is_empty():
        if not scrubbing:
            timeline.set_value_no_signal(animation_player.current_animation_position)
        time_label.text = "%.2f / %.2f 秒" % [animation_player.current_animation_position, animation_player.current_animation_length]
    bone_lines.visible = bones_visible
    if bones_visible:
        var lines := ImmediateMesh.new()
        var material := StandardMaterial3D.new()
        material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
        material.albedo_color = Color("7ce6da")
        material.no_depth_test = true
        lines.surface_begin(Mesh.PRIMITIVE_LINES, material)
        for index in range(skeleton.get_bone_count()):
            var parent := skeleton.get_bone_parent(index)
            if parent >= 0:
                lines.surface_add_vertex(skeleton.global_transform * skeleton.get_bone_global_pose(index).origin)
                lines.surface_add_vertex(skeleton.global_transform * skeleton.get_bone_global_pose(parent).origin)
        lines.surface_end()
        bone_lines.mesh = lines

func _capture_all() -> void:
    await get_tree().process_frame
    playing = false
    animation_player.speed_scale = 0.0
    var output := ProjectSettings.globalize_path("res://captures")
    DirAccess.make_dir_recursive_absolute(output)
    for action in report.actions:
        _play_action(action)
        for sample in range(4):
            animation_player.seek(report.actions[action].duration * sample / 4.0, true)
            await get_tree().process_frame
            await RenderingServer.frame_post_draw
            get_viewport().get_texture().get_image().save_png(output.path_join("%s_%d.png" % [action, sample]))
            if body_mesh and sample == 2:
                model_mesh.mesh = body_mesh
                await get_tree().process_frame
                await RenderingServer.frame_post_draw
                get_viewport().get_texture().get_image().save_png(output.path_join("%s_%d_clean.png" % [action, sample]))
                model_mesh.mesh = original_mesh
    _play_action("idle" if report.actions.has("idle") else str(report.actions.keys()[0]))
    for settings in [["front", 0.0], ["side", PI / 2], ["back", PI]]:
        yaw = settings[1]
        _orbit()
        await get_tree().process_frame
        await RenderingServer.frame_post_draw
        get_viewport().get_texture().get_image().save_png(output.path_join(settings[0] + ".png"))
    if body_mesh:
        model_mesh.mesh = body_mesh
        yaw = 0.35
        _orbit()
        await get_tree().process_frame
        await RenderingServer.frame_post_draw
        get_viewport().get_texture().get_image().save_png(output.path_join("accessories_hidden.png"))
    var file := FileAccess.open("res://character-report.json", FileAccess.WRITE)
    file.store_string(JSON.stringify(report, "  "))
    file.close()
    get_tree().quit()

func _save_heading() -> void:
    var filename := choice.get_item_text(choice.selected) + ".fbx"
    var record: Dictionary = heading_values.get(filename, {}).duplicate(true)
    if not spec.files.has(filename): return
    record["degrees"] = heading_angle.value
    record["status"] = "confirmed"
    record["source_sha256"] = spec.files[filename]
    record["schema"] = 1
    var target: String = str(spec.heading_directory).path_join(str(spec.files[filename]) + ".json")
    var file := FileAccess.open(target + ".tmp", FileAccess.WRITE)
    if file == null:
        heading_status.text = "保存失败，请检查目录权限"
        return
    file.store_string(JSON.stringify(record, "  "))
    file.close()
    if DirAccess.rename_absolute(target + ".tmp", target) != OK:
        heading_status.text = "保存失败，请重试"
        return
    heading_values[filename] = record
    heading_status.text = "已确认保存 · 关闭窗口后重新生成检查图和图集"
