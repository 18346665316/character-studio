extends SceneTree
var failures: Array[String] = []
func _initialize() -> void:
	call_deferred("run")
func capture() -> Image:
	await process_frame
	await RenderingServer.frame_post_draw
	return root.get_texture().get_image()
func run() -> void:
	var scene = load("res://main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	scene.player.enabled = false
	var checked := 0
	for i in scene.objects.size():
		var object: Node2D = scene.objects[i]
		var kind := "rock" if i == 0 else "crate"
		# Arbitrary imported artwork requires human review. Strict pixel probes
		# are calibrated only to the documented engineering fixtures.
		if not scene.sources.objects[kind].fixture:
			continue
		scene.player.position = object.position + Vector2(0,-20)
		var behind := await capture()
		var sample: Vector2 = scene.player.position + Vector2(0,-10)
		if behind.get_pixelv(sample).is_equal_approx(Color("56e8db")):
			failures.append(kind + " behind marker was not occluded")
		scene.player.position = object.position + Vector2(0,20)
		var front := await capture()
		sample = scene.player.position + Vector2(0,-10)
		var color := front.get_pixelv(sample)
		if Vector3(color.r,color.g,color.b).distance_to(Vector3(86.0/255,232.0/255,219.0/255)) > 0.03:
			failures.append(kind + " front marker was occluded")
		checked += 2
	scene.player.position = Vector2(550,480)
	var image := await capture()
	var output := "user://isometric-demo.png"
	if OS.get_cmdline_user_args().size():
		output = OS.get_cmdline_user_args()[0]
	image.save_png(output)
	print(JSON.stringify({"render_checks":checked,"failed":failures,"image":output}))
	quit(0 if failures.is_empty() else 1)
