extends SceneTree

func _initialize() -> void:
    var baker := preload("res://baker.gd").new()
    var static_clip := Animation.new()
    var moving_clip := Animation.new()
    for clip in [static_clip, moving_clip]:
        var track: int = clip.add_track(Animation.TYPE_POSITION_3D)
        clip.position_track_insert_key(track, 0.0, Vector3.ZERO)
        clip.position_track_insert_key(track, 0.5, Vector3.ZERO if clip == static_clip else Vector3.ONE)
    var passed: bool = not baker._has_motion(static_clip) and baker._has_motion(moving_clip)
    baker.free()
    if not passed:
        push_error("Static bind-pose clips must be excluded from motion selection")
    else:
        print("Clip selection regression passed")
    quit(0 if passed else 1)
