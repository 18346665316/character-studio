extends SceneTree
func _initialize():
	call_deferred("verify")
func verify():
	var args := OS.get_cmdline_user_args()
	var receipt: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	var scene = load("res://main.tscn").instantiate()
	root.add_child(scene)
	await physics_frame
	await physics_frame
	scene.set_physics_process(false)
	var actor: CharacterBody2D = scene.player
	var passed := true
	var results: Array = []
	for probe in receipt.probes:
		actor.position = Vector2(probe.start[0],probe.start[1])
		await physics_frame
		var motion := Vector2(probe.motion[0],probe.motion[1])
		var blocked := false
		var blocker := ""
		for i in range(50):
			var collision := actor.move_and_collide(motion/50.0)
			if collision:
				blocker = str(collision.get_collider().get_meta("module_title","unknown"))
				blocked = true
				break
			await physics_frame
		var ok: bool = blocked == probe.blocked
		passed = passed and ok
		results.append({"label":probe.label,"passed":ok,"blocked":blocked,"blocker":blocker,"position":[actor.position.x,actor.position.y]})
	var output := FileAccess.open(args[1],FileAccess.WRITE)
	output.store_string(JSON.stringify({"passed":passed,"probes":results},"  "))
	print("COURTYARD_ACCESS_", "PASS" if passed else "FAIL")
	if DisplayServer.get_name() != "headless":
		var occlusion_results: Array = []
		var center := Vector2(receipt.center[0],receipt.center[1])
		scene.camera.position = center
		var wall := Vector2(receipt.probes[2].start[0]+25,receipt.probes[2].start[1]-50)
		for sample in [{"label":"behind wall","foot":wall+Vector2(0,-12),"visible":false},
			{"label":"in front of wall","foot":wall+Vector2(0,16),"visible":true},
			{"label":"inside doorway","foot":center+Vector2(0,-12),"visible":true}]:
			actor.position = sample.foot
			await process_frame
			await RenderingServer.frame_post_draw
			await process_frame
			await RenderingServer.frame_post_draw
			var image := root.get_texture().get_image()
			var point: Vector2 = (actor.get_global_transform_with_canvas()*Vector2(0,-20))
			var color := image.get_pixel(int(point.x),int(point.y))
			var gold := Color("f5ce72")
			var shown: bool = abs(color.r-gold.r)+abs(color.g-gold.g)+abs(color.b-gold.b)<.08
			var ok: bool = shown==sample.visible
			passed = passed and ok
			occlusion_results.append({"label":sample.label,"passed":ok,"actor_visible":shown})
		output = FileAccess.open(args[1],FileAccess.WRITE)
		output.store_string(JSON.stringify({"passed":passed,"probes":results,"occlusion":occlusion_results},"  "))
		actor.position = Vector2(receipt.center[0]-10,receipt.center[1]+20)
		scene.camera.position = Vector2(receipt.center[0],receipt.center[1]-40)
		await process_frame
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png(args[1].get_base_dir()+"/gate-godot.png")
	quit(0 if passed else 1)
