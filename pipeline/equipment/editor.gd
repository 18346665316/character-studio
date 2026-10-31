extends Node
const Runtime = preload("res://equipment_runtime.gd")
var viewer
var config := {}
var bone := -1
var mode := "hand"
var pending := -1
var weapon: Node3D
var attached: Node3D
var markers: Array[MeshInstance3D] = []
var status: Label
var saved := false
var scale_input: SpinBox
var hand_choice: OptionButton
var neutral := false
var step := 0
var body: VBoxContainer
var heading: Label
var subtitle: Label
var next_button: Button
var back_button: Button
var step_buttons: Array[Button] = []
var dragging_point := -1
var drag_plane := Plane()
var undo_stack: Array = []
var axis_lines: MeshInstance3D
var previewed := false
var play_toggle: Button
var turn_slider: HSlider
var turn_value := 0.0
var selected_point := 0
var drag_start_mouse := Vector2.ZERO
var drag_start_world := Vector3.ZERO
var point_choices: Array[Button] = []
var look_mode := false
var looking := false
var look_button: Button
var hand_faces := PackedVector3Array()
var surface_dirty := true

func setup(host) -> void:
    viewer=host
    config=viewer.spec.equipment_draft.duplicate(true)
    bone=viewer.skeleton.find_bone(config.bone)
    # Use a single guided panel instead of stacking the inspection and editor UIs.
    for child in viewer.get_children():
        if child is CanvasLayer: child.hide()
    if config.hand_points.is_empty(): _default_hand()
    _ui()
    viewer.playing=false
    viewer.animation_player.speed_scale=0
    viewer.play_button.text="播放"
    _focus_hand()
    _refresh()
    _show_step(0)
    # Prefer a sword attack over locomotion when checking an equipped character.
    for index in range(viewer.choice.item_count):
        var action: String=viewer.choice.get_item_text(index)
        if "slash" in action.to_lower() or "attack" in action.to_lower():
            viewer.choice.select(index)
            break

func _ui() -> void:
    var layer := CanvasLayer.new()
    add_child(layer)
    var panel := PanelContainer.new()
    panel.position=Vector2(24,24)
    panel.custom_minimum_size=Vector2(325,0)
    layer.add_child(panel)
    var overlay=load("res://equipment_handles.gd").new()
    overlay.editor=self
    layer.add_child(overlay)
    var style := StyleBoxFlat.new()
    style.bg_color=Color(0.04,0.07,0.08,0.96)
    style.set_corner_radius_all(14)
    style.content_margin_left=20
    style.content_margin_right=20
    style.content_margin_top=20
    style.content_margin_bottom=20
    panel.add_theme_stylebox_override("panel",style)
    var col := VBoxContainer.new()
    col.add_theme_constant_override("separation",12)
    panel.add_child(col)
    col.add_child(viewer._label("STUDIO / EQUIPMENT",13))
    col.add_child(viewer._label("让武器握在手中",25))
    var tabs := HBoxContainer.new()
    for i in range(3):
        var index := i
        var tab: Button=viewer._button(["① 握点","② 朝向","③ 检查"][i],func():_show_step(index))
        tab.size_flags_horizontal=Control.SIZE_EXPAND_FILL
        step_buttons.append(tab)
        tabs.add_child(tab)
    col.add_child(tabs)
    heading=viewer._label("",20)
    subtitle=viewer._label("",14)
    subtitle.autowrap_mode=TextServer.AUTOWRAP_WORD_SMART
    subtitle.custom_minimum_size.x=280
    col.add_child(heading)
    col.add_child(subtitle)
    body=VBoxContainer.new()
    body.add_theme_constant_override("separation",10)
    col.add_child(body)
    var navigation := HBoxContainer.new()
    back_button=viewer._button("上一步",func():_show_step(step-1))
    next_button=viewer._button("下一步",func():
        if step<2: _show_step(step+1)
        else: _save())
    next_button.size_flags_horizontal=Control.SIZE_EXPAND_FILL
    navigation.add_child(back_button)
    navigation.add_child(next_button)
    col.add_child(navigation)
    status=viewer._label("",13)
    status.autowrap_mode=TextServer.AUTOWRAP_WORD_SMART
    status.custom_minimum_size.x=280
    col.add_child(status)
    look_button=viewer._button("旋转查看",func():
        look_mode=not look_mode
        looking=false
        look_button.text="返回调整" if look_mode else "旋转查看"
        status.text="在人物区域单指按住拖动旋转。" if look_mode else "直接拖动当前圆点调整。")
    col.add_child(look_button)
    var views := HBoxContainer.new()
    for item in [["正面",0.0],["侧面",PI/2],["背面",PI]]:
        var angle: float=item[1]
        views.add_child(viewer._button(item[0],func():viewer.yaw=angle;viewer.pitch=0;viewer._orbit()))
    col.add_child(views)
    var zoom := HBoxContainer.new()
    zoom.add_child(viewer._button("放大",func():viewer.distance=maxf(0.25,viewer.distance/1.25);viewer._orbit()))
    zoom.add_child(viewer._button("缩小",func():viewer.distance=minf(7,viewer.distance*1.25);viewer._orbit()))
    col.add_child(zoom)
    col.add_child(viewer._label("单指按住圆点拖动即可\n查看角度时，先点“旋转查看”",12))

