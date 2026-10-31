extends Node
## Job-local baker. Studio copies only the selected batch into res://animations.

var frame_size := 128
var frame_count := 10
var view := "three_quarter"
var target_fps := 12.0
var preflight := true
var shared_bounds := AABB()
var has_shared_bounds := false
var shared_screen := Rect2()
var has_shared_screen := false

func _ready() -> void:
    var args := OS.get_cmdline_user_args()
    var output := ""
    for i in range(args.size() - 1):
        if args[i] == "--output":
            output = args[i + 1]
        elif args[i] == "--frame-size":
            frame_size = int(args[i + 1])
        elif args[i] == "--view":
            view = args[i + 1]
    if output.is_empty() or DisplayServer.get_name() == "headless":
        push_error("Run through ./studio bake with a job output and a rendering display.")
        get_tree().quit(1)
        return
    var directory := DirAccess.open("res://animations")
    if directory == null:
        push_error("No job-local animation directory.")
        get_tree().quit(1)
        return
    var files := directory.get_files()
    files.sort()
    # Measure the whole batch first: every action shares scale and ground alignment.
    for file_name in files:
        if file_name.get_extension().to_lower() in ["fbx", "glb"]:
            if not await bake_animation("res://animations/" + file_name, output, file_name.get_basename()):
                get_tree().quit(1)
                return
    preflight = false
    var count := 0
    for file_name in files:
        if file_name.get_extension().to_lower() not in ["fbx", "glb"]:
            continue
        if not await bake_animation("res://animations/" + file_name, output, file_name.get_basename()):
            get_tree().quit(1)
            return
        count += 1
    get_tree().quit(0 if count > 0 else 1)

