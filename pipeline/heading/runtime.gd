extends RefCounted

static func record(filename: String) -> Dictionary:
    if not FileAccess.file_exists("res://heading.json"): return {"degrees":0.0,"status":"legacy"}
    var data = JSON.parse_string(FileAccess.get_file_as_string("res://heading.json"))
    var value: Dictionary = data.get(filename, {"degrees":0.0,"status":"legacy"}).duplicate(true)
    if value.get("status") != "confirmed": value["degrees"] = 0.0
    return value

static func wrap_model(model: Node3D, degrees: float) -> Node3D:
    var parent := model.get_parent()
    var wrapper := Node3D.new()
    wrapper.name = "StudioHeading"
    parent.add_child(wrapper)
    model.reparent(wrapper, false)
    wrapper.rotation_degrees.y = degrees
    return wrapper

static func estimate(player: AnimationPlayer, skeleton: Skeleton3D) -> Dictionary:
    var selected := ""
    var duration := 0.0
    for key in player.get_animation_list():
        if key != "RESET" and has_motion(player.get_animation(key)) and player.get_animation(key).length > duration:
            selected = key
            duration = player.get_animation(key).length
    var record := {"degrees":0.0,"estimated_degrees":0.0,"status":"uncertain","reason":"缺少可识别骨骼；保留原动作朝向"}
    if selected.is_empty(): return record
    var li := skeleton.find_bone("mixamorig_LeftUpLeg")
    var ri := skeleton.find_bone("mixamorig_RightUpLeg")
    var ls := skeleton.find_bone("mixamorig_LeftShoulder")
    var rs := skeleton.find_bone("mixamorig_RightShoulder")
    if mini(mini(li,ri),mini(ls,rs)) < 0: return record
    var angles := []
    var sum := Vector2.ZERO
    player.play(selected)
    for i in range(48):
        player.seek(duration * float(i) / 48.0, true)
        skeleton.force_update_all_bone_transforms()
        var hip: Vector3 = skeleton.global_basis * (skeleton.get_bone_global_pose(li).origin - skeleton.get_bone_global_pose(ri).origin)
        var shoulder: Vector3 = skeleton.global_basis * (skeleton.get_bone_global_pose(ls).origin - skeleton.get_bone_global_pose(rs).origin)
        var lateral := Vector2(hip.x, -hip.z).normalized() * 0.8 + Vector2(shoulder.x, -shoulder.z).normalized() * 0.2
        if lateral.length() < 0.1: continue
        lateral = lateral.normalized()
        angles.append(lateral.angle())
        sum += lateral
    if angles.is_empty(): return record
    var mean := sum.angle()
    var deviation := 0.0
    for angle in angles: deviation = maxf(deviation, absf(wrapf(angle - mean, -PI, PI)))
    var reliable := sum.length() / angles.size() > 0.9 and rad_to_deg(deviation) < 35.0
    var correction := snappedf(-rad_to_deg(mean), 0.1)
    return {"degrees":0.0,"estimated_degrees":correction,
        "status":"suggested" if reliable else "uncertain",
        "reason":"仅供参考；默认保留原动作朝向" if reliable else "动作转向变化明显；保留原动作朝向",
        "spread_degrees":rad_to_deg(deviation),"samples":angles.size(),"method":"hip80_shoulder20_circular_v1"}

static func has_motion(clip: Animation) -> bool:
    for track in range(clip.get_track_count()):
        if clip.track_get_type(track) not in [Animation.TYPE_POSITION_3D, Animation.TYPE_ROTATION_3D, Animation.TYPE_SCALE_3D, Animation.TYPE_BLEND_SHAPE, Animation.TYPE_VALUE]: continue
        if clip.track_get_key_count(track) < 2: continue
        var first: Variant = clip.track_get_key_value(track,0)
        for key in range(1,clip.track_get_key_count(track)):
            if clip.track_get_key_value(track,key) != first: return true
    return false
