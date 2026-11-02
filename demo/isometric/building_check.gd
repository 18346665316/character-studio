extends SceneTree
var scene: Node2D
var failures: Array[String] = []
var checks := 0
var observations: Dictionary = {}

func _initialize() -> void:
	call_deferred("run")

func frames(count: int) -> void:
	for i in count:
		await physics_frame

func check(ok: bool, label: String) -> void:
	checks += 1
	if not ok: failures.append(label)

func key(code: Key) -> void:
	var event := InputEventKey.new()
	event.keycode = code
	event.pressed = true
	Input.parse_input_event(event)
	await process_frame
	event = InputEventKey.new()
	event.keycode = code
	event.pressed = false
	Input.parse_input_event(event)
	await process_frame

func capture(path: String) -> Image:
	await process_frame
	await RenderingServer.frame_post_draw
	var image := root.get_texture().get_image()
	image.save_png(path)
	return image

func run() -> void:
	scene = load("res://building.tscn").instantiate()
	root.add_child(scene)
	await create_timer(.6).timeout
	await frames(5)
	Input.action_press("ui_right")
	await frames(20)
	Input.action_release("ui_right")
	observations["moved_x"] = scene.player.position.x
	check(scene.player.position.x > 625, "real input moves character")
	# Walk toward the marked front wall. The game-owned footprint blocks feet.
	scene.player.position = Vector2(530, 610)
	Input.action_press("ui_up")
	await frames(35)
	Input.action_release("ui_up")
	await frames(2)
	observations["wall_stop"] = [scene.player.position.x,scene.player.position.y]
	check(scene.player.position.y > 535, "front wall blocks movement")
	check(scene.player.position.y < 590, "character reaches wall before stopping")
	# Entrance is outside the collision polygon; a marker does not cut a doorway.
	scene.player.position = scene.entrance + Vector2(0, 22)
	await frames(3)
	await key(KEY_E)
	check(scene.interactions == 1, "entrance input triggers interaction")
	scene.player.position = Vector2(850,650)
	await frames(3)
	await key(KEY_E)
	check(scene.interactions == 1, "entrance input outside range is ignored")
	await key(KEY_F)
	check(scene.footprint.visible, "footprint overlay toggles")
	await key(KEY_G)
	check(not scene.grid_visible, "grid toggles")
	await key(KEY_G)
	await key(KEY_F)
	await key(KEY_R)
	check(scene.player.position.is_equal_approx(Vector2(610,620)), "reset restores spawn")
	var args := OS.get_cmdline_user_args()
	if not args.is_empty() and not DisplayServer.get_name() == "headless":
		var directory := args[0]
		scene.player.enabled = false
		await capture(directory + "/building-front.png")
		# Compare rendered pixels with and without the character. Positions are
		# deliberate sorting probes, not claims that the character walked there.
		for probe in [[Vector2(550,430),"behind"],[Vector2(610,540),"front-wall"]]:
			scene.player.position = probe[0]
			scene.player.visible = false
			var baseline := await capture(directory + "/building-baseline.png")
			scene.player.visible = true
			var actual := await capture(directory + "/building-" + probe[1] + ".png")
			var changed := 0
			for y in range(int(probe[0].y)-85,int(probe[0].y)-15):
				for x in range(int(probe[0].x)-12,int(probe[0].x)+12):
					if baseline.get_pixel(x,y) != actual.get_pixel(x,y): changed += 1
			check(changed == 0 if probe[1] == "behind" else changed > 100, "rendered character ordering " + probe[1])
		scene.player.position = Vector2(380,500)
		scene.footprint.visible = true
		await capture(directory + "/building-footprint.png")
	var report := {"checks":checks,"failed":failures,"observations":observations,"rendered":not args.is_empty(),"production_ready":false}
	if not args.is_empty():
		var file := FileAccess.open(args[0]+"/building-check.json",FileAccess.WRITE)
		file.store_string(JSON.stringify(report,"\t"))
	print(JSON.stringify(report))
	quit(0 if failures.is_empty() else 1)
