extends SceneTree
## Low-cost motion probe. No render, no publication, no frame-count truncation.
func _initialize() -> void:
    run.call_deferred()

func run() -> void:
    var args := OS.get_cmdline_user_args()
    if args.size() != 1:
        quit(1)
        return
    var reports := {}
    for filename in DirAccess.get_files_at("res://animations"):
        if filename.get_extension().to_lower() not in ["fbx", "glb"]: continue
        var scene := (load("res://animations/" + filename) as PackedScene).instantiate()
        root.add_child(scene)
        var player: AnimationPlayer
        var skeleton: Skeleton3D
        var nodes: Array[Node] = [scene]
        while not nodes.is_empty():
            var item: Node = nodes.pop_back()
            if item is AnimationPlayer: player = item
            if item is Skeleton3D: skeleton = item
            nodes.append_array(item.get_children())
        if player == null or skeleton == null:
            push_error("Motion sampling requires an animated skeleton: " + filename)
            quit(1)
            return
        var selected := ""
        var duration := 0.0
        var helper = load("res://baker.gd").new()
        for animation_name in player.get_animation_list():
            var clip := player.get_animation(animation_name)
            if animation_name != "RESET" and helper._has_motion(clip) and clip.length > duration:
                selected = animation_name
                duration = clip.length
        helper.free()
        if selected.is_empty() or duration > 120.0:
            push_error("Missing motion or diagnostic clip exceeds 120 seconds")
            quit(1)
            return
        player.play(selected)
        player.advance(0.0)
        player.pause()
        await process_frame
        # Bone origins plus short orientation probes capture twist as well as translation.
        var rest := []
        var labels := []
        var height := 0.0
        var low := INF
        var high := -INF
        for bone in range(skeleton.get_bone_count()):
            var tr := skeleton.global_transform * skeleton.get_bone_global_rest(bone)
            low = minf(low, tr.origin.y)
            high = maxf(high, tr.origin.y)
            rest.append(tr.origin)
            labels.append(str(skeleton.get_bone_name(bone)))
        height = high-low
        if height <= 0.000001:
            quit(1)
            return
        var markers := []
        for bone in range(skeleton.get_bone_count()):
            var basis := (skeleton.global_transform * skeleton.get_bone_global_rest(bone)).basis
            markers.append(height * 0.05 / maxf(basis.x.length(), 0.000001))
        var weapon_points := []
        var equipment := {}
        var usage := {}
        var runtime
        if FileAccess.file_exists("res://equipment.json"):
            equipment = JSON.parse_string(FileAccess.get_file_as_string("res://equipment.json"))
            runtime = load("res://equipment_runtime.gd")
            if FileAccess.file_exists("res://equipment_usage.json"):
                usage = JSON.parse_string(FileAccess.get_file_as_string("res://equipment_usage.json"))
            var model: Node3D = runtime.weapon_model(equipment)
            if model == null:
                quit(1)
                return
            var pending := [{"node": model, "transform": Transform3D.IDENTITY}]
            while not pending.is_empty():
                var entry: Dictionary = pending.pop_back()
                var node: Node3D = entry.node
                var transform: Transform3D = entry.transform * node.transform
                if node is MeshInstance3D and node.mesh != null:
                    var box: AABB = node.get_aabb()
                    for i in range(8): weapon_points.append(transform * box.get_endpoint(i))
                for child in node.get_children():
                    if child is Node3D: pending.append({"node":child,"transform":transform})
            model.free()
        var times := []
        var poses := []
        var count := int(ceil(duration * 120.0))
        for sample in range(count+1):
            var t := minf(float(sample)/120.0,duration)
            player.seek(t,true)
            skeleton.force_update_all_bone_transforms()
            var points := []
            for bone in range(skeleton.get_bone_count()):
                var transform := skeleton.global_transform * skeleton.get_bone_global_pose(bone)
                for offset in [Vector3.ZERO,Vector3.RIGHT*markers[bone],Vector3.UP*markers[bone],Vector3.BACK*markers[bone]]:
                    var point: Vector3 = transform * offset
                    points.append([point.x,point.y,point.z])
            if not equipment.is_empty():
                var state: String = runtime.usage_state(usage,filename.get_basename(),t/duration) if not usage.is_empty() else "hand"
                var tr := Transform3D.IDENTITY
                if state == "hand" or state == "hidden":
                    var bone := skeleton.find_bone(equipment.bone)
                    var hand: Transform3D = runtime.frame(equipment.hand_points)
                    var grip: Transform3D = runtime.frame(equipment.weapon_points)
                    var basis: Basis = hand.basis * grip.basis.inverse() * float(equipment.source_units_per_meter) * float(equipment.weapon_scale)
                    tr = skeleton.global_transform * skeleton.get_bone_global_pose(bone) * Transform3D(basis,hand.origin-basis*grip.origin)
                else:
                    var mount: Dictionary = usage.mounts[state]
                    var rotation: Array = mount.rotation
                    var basis := Basis.from_euler(Vector3(deg_to_rad(rotation[0]),deg_to_rad(rotation[1]),deg_to_rad(rotation[2]))) * float(equipment.source_units_per_meter) * float(equipment.weapon_scale)
                    var grip: Transform3D = runtime.frame(equipment.weapon_points)
                    var position: Array = mount.position
                    var origin := Vector3(position[0],position[1],position[2])*float(equipment.source_units_per_meter)
                    tr = skeleton.global_transform * skeleton.get_bone_global_pose(skeleton.find_bone(mount.bone)) * Transform3D(basis,origin-basis*grip.origin)
                # Hidden states have no visible trajectory; null markers are masked by analysis.
                for local in weapon_points:
                    var point: Vector3 = tr * local
                    points.append([point.x,point.y,point.z] if state != "hidden" else null)
            times.append(t)
            poses.append(points)
        reports[filename.get_basename()] = {"duration":duration,"probe_hz":120,"times":times,"positions":poses,"bone_names":labels,"rest_height":height,"weapon_marker_count":weapon_points.size()}
        scene.free()
        await process_frame
    var output := FileAccess.open(args[0],FileAccess.WRITE)
    output.store_string(JSON.stringify(reports))
    output.close()
    quit(0 if not reports.is_empty() else 1)
