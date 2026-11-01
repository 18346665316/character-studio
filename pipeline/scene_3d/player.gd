extends CharacterBody3D

const WALK_SPEED := 1.8
const MOVE_SPEEDS := {"walk":1.8,"jogging":2.8,"run":3.8,"fast_run":5.2}
var visual: Node3D
var animator: AnimationPlayer
var current_motion := ""
var moving := false
var running := false
var travel := 0.0
var camera_yaw := 0.0
var locomotion := "fast_run"
var action := ""
var action_time := 0.0
var action_duration := 0.0
var jumped := false
var attacked := false
var peak_height := 0.0
var durations := {}
var weapon: Node3D
var jump_curves := {}
var action_origin_y := 0.0

func _ready() -> void:
    name = "Player"
    var shape := CollisionShape3D.new()
    var capsule := CapsuleShape3D.new()
    capsule.radius = 0.27
    capsule.height = 1.7
    shape.shape = capsule
    shape.position.y = 0.85
    add_child(shape)
    var heading := Node3D.new()
    heading.name = "Facing"
    add_child(heading)
    visual = heading
    var model := load("res://assets/walk.fbx").instantiate() as Node3D
    heading.add_child(model)
    animator = model.find_children("*", "AnimationPlayer", true, false)[0]
    var mesh: MeshInstance3D = model.find_children("*", "MeshInstance3D", true, false)[0]
    var bounds := mesh.global_transform * mesh.get_aabb()
    var factor := 1.7 / bounds.size.y
    model.scale *= factor
    model.position -= Vector3(bounds.get_center().x, bounds.position.y, bounds.get_center().z) * factor
    var library := AnimationLibrary.new()
    for motion in ["walk", "jogging", "run", "fast_run", "standing_jump", "great_sword_jump_attack"]:
        var source := load("res://assets/" + motion + ".fbx").instantiate() as Node3D
        var source_player: AnimationPlayer = source.find_children("*", "AnimationPlayer", true, false)[0]
        var clip: Animation
        for key in source_player.get_animation_list():
            if key != "RESET" and (clip == null or source_player.get_animation(key).length > clip.length):
                clip = source_player.get_animation(key)
        clip = clip.duplicate(true)
        clip.loop_mode = Animation.LOOP_NONE if motion in ["standing_jump", "great_sword_jump_attack"] else Animation.LOOP_LINEAR
        durations[motion] = clip.length
        # Separate authored airborne height from the skinned pose, so collision and
        # animation share timing rather than adding a second ballistic jump.
        var heights := []
        # Gameplay controller owns horizontal travel. Keep vertical bounce and rotations.
        for track in range(clip.get_track_count()):
            if clip.track_get_type(track) == Animation.TYPE_POSITION_3D and str(clip.track_get_path(track)).ends_with(":mixamorig_Hips"):
                var origin: Vector3 = clip.track_get_key_value(track, 0)
                if motion in ["standing_jump", "great_sword_jump_attack"]:
                    for sample in range(241):
                        var value: Vector3 = clip.position_track_interpolate(track,clip.length*float(sample)/240.0)
                        heights.append(maxf(0.0,(value.y-origin.y)*factor))
                for key in range(clip.track_get_key_count(track)):
                    var value: Vector3 = clip.track_get_key_value(track, key)
                    value.x = origin.x
                    value.z = origin.z
                    if motion in ["standing_jump", "great_sword_jump_attack"]: value.y = minf(value.y,origin.y)
                    clip.track_set_key_value(track, key, value)
        if not heights.is_empty():
            # Remove tiny terminal drift so an authored landing can settle on the floor.
            var endpoint := float(heights[-1])
            for sample in range(heights.size()):
                heights[sample] = maxf(0.0,float(heights[sample])-endpoint*float(sample)/float(heights.size()-1))
        jump_curves[motion] = heights
        library.add_animation(motion, clip)
        source.free()
    animator.add_animation_library("game", library)
    for node in model.find_children("*", "MeshInstance3D", true, false):
        for surface in range(node.mesh.get_surface_count()):
            var material = node.get_active_material(surface)
            if material is BaseMaterial3D:
                material = material.duplicate()
                material.metallic = 0.0
                material.roughness = 0.9
                node.set_surface_override_material(surface, material)
    if FileAccess.file_exists("res://equipment.json"):
        var config: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://equipment.json"))
        var skeleton: Skeleton3D = model.find_children("*", "Skeleton3D", true, false)[0]
        weapon = load("res://equipment_runtime.gd").attach(skeleton,config)
    set_motion("walk")
    animator.seek(0.0, true)
    animator.pause()

func set_motion(motion: String) -> void:
    if current_motion != motion or not animator.is_playing():
        animator.play("game/" + motion, 0.15)
        current_motion = motion

func drive(input: Vector2, sprint: bool, delta: float) -> void:
    moving = input.length() > 0.05
    running = sprint and moving
    var direction := Vector3(input.x, 0, input.y).rotated(Vector3.UP, camera_yaw)
    var target_speed: float = MOVE_SPEEDS[locomotion] if running else WALK_SPEED
    velocity.x = move_toward(velocity.x, direction.x * target_speed, 14.0 * delta)
    velocity.z = move_toward(velocity.z, direction.z * target_speed, 14.0 * delta)
    if not action.is_empty():
        action_time += delta
        if action_time >= action_duration and is_on_floor():
            action = ""
        else:
            direction = Vector3.ZERO if action == "great_sword_jump_attack" else direction
            velocity.x = move_toward(velocity.x,0,18*delta) if action == "great_sword_jump_attack" else velocity.x
            velocity.z = move_toward(velocity.z,0,18*delta) if action == "great_sword_jump_attack" else velocity.z
    if not action.is_empty():
        var heights: Array = jump_curves[action]
        if not heights.is_empty():
            var sample := clampf(action_time/action_duration,0,1)*float(heights.size()-1)
            var index := int(sample)
            var height := lerpf(float(heights[index]),float(heights[mini(index+1,heights.size()-1)]),sample-index)
            velocity.y = (action_origin_y+height-position.y)/delta
        elif not is_on_floor(): velocity.y -= 18.0*delta
    elif not is_on_floor(): velocity.y -= 18.0 * delta
    else: velocity.y = -0.1
    peak_height = maxf(peak_height,position.y)
    if not action.is_empty():
        pass
    elif moving:
        # Mixamo character front is +Z; preserve the source's sideways run pose.
        visual.rotation.y = lerp_angle(visual.rotation.y, atan2(direction.x, direction.z), minf(delta * 12, 1))
        set_motion(locomotion if running else "walk")
        animator.speed_scale = 1.0
    else:
        if animator.is_playing():
            animator.play("game/walk", 0.0)
            current_motion = "walk"
            animator.seek(0.0, true)
            animator.pause()
    var before := position
    move_and_slide()
    travel += Vector2(position.x-before.x, position.z-before.z).length()
    if position.y < -8: reset()

func trigger_action(motion: String) -> void:
    if not action.is_empty() or not is_on_floor(): return
    action = motion
    action_time = 0.0
    action_duration = float(durations[motion])
    action_origin_y = position.y
    animator.speed_scale = 1.0
    animator.play("game/"+motion,0.08)
    current_motion = motion
    if motion == "standing_jump": jumped = true
    else: attacked = true

func reset() -> void:
    action = ""
    action_time = 1.0
    if animator:
        animator.play("game/walk",0.0)
        animator.seek(0,true)
        animator.pause()
        current_motion = "walk"
    position = Vector3(0, 0.1, 3)
    velocity = Vector3.ZERO
