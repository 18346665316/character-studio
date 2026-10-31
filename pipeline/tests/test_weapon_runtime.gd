# Isolated QA project: equipment_runtime.gd and an imported vertex-color weapon.glb.
extends SceneTree
func _initialize() -> void:
    run.call_deferred()
func run() -> void:
    var runtime=load("res://equipment_runtime.gd")
    var skeleton:=Skeleton3D.new()
    root.add_child(skeleton)
    skeleton.add_bone("mixamorig_RightHand")
    var config={"schema":2,"weapon":"asset","weapon_length":0.85,"bone":"mixamorig_RightHand","source_units_per_meter":1.0,"weapon_scale":1.0,"hand_points":[[0,0,0],[0,0.1,0],[0.1,0,0]],"weapon_points":[[0,0.17,0],[0,0.68,0],[0.085,0.17,0]]}
    var attached=runtime.attach(skeleton,config)
    assert(attached!=null,"custom weapon did not attach")
    var weapon=attached.get_child(0)
    var model=weapon.get_child(0)
    assert(model.scale.is_equal_approx(Vector3.ONE*0.85),"weapon length not applied")
    var grip=Vector3(0,0.17,0)
    assert((weapon.transform*grip).is_equal_approx(Vector3.ZERO),"grip not aligned to hand")
    var local_transform=weapon.transform
    skeleton.set_bone_pose_position(0,Vector3(0.3,0.1,0.2))
    await process_frame
    await process_frame
    assert(weapon.transform.is_equal_approx(local_transform),"weapon slipped from attachment")
    var stack:Array[Node]=[model]
    var meshes=0
    while not stack.is_empty():
        var item:Node=stack.pop_back()
        if item is MeshInstance3D:
            meshes+=1
            assert(item.get_active_material(0).vertex_color_use_as_albedo,"vertex color lost")
        stack.append_array(item.get_children())
    assert(meshes>0,"no imported weapon geometry")
    print("WEAPON_RUNTIME_QA_PASS")
    quit()
