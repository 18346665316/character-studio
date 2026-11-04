extends SceneTree

func _initialize() -> void:
	call_deferred("verify")

func verify() -> void:
	var scene = load("res://main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	scene.set_physics_process(false)
	var checks: Array = []
	var modules: Dictionary = {}
	for module in scene.data.modules:
		modules[module.id] = module
	var blocked_count := 0
	for item in scene.data.instances:
		var module: Dictionary = modules[item.module]
		if module.get("layer", "objects") == "ground" or module.polygons.is_empty():
			continue
		var shape: Array = module.polygons[0]
		var scale: float = module.world_scale
		var left: float = shape[0][0] * scale
		var right: float = shape[1][0] * scale
		var middle_y: float = (shape[0][1] + shape[2][1]) * scale / 2.0
		var at := Vector2(item.position[0], item.position[1])
		scene.player.position = at + Vector2(left - 20.0, middle_y)
		await physics_frame
		var hit = scene.player.move_and_collide(Vector2(right - left + 40.0, 0))
		var ok: bool = hit != null and hit.get_collider().get_meta("module_title", "") == module.title
		checks.append({"title": module.title, "blocked_by_expected_asset": ok})
		if ok:
			blocked_count += 1
	scene.player.position = Vector2(scene.data.spawn[0], scene.data.spawn[1])
	if DisplayServer.get_name() != "headless":
		root.grab_focus()
		await create_timer(0.5).timeout
	scene.set_physics_process(true)
	var start: Vector2 = scene.player.position
	var event := InputEventKey.new()
	event.physical_keycode = KEY_D
	event.pressed = true
	Input.parse_input_event(event)
	await create_timer(0.25).timeout
	event = InputEventKey.new()
	event.physical_keycode = KEY_D
	event.pressed = false
	Input.parse_input_event(event)
	var moved: bool = scene.player.position.x > start.x + 10.0
	var reference = scene.player.get_child(1)
	var one_human: bool = is_equal_approx(reference.polygon[2].y, -34.0)
	var passed: bool = moved and one_human and blocked_count == 5 and scene.data.instances.size() == 88
	var report := {"passed":passed,"movement":moved,"one_human_reference":one_human,"blocking_checks":checks}
	var args := OS.get_cmdline_user_args()
	if args.size() > 0:
		var file := FileAccess.open(args[0], FileAccess.WRITE)
		file.store_string(JSON.stringify(report, "  "))
		if DisplayServer.get_name() != "headless":
			scene.camera.position = Vector2(0, 0)
			await RenderingServer.frame_post_draw
			await RenderingServer.frame_post_draw
			root.get_texture().get_image().save_png(args[0].get_base_dir()+"/farm-godot.png")
	print("FARM_WORKFLOW ", JSON.stringify(report))
	quit(0 if passed else 1)
