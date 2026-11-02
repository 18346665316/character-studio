extends SceneTree
var checks: Array[String] = []
var failures: Array[String] = []
var scene: Node2D
func check(ok: bool, label: String) -> void:
	checks.append(label)
	if not ok:
		failures.append(label)
func _initialize() -> void:
	call_deferred("run")
func frames(count: int) -> void:
	for i in count:
		await physics_frame
func run() -> void:
	scene = load("res://main.tscn").instantiate()
	root.add_child(scene)
	await frames(3)
	check(scene.sorting.y_sort_enabled, "shared Y sorting enabled")
	check(scene.player.get_parent() == scene.sorting, "marker shares sorting parent")
	for object in scene.objects:
		check(object.get_parent() == scene.sorting, "object shares sorting parent")
		var sprite: Sprite2D = object.get_child(0)
		check(sprite.texture.get_width() == 256, "unaltered object canvas imported")
	check(scene.player.position.is_equal_approx(Vector2(550,480)), "spawn position")
	Input.action_press("ui_right")
	await frames(20)
	Input.action_release("ui_right")
	await frames(2)
	check(scene.player.position.x > 590, "real input moves marker")
	for i in scene.objects.size():
		var object: Node2D = scene.objects[i]
		scene.player.position = object.position + Vector2(0,75)
		Input.action_press("ui_up")
		await frames(40)
		Input.action_release("ui_up")
		await frames(2)
		check(scene.player.position.y > object.position.y + 7, "object ground footprint blocks movement %d" % i)
	var report := {"checks":checks.size(),"failed":failures,"graphics_verified":false}
	var file := FileAccess.open("user://isometric-smoke.json",FileAccess.WRITE)
	file.store_string(JSON.stringify(report,"\t"))
	print(JSON.stringify(report))
	quit(0 if failures.is_empty() else 1)