func _default_hand() -> void:
    if bone<0: return
    var units: float=config.source_units_per_meter
    var center := Vector3.ZERO
    var finger: int=viewer.skeleton.find_bone("mixamorig_RightHandMiddle1" if "Right" in config.bone else "mixamorig_LeftHandMiddle1")
    if finger>=0:
        center=(viewer.skeleton.get_bone_global_pose(bone).affine_inverse()*viewer.skeleton.get_bone_global_pose(finger).origin)*0.65
    var axis := Vector3(0,0,-1)*0.10*units
    var side := Vector3(1,0,0)*0.07*units
    config.hand_points=[_array(center),_array(center+axis),_array(center+side)]

func _array(point: Vector3) -> Array:
    return [point.x,point.y,point.z]

func _point(index: int) -> Vector3:
    var p: Array=config.hand_points[index]
    return Vector3(p[0],p[1],p[2])

func _checkpoint() -> void:
    undo_stack.append(config.duplicate(true))
    if undo_stack.size()>30: undo_stack.pop_front()
    previewed=false

func _undo() -> void:
    if undo_stack.is_empty(): return
    config=undo_stack.pop_back()
    previewed=false
    _refresh()
    _show_step(step)

func _show_step(value: int) -> void:
    if value<0 or value>2: return
    step=value
    look_mode=false
    looking=false
    look_button.text="旋转查看"
    selected_point=0 if step==0 else 1
    point_choices.clear()
    pending=-1
    dragging_point=-1
    if viewer.timeline.get_parent()==body:
        viewer.timeline.reparent(viewer)
        viewer.timeline.hide()
        viewer.time_label.reparent(viewer)
        viewer.time_label.hide()
    for child in body.get_children():
        body.remove_child(child)
        child.queue_free()
    for i in range(step_buttons.size()): step_buttons[i].modulate=Color.WHITE if i==step else Color("889b9d")
    back_button.visible=step>0
    next_button.text="下一步：调整朝向" if step==0 else ("下一步：检查动作" if step==1 else "确认保存，返回工作台")
    heading.text=["先把握柄放进手掌","让剑指向正确方向","看看动作中的握持"][step]
    subtitle.text=["拖动红点，把剑柄放在手掌上。握点会贴着模型表面移动。","拖动绿点改变剑尖朝向。握点和武器大小保持不变；刀刃用下面的滑条转正。","切换动作并慢放检查。发现位置不对可返回调整，确认后保存这个人物的装备配置。"][step]
    if step<2:
        _pause()
        if neutral==false:
            viewer.animation_player.stop()
            viewer.skeleton.reset_bone_poses()
            neutral=true
        surface_dirty=true
        _focus_hand()
    if step==0: _grip_controls()
    elif step==1: _direction_controls()
    else: _preview_controls()
    status.text="拖动红点放好剑柄。" if step==0 else ("拖动绿点指向剑尖，滑条转正刀刃。" if step==1 else "请查看各动作中的握持，特别注意武器穿身。")

