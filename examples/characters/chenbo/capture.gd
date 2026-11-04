extends SceneTree
## Capture the actual renderer at a fixed rate; pass an absolute output directory.
func _initialize(): call_deferred("capture")

func capture():
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		push_error("Pass an output directory after --")
		quit(1)
		return
	DirAccess.make_dir_recursive_absolute(args[0])
	var scene = load("res://showcase.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	for actor in scene.actors:
		if actor.get_node("Sprite").sprite_frames == null:
			push_error("Import the project with --headless --editor --import before capture")
			quit(1)
			return
	scene.restart()
	for index in 120:
		await process_frame
		await RenderingServer.frame_post_draw
		var result := root.get_texture().get_image().save_png(args[0].path_join("frame-%03d.png" % index))
		if result != OK:
			quit(1)
			return
	print("SHOWCASE_CAPTURE_PASS 120 frames at --fixed-fps 12")
	quit()
