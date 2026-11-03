extends SceneTree
func _initialize():
	call_deferred("verify")
func check(ok: bool, message: String):
	if not ok:
		push_error(message)
		quit(1)
		assert(ok, message)
func verify():
	var scene = load("res://main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	scene.player.set_physics_process(false)
	scene.set_physics_process(false)
	var actor: CharacterBody2D = scene.player
	var world: Node2D = scene.get_child(0)
	var art: Sprite2D = world.get_child(4).get_child(0)
	check(art.scale.is_equal_approx(Vector2(.5,.5)),"half image scale")
	check(art.position.is_equal_approx(Vector2(-32,-40)),"scaled anchor offset")
	check(art.global_position.is_equal_approx(Vector2(688,-40)),"instance position remains world units")
	check(scene.blockers[4].polygon[0].is_equal_approx(Vector2(-32,-3)),"collision scales once")
	# Layout and polygons come from the actual Studio export.
	for probe in [
		{"start":Vector2(0,-40),"motion":Vector2(0,80),"blocked":true,"label":"wall"},
		{"start":Vector2(128,-40),"motion":Vector2(0,80),"blocked":true,"label":"repeated wall"},
		{"start":Vector2(320,-40),"motion":Vector2(0,80),"blocked":false,"label":"opening"},
		{"start":Vector2(275,-40),"motion":Vector2(0,80),"blocked":true,"label":"opening side"},
		{"start":Vector2(720,-40),"motion":Vector2(0,80),"blocked":true,"label":"half wall center"},
		{"start":Vector2(765,-40),"motion":Vector2(0,80),"blocked":false,"label":"outside half wall"},
		{"start":Vector2(920,-40),"motion":Vector2(0,80),"blocked":true,"label":"scaled opening narrower than actor diameter"},
		{"start":Vector2(520,-40),"motion":Vector2(0,80),"blocked":false,"label":"decoration"}
	]:
		actor.position = probe.start
		await physics_frame
		var collision := actor.move_and_collide(probe.motion)
		check((collision != null) == probe.blocked,probe.label)
		if not probe.blocked:
			check(actor.position.is_equal_approx(probe.start+probe.motion),"full passage "+probe.label)
	# Input invokes the exported controller and must change position.
	actor.position = Vector2(520,100)
	scene.set_physics_process(true)
	var event := InputEventKey.new()
	event.physical_keycode = KEY_D
	event.pressed = true
	Input.parse_input_event(event)
	await create_timer(.2).timeout
	event = InputEventKey.new()
	event.physical_keycode = KEY_D
	event.pressed = false
	Input.parse_input_event(event)
	check(actor.position.x>540,"exported physical key movement")
	print("MODULE_SCENE_PASS wall/repeated-instance/opening/opening-side/passable/input/scaled-image-anchor-collision")
	quit()