func _grip_controls() -> void:
    hand_choice=OptionButton.new()
    hand_choice.add_item("右手")
    hand_choice.add_item("左手")
    hand_choice.select(0 if "Right" in config.bone else 1)
    hand_choice.item_selected.connect(func(i):
        _checkpoint()
        config.bone="mixamorig_RightHand" if i==0 else "mixamorig_LeftHand"
        bone=viewer.skeleton.find_bone(config.bone)
        surface_dirty=true
        _default_hand()
        _focus_hand()
        _refresh())
    body.add_child(viewer._label("握持手",13))
    body.add_child(hand_choice)
    body.add_child(viewer._button("恢复建议位置",func():_checkpoint();_default_hand();_refresh()))
    body.add_child(viewer._button("撤销上次调整",_undo))

func _nudge_controls() -> void:
    body.add_child(viewer._label("选中点微调（每次 2 毫米）",13))
    var row := HBoxContainer.new()
    for item in [["←",Vector3.LEFT],["→",Vector3.RIGHT],["↑",Vector3.UP],["↓",Vector3.DOWN]]:
        var direction: Vector3=item[1]
        row.add_child(viewer._button(item[0],func():
            _checkpoint()
            var world: Vector3=viewer.camera.global_basis*direction*0.002
            _move_point(selected_point,_point(selected_point)+_hand_transform().basis.inverse()*world)))
    body.add_child(row)

func _depth_control() -> void:
    body.add_child(viewer._label("沿视线前后微调",13))
    var row := HBoxContainer.new()
    for value in [-0.005,0.005]:
        var amount: float=value
        row.add_child(viewer._button("向前" if value<0 else "向后",func():
            _checkpoint()
            var delta: Vector3=_hand_transform().basis.inverse()*viewer.camera.global_basis.z*amount
            for i in range(3): config.hand_points[i]=_array(_point(i)+delta)
            _refresh()))
    body.add_child(row)

func _direction_controls() -> void:
    body.add_child(viewer._label("拖动绿点，剑绕握点转动",13))
    var row := HBoxContainer.new()
    row.add_child(viewer._button("剑尖反向",func():
        _checkpoint()
        config.hand_points[1]=_array(_point(0)*2-_point(1))
        _refresh()))
    row.add_child(viewer._button("旋转刃面 90°",func():_rotate_blade(PI/2)))
    body.add_child(row)
    body.add_child(viewer._label("刃面旋转",13))
    turn_slider=HSlider.new()
    turn_slider.min_value=-180
    turn_slider.max_value=180
    turn_slider.step=1
    turn_value=0
    turn_slider.drag_started.connect(_checkpoint)
    turn_slider.value_changed.connect(func(v):
        _rotate_blade(deg_to_rad(v-turn_value),false)
        turn_value=v)
    body.add_child(turn_slider)
    body.add_child(viewer._label("武器大小（倍率）",13))
    var size_slider := HSlider.new()
    size_slider.min_value=0.2
    size_slider.max_value=2
    size_slider.step=0.05
    size_slider.value=config.weapon_scale
    size_slider.drag_started.connect(_checkpoint)
    size_slider.value_changed.connect(func(v):config.weapon_scale=v;previewed=false;_refresh())
    body.add_child(size_slider)
    body.add_child(viewer._button("撤销上次调整",_undo))

func _rotate_blade(angle: float, record := true) -> void:
    if record: _checkpoint()
    var axis: Vector3=(_point(1)-_point(0)).normalized()
    config.hand_points[2]=_array(_point(0)+(_point(2)-_point(0)).rotated(axis,angle))
    _refresh()

func _preview_controls() -> void:
    var actions := OptionButton.new()
    for action in viewer.report.actions: actions.add_item(action)
    actions.select(viewer.choice.selected)
    actions.item_selected.connect(func(i):viewer._play_action(actions.get_item_text(i));previewed=true)
    body.add_child(viewer._label("检查动作",13))
    body.add_child(actions)
    play_toggle=viewer._button("暂停",func():
        viewer.playing=not viewer.playing
        viewer.animation_player.speed_scale=viewer.speed if viewer.playing else 0
        play_toggle.text="暂停" if viewer.playing else "播放")
    body.add_child(play_toggle)
    var speeds := OptionButton.new()
    for s in [0.25,0.5,1.0]: speeds.add_item("%.2f ×" % s)
    speeds.select(1)
    viewer.speed=0.5
    speeds.item_selected.connect(func(i):viewer.speed=[0.25,0.5,1.0][i];viewer.animation_player.speed_scale=viewer.speed if viewer.playing else 0)
    body.add_child(speeds)
    # The inspection viewer still owns and updates its timeline and time label.
    viewer.timeline.reparent(body)
    viewer.time_label.reparent(body)
    viewer.timeline.show()
    viewer.time_label.show()
    body.add_child(viewer._button("回到手部继续调整",func():_show_step(0)))
    _preview()
    previewed=true

