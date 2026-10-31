extends SceneTree

func _initialize():
    call_deferred("run")

func fixture(turning: bool) -> Dictionary:
    var model := Node3D.new()
    root.add_child(model)
    var skeleton := Skeleton3D.new()
    skeleton.name = "Skeleton3D"
    model.add_child(skeleton)
    var player := AnimationPlayer.new()
    model.add_child(player)
    var clip := Animation.new()
    clip.length = 1.0
    var names := ["mixamorig_LeftUpLeg","mixamorig_RightUpLeg","mixamorig_LeftShoulder","mixamorig_RightShoulder"]
    for i in range(4):
        skeleton.add_bone(names[i])
        var track := clip.add_track(Animation.TYPE_POSITION_3D)
        clip.track_set_path(track,NodePath("Skeleton3D:" + names[i]))
        for k in range(49):
            var time := float(k)/48.0
            var degrees := time*180.0 if turning else 40.0 + sin(time*TAU)*5.0 + (20.0 if i >= 2 else 0.0)
            var sign_value := 1.0 if i % 2 == 0 else -1.0
            var lateral := Vector3(cos(deg_to_rad(degrees)),0,-sin(deg_to_rad(degrees)))
            clip.position_track_insert_key(track,time,lateral*sign_value + Vector3(0,1 if i>=2 else 0,0))
    var library := AnimationLibrary.new()
    library.add_animation("motion",clip)
    player.add_animation_library("",library)
    return {"model":model,"skeleton":skeleton,"player":player}

func run():
    var runtime = load("res://heading_runtime.gd")
    var fixed := fixture(false)
    var record: Dictionary = runtime.estimate(fixed.player,fixed.skeleton)
    assert(record.status == "suggested",str(record))
    assert(float(record.degrees)==0.0,str(record))
    assert(absf(float(record.estimated_degrees)+44.0)<0.2,str(record))
    var wrapper: Node3D = runtime.wrap_model(fixed.model,record.estimated_degrees)
    var corrected: Dictionary = runtime.estimate(fixed.player,fixed.skeleton)
    assert(absf(float(corrected.estimated_degrees))<0.2,str(corrected))
    assert(absf(float(corrected.spread_degrees)-float(record.spread_degrees))<0.1)
    wrapper.free()
    var turning := fixture(true)
    var uncertain: Dictionary = runtime.estimate(turning.player,turning.skeleton)
    assert(uncertain.status == "uncertain",str(uncertain))
    assert(float(uncertain.degrees)==0.0)
    turning.model.free()
    print("Heading estimate, correction sign, preserved sway and turning guard passed")
    quit()
