extends SceneTree
## Headless interaction-state checks, without claiming visual QA.
func _initialize() -> void:
    _run.call_deferred()

func _run() -> void:
    var host=load("res://review.tscn").instantiate()
    root.add_child(host)
    for i in range(5): await process_frame
    var editor
    for child in host.get_children():
        if child.get_script()==load("res://equipment_editor.gd"): editor=child
    if editor==null:
        push_error("Missing editor")
        quit(1)
        return
    var before: Array=editor.config.hand_points.duplicate(true)
    # Send real viewport events, rather than calling editor drag methods directly.
    # A fixed surface isolates input routing from GPU-only skin baking in headless.
    var center: Vector3=editor._hand_transform()*editor._point(0)
    var right: Vector3=host.camera.global_basis.x*0.04
    var up: Vector3=host.camera.global_basis.y*0.04
    editor.hand_faces=PackedVector3Array([center-right-up,center+right-up,center+right+up,center-right-up,center+right+up,center-right+up])
    editor.surface_dirty=false
    var press_drag := InputEventMouseButton.new()
    press_drag.button_index=MOUSE_BUTTON_LEFT
    press_drag.pressed=true
    press_drag.position=host.camera.unproject_position(center)
    root.push_input(press_drag,true)
    await process_frame
    assert(editor.dragging_point==0,"Real viewport press must start grip drag")
    var drag := InputEventMouseMotion.new()
    drag.button_mask=MOUSE_BUTTON_MASK_LEFT
    drag.position=press_drag.position+Vector2(18,0)
    root.push_input(drag,true)
    await process_frame
    assert(editor.config.hand_points!=before,"Real viewport motion must move grip on surface")
    press_drag.pressed=false
    press_drag.position=drag.position
    root.push_input(press_drag,true)
    await process_frame
    assert(editor.dragging_point==-1,"Releasing viewport press must end drag")
    editor._undo()
    assert(editor.config.hand_points==before,"Drag undo must restore grip")
    var key := InputEventKey.new()
    key.pressed=true
    key.keycode=KEY_RIGHT
    editor._input(key)
    assert(editor.config.hand_points!=before,"Keyboard nudge must change the grip")
    var first: float=(editor._point(0)-Vector3(before[0][0],before[0][1],before[0][2])).length()
    editor._undo()
    assert(editor.config.hand_points==before,"Undo must restore original points")
    key.shift_pressed=true
    editor._input(key)
    var fine: float=(editor._point(0)-Vector3(before[0][0],before[0][1],before[0][2])).length()
    assert(abs(first/fine-4)<0.01,"Shift must use quarter-sized increments")
    editor._show_step(1)
    var grip: Vector3=editor._point(0)
    var length: float=(editor._point(1)-grip).length()
    var side_length: float=(editor._point(2)-grip).length()
    var scale_before: float=editor.config.weapon_scale
    editor._move_point(1,grip+Vector3(0.25,0.15,0.13)*editor.config.source_units_per_meter)
    assert(editor._point(0).is_equal_approx(grip),"Direction adjustment must preserve grip")
    assert(is_equal_approx((editor._point(1)-grip).length(),length),"Direction handle must retain its radius")
    assert(is_equal_approx((editor._point(2)-grip).length(),side_length),"Blade side must rotate rigidly with tip")
    assert(editor.config.weapon_scale==scale_before,"Direction adjustment must preserve weapon size")
    var before_turn: Array=editor.config.hand_points.duplicate(true)
    editor.look_mode=true
    var press := InputEventMouseButton.new()
    press.button_index=MOUSE_BUTTON_LEFT
    press.pressed=true
    press.position=Vector2(700,400)
    editor._input(press)
    var yaw_before: float=host.yaw
    var motion := InputEventMouseMotion.new()
    motion.relative=Vector2(30,10)
    editor._input(motion)
    assert(host.yaw!=yaw_before,"Single-button viewing mode must orbit")
    assert(editor.config.hand_points==before_turn,"Viewing mode must not edit points")
    press.pressed=false
    editor._input(press)
    editor.look_mode=false
    assert(editor._surface_at(Vector2(-10000,-10000))==null,"Off-mesh surface drag must not move the grip")
    editor.selected_point=2
    var old_axis: Array=editor.config.hand_points[1].duplicate()
    editor._input(key)
    assert(editor.config.hand_points[1]==old_axis,"Nudging blade side must not move tip")
    editor._show_step(2)
    editor._show_step(0)
    editor._show_step(2)
    assert(is_instance_valid(host.timeline),"Timeline must survive repeated step changes")
    print("EQUIPMENT_CONTROLS_OK real viewport grip press/move/release, drag undo, fixed grip, constant radius, constant size, rigid orientation, single-button orbit, mode isolation, navigation")
    quit(0)