func _pause() -> void:
    viewer.playing=false
    viewer.animation_player.speed_scale=0
    viewer.play_button.text="播放"

func _hand_transform() -> Transform3D:
    return viewer.skeleton.global_transform * viewer.skeleton.get_bone_global_pose(bone)

func _focus_hand() -> void:
    mode="hand"
    viewer.model.visible=true
    if weapon: weapon.visible=false
    if attached: attached.visible=true
    if bone<0:
        status.text="模型缺少所选手骨"
        return
    viewer.orbit.position=_hand_transform().origin+Vector3(-0.04,0.01,0)
    viewer.distance=0.7
    viewer._orbit()
    _markers()

func _focus_weapon() -> void:
    mode="weapon"
    _pause()
    viewer.model.visible=false
    if attached: attached.visible=false
    if not weapon:
        weapon=Runtime.sword()
        add_child(weapon)
    weapon.visible=true
    viewer.orbit.position=Vector3(-0.12,0.25,0)
    viewer.distance=1.65
    viewer.yaw=0.35
    viewer._orbit()
    _markers()

func _arm(index: int, target: String) -> void:
    if target=="hand":
        viewer.model.visible=true
        _focus_hand()
    else:
        _focus_weapon()
    _pause()
    pending=index
    status.text="在中间视窗左键点选。中心点贴合表面；方向点落在中心深度的平面。旋转检查深度后再确认。"

func _valid(points: Array) -> bool:
    if points.size()!=3: return false
    var a := Vector3(points[1][0]-points[0][0],points[1][1]-points[0][1],points[1][2]-points[0][2])
    var b := Vector3(points[2][0]-points[0][0],points[2][1]-points[0][1],points[2][2]-points[0][2])
    return a.length()>0.00001 and b.length()>0.00001 and a.cross(b).length()>a.length()*b.length()*0.1

func _refresh() -> void:
    if attached:
        attached.free()
        attached=null
    if bone>=0 and _valid(config.hand_points) and _valid(config.weapon_points):
        attached=Runtime.attach(viewer.skeleton,config)
    status.text="剑柄贴着手掌表面移动。" if step==0 else "朝向即时更新；握点和剑的大小保持不变。"
    _markers()

func _markers() -> void:
    for marker in markers: marker.queue_free()
    markers.clear()
    if axis_lines:
        axis_lines.queue_free()
        axis_lines=null
    if mode=="preview": return
    var points: Array=config.hand_points if mode=="hand" else config.weapon_points
    for i in range(points.size()):
        var point: Array=points[i]
        var marker := MeshInstance3D.new()
        var sphere := SphereMesh.new()
        sphere.radius=0.006 if mode=="hand" else 0.012
        sphere.height=sphere.radius*2
        var mat := StandardMaterial3D.new()
        mat.shading_mode=BaseMaterial3D.SHADING_MODE_UNSHADED
        mat.no_depth_test=true
        mat.albedo_color=[Color("fa775d"),Color("74dc91"),Color("70b9ff")][i]
        sphere.material=mat
        marker.mesh=sphere
        marker.visible=(step==0 and i==0) or (step==1 and i==1)
        add_child(marker)
        marker.global_position=(_hand_transform()*Vector3(point[0],point[1],point[2])) if mode=="hand" else Vector3(point[0],point[1],point[2])
        markers.append(marker)
    if points.size()==3:
        var lines := ImmediateMesh.new()
        var material := StandardMaterial3D.new()
        material.shading_mode=BaseMaterial3D.SHADING_MODE_UNSHADED
        material.no_depth_test=true
        material.vertex_color_use_as_albedo=true
        lines.surface_begin(Mesh.PRIMITIVE_LINES,material)
        for i in [1]:
            lines.surface_set_color(Color("74dc91") if i==1 else Color("70b9ff"))
            lines.surface_add_vertex(markers[0].global_position)
            lines.surface_add_vertex(markers[i].global_position)
        lines.surface_end()
        axis_lines=MeshInstance3D.new()
        axis_lines.mesh=lines
        add_child(axis_lines)

