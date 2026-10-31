extends SceneTree
func _initialize() -> void:
    run.call_deferred()
func run() -> void:
    var runtime = load("res://equipment_runtime.gd")
    var usage: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://equipment_usage.json"))
    var config: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://equipment.json"))
    var skeleton := Skeleton3D.new()
    root.add_child(skeleton)
    for bone in [config.bone,"mixamorig_Spine2","mixamorig_Hips"]: skeleton.add_bone(bone)
    var mounts: Dictionary = runtime.usage_setup(skeleton,config,usage)
    assert(mounts.size()==3)
    for pair in [[0.0,"waist"],[0.25,"hand"],[0.5,"back"],[0.75,"hidden"],[0.1,"waist"]]:
        runtime.usage_apply(mounts,usage,"great_sword_jump_attack",pair[0])
        for key in mounts: assert(mounts[key].visible==(key==pair[1]),"State seek is not deterministic")
    var grip = runtime.frame(config.weapon_points).origin
    for state in ["back","waist"]:
        var model: Node3D = mounts[state].get_child(0)
        var p: Array = usage.mounts[state].position
        var expected := Vector3(p[0],p[1],p[2])*float(config.source_units_per_meter)
        assert((model.transform*grip).is_equal_approx(expected),"Stored grip does not align with mount")
    print("USAGE_RUNTIME_QA_PASS")
    quit()
