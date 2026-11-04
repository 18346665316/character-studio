extends Node2D
# One standard human; legacy scene coordinates remain unchanged.
const HUMAN_HEIGHT: float = 34.0
var player: CharacterBody2D
var camera: Camera2D
var data: Dictionary
var blockers: Array = []
var debug_collision := false
func _ready():
	RenderingServer.set_default_clear_color(Color("34443e"))
	data = JSON.parse_string(FileAccess.get_file_as_string("res://scene.json"))
	var world := Node2D.new()
	world.y_sort_enabled = true
	add_child(world)
	var modules := {}
	for module in data.modules:
		modules[module.id] = module
	for item in data.instances:
		var module: Dictionary = modules[item.module]
		var world_scale := float(module.get("world_scale", 1.0))
		var origin := Node2D.new()
		origin.position = Vector2(item.position[0], item.position[1])
		world.add_child(origin)
		if module.get("layer", "objects") == "ground":
			origin.z_index = -1
		if module.has("character_scene"):
			var actor = load("res://"+module.character_scene).instantiate()
			actor.name="Character"
			actor.scale=Vector2.ONE*world_scale
			origin.add_child(actor)
		else:
			if module.has("occlusion_slices"):
				# Each narrow strip sorts against the player's feet at its local wall baseline.
				for strip in module.occlusion_slices:
					var strip_origin := Node2D.new()
					strip_origin.position = origin.position + Vector2(0,float(strip.foot_y)*world_scale)
					world.add_child(strip_origin)
					var art := Sprite2D.new()
					art.texture = load("res://images/" + module.image)
					art.centered = false
					art.region_enabled = true
					art.region_rect = Rect2(float(strip.x),0,float(strip.width),float(module.canvas_px[1]))
					art.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
					art.position = Vector2(float(strip.x)-float(module.anchor[0]),-float(module.anchor[1])-float(strip.foot_y))*world_scale
					art.scale = Vector2.ONE*world_scale
					strip_origin.add_child(art)
			else:
				var art := Sprite2D.new()
				art.texture = load("res://images/" + module.image)
				art.centered = false
				art.position = -Vector2(module.anchor[0], module.anchor[1]) * world_scale
				art.scale = Vector2.ONE * world_scale
				origin.add_child(art)
		for poly in module.polygons:
			var body := StaticBody2D.new()
			body.set_meta("module_title",module.title)
			body.collision_layer = 1
			body.collision_mask = 2
			var shape := CollisionPolygon2D.new()
			var points := PackedVector2Array()
			for p in poly:
				points.append(Vector2(p[0], p[1]) * world_scale)
			shape.polygon = points
			body.add_child(shape)
			origin.add_child(body)
			blockers.append({"position": origin.position, "polygon": points})
	player = CharacterBody2D.new()
	player.name = "Player"
	player.motion_mode = CharacterBody2D.MOTION_MODE_FLOATING
	player.collision_layer = 2
	player.collision_mask = 1
	player.position = Vector2(data.spawn[0], data.spawn[1])
	var collider := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 8
	collider.shape = circle
	player.add_child(collider)
	var visual := Polygon2D.new()
	visual.polygon = PackedVector2Array([Vector2(-8,0),Vector2(-8,-HUMAN_HEIGHT*24.0/34.0),Vector2(0,-HUMAN_HEIGHT),Vector2(8,-HUMAN_HEIGHT*24.0/34.0),Vector2(8,0)])
	visual.color = Color("f5ce72")
	player.add_child(visual)
	world.add_child(player)
	camera = Camera2D.new()
	add_child(camera)
	var ui := CanvasLayer.new()
	add_child(ui)
	var label := Label.new()
	label.position = Vector2(20,20)
	label.text = "Studio 模块场景验收 · WASD / 方向键移动 · C 碰撞范围\n标准人高 = 1 · 黄色角色用于尺度与通行对比"
	ui.add_child(label)
func _physics_process(_delta):
	var direction := Vector2(float(Input.is_physical_key_pressed(KEY_D) or Input.is_physical_key_pressed(KEY_RIGHT))-float(Input.is_physical_key_pressed(KEY_A) or Input.is_physical_key_pressed(KEY_LEFT)), float(Input.is_physical_key_pressed(KEY_S) or Input.is_physical_key_pressed(KEY_DOWN))-float(Input.is_physical_key_pressed(KEY_W) or Input.is_physical_key_pressed(KEY_UP)))
	player.velocity = direction.normalized() * 180
	player.move_and_slide()
	camera.position = player.position
func _unhandled_key_input(event):
	if event.pressed and not event.echo and event.keycode == KEY_C:
		debug_collision = not debug_collision
		queue_redraw()
func _draw():
	if debug_collision:
		for blocker in blockers:
			var polygon := PackedVector2Array()
			for p in blocker.polygon:
				polygon.append(p + blocker.position)
			draw_colored_polygon(polygon, Color(1,.3,.2,.4))