func _unhandled_input(event: InputEvent) -> void:
    if look_mode: return
    if event is InputEventKey and event.pressed and event.keycode==KEY_Z and event.ctrl_pressed:
        _undo()
        get_viewport().set_input_as_handled()
        return
    if step<2 and pending<0 and event is InputEventMouseButton and event.button_index==MOUSE_BUTTON_LEFT and event.pressed:
        var best := 32.0
        var selected := -1
        for i in range(markers.size()):
            if (step==0 and i!=0) or (step==1 and i!=1): continue
            var screen: Vector2=viewer.camera.unproject_position(markers[i].global_position)
            var gap: float=screen.distance_to(event.position)
            # Prefer explicitly selected point when direction handles overlap.
            if i==selected_point and gap<32:
                selected=i
                break
            if gap<best:
                best=gap
                selected=i
        if selected>=0:
            _pause()
            _checkpoint()
            dragging_point=selected
            selected_point=selected
            drag_start_mouse=event.position
            drag_start_world=markers[selected].global_position
            drag_plane=Plane(viewer.camera.global_basis.z,markers[selected].global_position)
            get_viewport().set_input_as_handled()
            return
    _place(event)

func _input(event: InputEvent) -> void:
    if event is InputEventMouseButton and event.button_index==MOUSE_BUTTON_LEFT:
        if look_mode and event.pressed and event.position.x>370:
            looking=true
            get_viewport().set_input_as_handled()
            return
        if not event.pressed: looking=false
        # Capture handles before GUI/unhandled propagation can discard a press.
        if not look_mode and step<2 and pending<0 and event.pressed and event.position.x>370:
            _unhandled_input(event)
            if dragging_point>=0: return
    if look_mode:
        if looking and event is InputEventMouseMotion:
            viewer.yaw-=event.relative.x*0.006
            viewer.pitch=clampf(viewer.pitch-event.relative.y*0.004,-1.1,1.1)
            viewer._orbit()
            get_viewport().set_input_as_handled()
        return
    # Handle adjustment keys before the viewer uses arrows for animation stepping.
    if step<2 and pending<0 and event is InputEventKey and event.pressed:
        var direction := Vector3.ZERO
        if event.keycode==KEY_LEFT: direction=-viewer.camera.global_basis.x
        elif event.keycode==KEY_RIGHT: direction=viewer.camera.global_basis.x
        elif event.keycode==KEY_UP: direction=viewer.camera.global_basis.y
        elif event.keycode==KEY_DOWN: direction=-viewer.camera.global_basis.y
        elif event.keycode==KEY_PAGEUP: direction=-viewer.camera.global_basis.z
        elif event.keycode==KEY_PAGEDOWN: direction=viewer.camera.global_basis.z
        if direction!=Vector3.ZERO:
            var focus=get_viewport().gui_get_focus_owner()
            if focus is LineEdit or focus is Range: return
            _checkpoint()
            var amount := 0.0005 if event.shift_pressed else 0.002
            _move_point(selected_point,_hand_transform().affine_inverse()*(_hand_transform()*_point(selected_point)+direction*amount))
            get_viewport().set_input_as_handled()
            return
    if dragging_point<0: return
    if event is InputEventMouseButton and event.button_index==MOUSE_BUTTON_LEFT and not event.pressed:
        dragging_point=-1
        get_viewport().set_input_as_handled()
    elif event is InputEventMouseMotion:
        if dragging_point==0:
            var surface=_surface_at(event.position)
            if surface!=null:
                _move_point(0,_hand_transform().affine_inverse()*surface)
            else:
                status.text="请把红点拖在手掌表面；拖出模型时位置保持不变。"
            get_viewport().set_input_as_handled()
            return
        var pointer: Vector2=event.position
        var start_hit=drag_plane.intersects_ray(viewer.camera.project_ray_origin(drag_start_mouse),viewer.camera.project_ray_normal(drag_start_mouse))
        var hit=drag_plane.intersects_ray(viewer.camera.project_ray_origin(pointer),viewer.camera.project_ray_normal(pointer))
        if hit==null: return
        if start_hit!=null: hit=drag_start_world+hit-start_hit
        if dragging_point==0 and hit.distance_to(_hand_transform().origin)>0.22: return
        var local: Vector3=_hand_transform().affine_inverse()*hit
        _move_point(dragging_point,local)
        get_viewport().set_input_as_handled()