func bake_animation(path: String, output: String, asset_name: String) -> bool:
    var resource := load(path) as PackedScene
    if resource == null:
        push_error("Cannot load " + path)
        return false
    var character := resource.instantiate() as Node3D
    if character == null:
        return false
    var viewport := SubViewport.new()
    viewport.size = Vector2i(frame_size, frame_size)
    viewport.transparent_bg = true
    viewport.own_world_3d = true
    viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
    add_child(viewport)
    viewport.add_child(character)
    var light := DirectionalLight3D.new()
    light.rotation_degrees = Vector3(-35, 45, 0)
    viewport.add_child(light)
    var environment := WorldEnvironment.new()
    environment.environment = Environment.new()
    environment.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    environment.environment.ambient_light_color = Color(0.4, 0.4, 0.5)
    viewport.add_child(environment)
    var camera := Camera3D.new()
    camera.projection = Camera3D.PROJECTION_ORTHOGONAL
    camera.size = 2.0
    camera.position = Vector3(0, 0.9, 3.0)
    viewport.add_child(camera)
    camera.make_current()
    var player: AnimationPlayer = null
    var stack: Array[Node] = [character]
    while not stack.is_empty():
        var node: Node = stack.pop_back()
        if node is AnimationPlayer:
            player = node as AnimationPlayer
            break
        stack.append_array(node.get_children())
    if player == null:
        push_error("No AnimationPlayer: " + path)
        viewport.queue_free()
        return false
    var equipment_helper
    var equipment_mounts := {}
    var usage := {}
    if FileAccess.file_exists("res://equipment.json"):
        var config: Dictionary=JSON.parse_string(FileAccess.get_file_as_string("res://equipment.json"))
        var nodes: Array[Node]=[character]
        var skeleton: Skeleton3D
        while not nodes.is_empty():
            var node: Node=nodes.pop_back()
            if node is Skeleton3D: skeleton=node
            nodes.append_array(node.get_children())
        if skeleton==null or skeleton.find_bone(config.bone)<0:
            push_error("Missing equipment hand bone")
            viewport.queue_free()
            return false
        equipment_helper = load("res://equipment_runtime.gd")
        if FileAccess.file_exists("res://equipment_usage.json"):
            usage = JSON.parse_string(FileAccess.get_file_as_string("res://equipment_usage.json"))
            equipment_mounts = equipment_helper.usage_setup(skeleton, config, usage)
        else:
            var attachment = equipment_helper.attach(skeleton,config)
            if attachment != null: equipment_mounts.hand = attachment
        if equipment_mounts.is_empty():
            push_error("Could not load equipment weapon")
            viewport.queue_free()
            return false
    var selected := ""
    var length := 0.0
    for name in player.get_animation_list():
        var clip := player.get_animation(name)
        if name != "RESET" and _has_motion(clip) and clip.length > length:
            selected = name
            length = clip.length
    if selected.is_empty():
        push_error("No usable animation: " + path)
        viewport.queue_free()
        return false
    frame_count = clampi(int(ceil(length * target_fps)), 8, 120)
    # Use restrained, texture-driven shading; tiny normal/highlight changes should not dominate.
    var material_nodes: Array[Node] = [character]
    while not material_nodes.is_empty():
        var mesh_node: Node = material_nodes.pop_back()
        if mesh_node is MeshInstance3D and mesh_node.mesh != null:
            for surface in range(mesh_node.mesh.get_surface_count()):
                var original: Material = mesh_node.get_active_material(surface)
                if original is BaseMaterial3D:
                    var flat := original.duplicate() as BaseMaterial3D
                    flat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
                    flat.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR
                    mesh_node.set_surface_override_material(surface, flat)
        material_nodes.append_array(mesh_node.get_children())
    # Start the selected clip before seeking; freeze automatic time advancement.
    player.play(selected)
    player.advance(0.0)
    player.pause()
    await get_tree().process_frame
    # Frame imported geometry in world space; Mixamo exports need not use meter-sized bounds.
    var angle := PI / 2.0 if view == "side" else PI / 4.0 if view == "three_quarter" else 0.0
    var screen_right := Vector3(cos(angle), 0, -sin(angle))
    var screen_bounds := Rect2()
    var found_screen := false
    var bounds := AABB()
    var found_bounds := false
    # Skinning may move vertices well outside the imported bind-pose AABB.
    # Use deformed geometry across the sampled clip to keep one stable framing.
    for sample in range(frame_count):
        player.seek(float(sample) / frame_count * length, true)
        if not usage.is_empty(): equipment_helper.usage_apply(equipment_mounts,usage,asset_name,float(sample)/frame_count)
        await get_tree().process_frame
        await RenderingServer.frame_post_draw
        var meshes: Array[Node] = [character]
        while not meshes.is_empty():
            var item: Node = meshes.pop_back()
            if item is MeshInstance3D and item.mesh != null and item.is_visible_in_tree():
                var posed: ArrayMesh = item.bake_mesh_from_current_skeleton_pose() if item.skin != null else null
                var local_bounds: AABB = posed.get_aabb() if posed != null else item.get_aabb()
                # Project each posed box before merging: camera depth must not set sprite scale.
                var projected := project_bounds(local_bounds, item.global_transform, screen_right)
                screen_bounds = screen_bounds.merge(projected) if found_screen else projected
                found_screen = true
                var box: AABB = item.global_transform * local_bounds
                bounds = bounds.merge(box) if found_bounds else box
                found_bounds = true
            meshes.append_array(item.get_children())
    if not found_bounds:
        push_error("No mesh bounds: " + path)
        viewport.queue_free()
        return false
    if preflight:
        shared_bounds = shared_bounds.merge(bounds) if has_shared_bounds else bounds
        has_shared_bounds = true
        shared_screen = shared_screen.merge(screen_bounds) if has_shared_screen else screen_bounds
        has_shared_screen = true
        viewport.queue_free()
        await get_tree().process_frame
        return true
    bounds = shared_bounds
    var center := bounds.get_center()
    var extent := maxf(maxf(bounds.size.x, bounds.size.y), bounds.size.z)
    var screen_center := shared_screen.get_center()
    center += screen_right * (screen_center.x - center.dot(screen_right))
    center.y = screen_center.y
    camera.size = maxf(maxf(shared_screen.size.x, shared_screen.size.y) * 1.12, 0.0001)
    camera.position = center + Vector3(sin(angle), 0, cos(angle)) * maxf(extent * 3.0, 0.001)
    camera.near = maxf(extent * 0.001, 0.000001)
    camera.far = maxf(extent * 10.0, 0.01)
    camera.look_at(center)
    print("Framing ", path, " bounds=", bounds)
    await RenderingServer.frame_post_draw
    var sheet := Image.create(frame_size * frame_count, frame_size, false, Image.FORMAT_RGBA8)
    for i in range(frame_count):
        player.seek(float(i) / frame_count * length, true)
        if not usage.is_empty(): equipment_helper.usage_apply(equipment_mounts,usage,asset_name,float(i)/frame_count)
        await get_tree().process_frame
        await RenderingServer.frame_post_draw
        var frame := viewport.get_texture().get_image()
        if frame == null or frame.is_empty():
            push_error("Renderer returned no image: " + path)
            viewport.queue_free()
            return false
        frame.convert(Image.FORMAT_RGBA8)
        sheet.blit_rect(frame, Rect2i(0, 0, frame_size, frame_size), Vector2i(i * frame_size, 0))
    var error := sheet.save_png(output.path_join(asset_name + "_spritesheet.png"))
    viewport.queue_free()
    var metadata := FileAccess.open(output.path_join(asset_name + "_render.json"), FileAccess.WRITE)
    if metadata == null:
        return false
    metadata.store_string(JSON.stringify({"duration_seconds": length, "frame_count": frame_count,
        "fps": float(frame_count) / length, "clip": selected, "view": view,
        "camera": {"size": camera.size, "center": [center.x,center.y,center.z], "view": view},
        "render_style": "unshaded_texture", "framing": "shared_batch_projected_bounds", "frame_width": frame_size, "frame_height": frame_size}, "  "))
    metadata.close()
    if error != OK:
        push_error("Could not save sprite sheet: " + str(error))
        return false
    print("Baked ", path, " clip=", selected)
    return true

func _has_motion(clip: Animation) -> bool:
    # Mixamo can include a longer static bind-pose clip alongside the real action.
    for track in range(clip.get_track_count()):
        if clip.track_get_type(track) not in [Animation.TYPE_POSITION_3D, Animation.TYPE_ROTATION_3D, Animation.TYPE_SCALE_3D, Animation.TYPE_BLEND_SHAPE, Animation.TYPE_VALUE]:
            continue
        var count := clip.track_get_key_count(track)
        if count < 2:
            continue
        var first: Variant = clip.track_get_key_value(track, 0)
        for key in range(1, count):
            if clip.track_get_key_value(track, key) != first:
                return true
    return false

static func project_bounds(box: AABB, transform: Transform3D, screen_right: Vector3) -> Rect2:
    var result := Rect2()
    for corner in range(8):
        var point := transform * box.get_endpoint(corner)
        var screen := Vector2(point.dot(screen_right), point.y)
        result = result.expand(screen) if corner > 0 else Rect2(screen, Vector2.ZERO)
    return result
