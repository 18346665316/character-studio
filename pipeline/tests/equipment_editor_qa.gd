extends SceneTree
## Isolated test project only. Does not publish a production equipment receipt.
func _initialize() -> void:
    _run.call_deferred()

func require(value: bool, message: String) -> bool:
    if not value:
        push_error(message)
        quit(1)
    return value

func _run() -> void:
    var host = load("res://review.tscn").instantiate()
    root.add_child(host)
    for i in range(12): await process_frame
    var editor
    for child in host.get_children():
        if child.get_script()==load("res://equipment_editor.gd"): editor=child
    if not require(editor!=null,"Editor did not start"): return
    host.animation_player.stop()
    host.skeleton.reset_bone_poses()
    editor.neutral=true
    await process_frame
    editor._focus_hand()
    editor.config.hand_points=[]
    editor._refresh()
    var finger=host.skeleton.find_bone("mixamorig_RightHandMiddle1")
    var hand=editor._hand_transform()
    var target=hand.origin
    if finger>=0:
        target=hand.origin.lerp((host.skeleton.global_transform*host.skeleton.get_bone_global_pose(finger)).origin,0.65)
    for index in range(3):
        editor._arm(index,"hand")
        var point=target
        if index==1: point+=host.camera.global_basis.y*0.07
        if index==2: point+=host.camera.global_basis.x*0.05
        var event=InputEventMouseButton.new()
        event.button_index=MOUSE_BUTTON_LEFT
        event.pressed=true
        event.position=host.camera.unproject_position(point)
        editor._unhandled_input(event)
        if not require(editor.config.hand_points.size()==index+1,"Hand surface picking failed: "+editor.status.text): return
    if not require(editor.attached!=null,"Weapon did not attach"): return
    editor._focus_weapon()
    editor._arm(0,"weapon")
    var event=InputEventMouseButton.new()
    event.button_index=MOUSE_BUTTON_LEFT
    event.pressed=true
    event.position=host.camera.unproject_position(Vector3.ZERO)
    editor._unhandled_input(event)
    if not require(editor.pending==-1,"Weapon surface picking failed"): return
    editor._show_step(0)
    await process_frame
    var original_grip=editor.config.hand_points.duplicate(true)
    var press=InputEventMouseButton.new()
    press.button_index=MOUSE_BUTTON_LEFT
    press.pressed=true
    press.position=host.camera.unproject_position(editor.markers[0].global_position)
    editor._unhandled_input(press)
    if not require(editor.dragging_point==0,"Grip handle cannot be selected"): return
    var motion=InputEventMouseMotion.new()
    motion.position=press.position+Vector2(15,0)
    editor._input(motion)
    press.pressed=false
    editor._input(press)
    if not require(editor.config.hand_points!=original_grip,"Grip dragging had no effect"): return
    editor._undo()
    if not require(editor.config.hand_points==original_grip,"Undo did not restore the grip"): return
    editor._show_step(1)
    editor._show_step(2)
    editor._show_step(0)
    editor._show_step(2)
    await process_frame
    var weapon=editor.attached.get_child(0)
    var relative=weapon.transform
    var before=weapon.global_position
    host._play_action("running")
    host.animation_player.seek(0.3,true)
    for i in range(3): await process_frame
    if not require(relative.is_equal_approx(weapon.transform),"Grip shifted relative to hand attachment"): return
    if not require(before.distance_to(weapon.global_position)>0.0001,"Weapon did not follow animated hand"): return
    editor._pause()
    await RenderingServer.frame_post_draw
    root.get_texture().get_image().save_png("res://../qa-preview.png")
    var report=FileAccess.open("res://../qa-results.json",FileAccess.WRITE)
    report.store_string(JSON.stringify({"hand_surface_pick":true,"weapon_surface_pick":true,"constant_grip":true,"follows_motion":true,"drag_handle":true,"undo":true,"step_navigation":true}))
    report.close()
    editor._save()