func _move_point(index: int, local: Vector3) -> void:
    if index==0 and (_hand_transform()*local).distance_to(_hand_transform().origin)>0.22: return
    var previous: Array=config.hand_points.duplicate(true)
    if index==0:
        var delta := local-_point(0)
        for i in range(3): config.hand_points[i]=_array(_point(i)+delta)
    elif index==1:
        var old_axis := _point(1)-_point(0)
        var new_axis := local-_point(0)
        if new_axis.length()<0.00001: return
        var rotation := Quaternion(old_axis.normalized(),new_axis.normalized())
        config.hand_points[2]=_array(_point(0)+rotation*(_point(2)-_point(0)))
        config.hand_points[1]=_array(_point(0)+new_axis.normalized()*old_axis.length())
    else: config.hand_points[index]=_array(local)
    if _valid(config.hand_points):
        previewed=false
        _refresh()
    else: config.hand_points=previous

func _surface_at(screen: Vector2):
    if not get_viewport().get_visible_rect().has_point(screen) or screen.x<370: return null
    var origin: Vector3=viewer.camera.project_ray_origin(screen)
    var direction: Vector3=viewer.camera.project_ray_normal(screen)
    if surface_dirty:
        _cache_hand_surface()
    if hand_faces.is_empty():
        status.text="手部表面还未就绪，请稍后重试或切换一次视角。"
        return null
    var closest := INF
    var result=null
    for i in range(0,hand_faces.size(),3):
        var hit=Geometry3D.ray_intersects_triangle(origin,direction,hand_faces[i],hand_faces[i+1],hand_faces[i+2])
        if hit==null:
            hit=Geometry3D.ray_intersects_triangle(origin,direction,hand_faces[i+2],hand_faces[i+1],hand_faces[i])
        if hit==null: continue
        var world: Vector3=hit
        var depth := origin.distance_to(world)
        if depth<closest:
            closest=depth
            result=world
    if result==null:
        # Keep dragging forgiving near the hand silhouette, without free-space motion.
        var nearest := 24.0
        for i in range(0,hand_faces.size(),3):
            for edge in range(3):
                var a: Vector3=hand_faces[i+edge]
                var b: Vector3=hand_faces[i+(edge+1)%3]
                var sa: Vector2=viewer.camera.unproject_position(a)
                var sb: Vector2=viewer.camera.unproject_position(b)
                var projected: Vector2=Geometry2D.get_closest_point_to_segment(screen,sa,sb)
                var gap := screen.distance_to(projected)
                if gap<nearest:
                    nearest=gap
                    var span := sb-sa
                    var t := clampf((projected-sa).dot(span)/maxf(span.length_squared(),0.0001),0,1)
                    # Perspective-correct interpolation along the projected edge.
                    var da: float=-viewer.camera.to_local(a).z
                    var db: float=-viewer.camera.to_local(b).z
                    var weight := (t/maxf(db,0.0001))/maxf((1-t)/maxf(da,0.0001)+t/maxf(db,0.0001),0.0001)
                    result=a.lerp(b,weight)
    return result

func _cache_hand_surface() -> void:
    hand_faces.clear()
    var instance: MeshInstance3D=viewer.model_mesh
    var mesh: Mesh=instance.bake_mesh_from_current_skeleton_pose() if instance.skin else instance.mesh
    if mesh==null: return
    var faces := mesh.get_faces()
    var center := _hand_transform().origin
    # Convert once per editing pose, not once per pointer event. Ignore torso occlusion.
    for i in range(0,faces.size(),3):
        var a: Vector3=instance.global_transform*faces[i]
        var b: Vector3=instance.global_transform*faces[i+1]
        var c: Vector3=instance.global_transform*faces[i+2]
        if maxf(a.distance_to(center),maxf(b.distance_to(center),c.distance_to(center)))<0.22:
            hand_faces.append_array(PackedVector3Array([a,b,c]))
    surface_dirty=false

func _place(event: InputEvent) -> void:
    if pending<0 or not event is InputEventMouseButton or event.button_index!=MOUSE_BUTTON_LEFT or not event.pressed: return
    if event.position.x<370: return
    var origin: Vector3=viewer.camera.project_ray_origin(event.position)
    var direction: Vector3=viewer.camera.project_ray_normal(event.position)
    var transform := _hand_transform() if mode=="hand" else Transform3D.IDENTITY
    var points: Array=config.hand_points if mode=="hand" else config.weapon_points
    var center := transform.origin
    if not points.is_empty(): center=transform*Vector3(points[0][0],points[0][1],points[0][2])
    var hit = Plane(viewer.camera.global_basis.z,center).intersects_ray(origin,direction)
    if pending==0:
        # Ray/triangle intersection on the current deformed hand mesh or weapon.
        var meshes: Array=[]
        if mode=="hand": meshes=[viewer.model_mesh]
        else: meshes=weapon.get_children()
        var closest := INF
        for instance in meshes:
            if not instance is MeshInstance3D: continue
            var mesh: Mesh=instance.bake_mesh_from_current_skeleton_pose() if instance.skin else instance.mesh
            var faces: PackedVector3Array=mesh.get_faces()
            var local_origin: Vector3=instance.global_transform.affine_inverse()*origin
            var local_dir: Vector3=(instance.global_basis.inverse()*direction).normalized()
            for i in range(0,faces.size(),3):
                var intersection = Geometry3D.ray_intersects_triangle(local_origin,local_dir,faces[i],faces[i+1],faces[i+2])
                if intersection!=null:
                    var world_point: Vector3=instance.global_transform*intersection
                    var depth := origin.distance_to(world_point)
                    if depth<closest:
                        closest=depth
                        hit=world_point
        if closest==INF:
            status.text="没有点中模型表面，请旋转或放大后再点。"
            return
        if mode=="hand" and hit.distance_to(transform.origin)>0.22:
            status.text="点离所选手骨太远，请在手掌附近标注。"
            return
    if hit==null: return
    if pending>points.size():
        status.text="请按①②③顺序标注。"
        return
    var local: Vector3=transform.affine_inverse()*hit
    var value := [local.x,local.y,local.z]
    _checkpoint()
    if pending==0 and points.size()==3 and mode=="hand":
        var delta: Vector3=local-_point(0)
        for i in range(3): points[i]=_array(_point(i)+delta)
    if pending==points.size(): points.append(value)
    else: points[pending]=value
    pending=-1
    _refresh()
    get_viewport().set_input_as_handled()

func _preview() -> void:
    pending=-1
    mode="preview"
    if weapon: weapon.visible=false
    viewer.model.visible=true
    if attached: attached.visible=true
    for marker in markers: marker.visible=false
    if axis_lines: axis_lines.visible=false
    viewer.orbit.position=Vector3(-0.30,1.10,0)
    viewer.distance=4.0
    viewer._orbit()
    if neutral:
        neutral=false
        viewer._play_action(viewer.choice.get_item_text(viewer.choice.selected))
    viewer.playing=true
    viewer.animation_player.speed_scale=viewer.speed
    viewer.play_button.text="暂停"
    status.text="在左侧切换动作、慢放和逐帧检查。普通动作不会自动变成挥剑动作。"

func _save() -> void:
    if not _valid(config.hand_points) or not _valid(config.weapon_points):
        status.text="三点未完成或方向近乎共线，请重新标注。"
        return
    if mode!="preview" or not previewed:
        status.text="请先点击全身动作预览，检查握持和穿插。"
        return
    _pause()
    config.confirmed=true
    var output: String=viewer.spec.equipment_output
    var file := FileAccess.open(output+".tmp",FileAccess.WRITE)
    if file==null:
        config.confirmed=false
        status.text="保存失败，请检查输出目录是否可写。窗口保持打开，可继续调整。"
        return
    file.store_string(JSON.stringify(config,"  "))
    file.close()
    if DirAccess.rename_absolute(output+".tmp",output)!=OK:
        config.confirmed=false
        status.text="保存失败，未覆盖旧配置。请检查文件权限后重试。"
        return
    await RenderingServer.frame_post_draw
    get_viewport().get_texture().get_image().save_png(viewer.spec.equipment_screenshot)
    saved=true
    viewer.get_tree().quit()
