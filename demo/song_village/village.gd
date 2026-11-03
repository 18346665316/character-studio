extends Node2D
## Isolated visual trial assembled from Studio exports. No generation at runtime.
const CELL := Vector2(128, 64)
var camera: Camera2D
var layout: Dictionary
var show_grid := false
var dragging := false
var view_index := 0
var player: Node2D
var follow_player := true

func set_view(index: int) -> void:
	follow_player = false
	view_index = index
	var view: Dictionary = layout.viewpoints[index]
	camera.position = Vector2(view.position[0], view.position[1])
	camera.zoom = Vector2.ONE * float(view.zoom)

func grid_point(x: int, y: int) -> Vector2:
	return Vector2((x - y) * CELL.x * .5, (x + y) * CELL.y * .5)

func _ready() -> void:
	RenderingServer.set_default_clear_color(Color("283c36"))
	texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	layout = JSON.parse_string(FileAccess.get_file_as_string("res://assets/layout.json"))
	for cell in layout.tiles:
		var tile := Sprite2D.new()
		tile.texture = load("res://assets/" + cell.image)
		tile.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		tile.position = Vector2(cell.position[0], cell.position[1])
		add_child(tile)
	var sorted_world := Node2D.new()
	sorted_world.y_sort_enabled = true
	add_child(sorted_world)
	for item in layout.objects:
		var origin := Node2D.new()
		origin.name = item.name
		origin.position = Vector2(item.position[0], item.position[1])
		sorted_world.add_child(origin)
		var art := Sprite2D.new()
		art.texture = load("res://assets/" + item.image)
		art.centered = false
		art.position = -Vector2(item.anchor[0], item.anchor[1]) * float(item.scale)
		art.scale = Vector2.ONE * float(item.scale)
		origin.add_child(art)
	player = preload("res://village_actor.gd").new()
	player.name = "Player"
	player.position = Vector2(650, 300)
	sorted_world.add_child(player)
	player.configure("res://assets/" + layout.sources.actor.scene)
	camera = Camera2D.new()
	add_child(camera)
	camera.position = player.position
	camera.zoom = Vector2.ONE * 1.4
	var ui := CanvasLayer.new()
	add_child(ui)
	var panel := PanelContainer.new()
	panel.position = Vector2(24, 20)
	ui.add_child(panel)
	var margin := MarginContainer.new()
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 14)
	panel.add_child(margin)
	var column := VBoxContainer.new()
	margin.add_child(column)
	var title := Label.new()
	title.text = "宋村 · 江南春日"
	title.add_theme_font_size_override("font_size", 26)
	column.add_child(title)
	var subtitle := Label.new()
	subtitle.text = "Studio 素材试制  /  %d 类素材  /  2:1 等距村庄" % layout.sources.size()
	column.add_child(subtitle)
	var controls := Label.new()
	controls.text = "WASD / 方向键移动 · Shift 奔跑 · 空格跳跃 · F 跟随人物 · 拖动 / 滚轮缩放 · 1–4 场景 · G 地格"
	column.add_child(controls)
	var scope := Label.new()
	scope.text = "独立素材试摆 · 院墙与门洞待 Studio 生产 · 当前没有物体碰撞或院落遮挡"
	scope.modulate = Color("c6cab6")
	column.add_child(scope)
	if "--capture" in OS.get_cmdline_user_args():
		await RenderingServer.frame_post_draw
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(ProjectSettings.globalize_path("res://assets/character-preview.png"))
		for i in range(4):
			set_view(i)
			await RenderingServer.frame_post_draw
			await RenderingServer.frame_post_draw
			get_viewport().get_texture().get_image().save_png(ProjectSettings.globalize_path("res://assets/village-view-%d.png" % i))
		set_view(0)
		await RenderingServer.frame_post_draw
		await RenderingServer.frame_post_draw
		var path := ProjectSettings.globalize_path("res://assets/village-preview.png")
		get_viewport().get_texture().get_image().save_png(path)
		print("VILLAGE_CAPTURE ", path)
		get_tree().quit()

func _process(delta: float) -> void:
	if follow_player:
		camera.position = camera.position.lerp(player.position, minf(delta * 10, 1))

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_LEFT or event.button_index == MOUSE_BUTTON_MIDDLE:
			dragging = event.pressed
		if event.pressed and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
			var factor := 1.1 if event.button_index == MOUSE_BUTTON_WHEEL_UP else 1.0 / 1.1
			camera.zoom = Vector2.ONE * clampf(camera.zoom.x * factor, .18, 1.6)
	elif event is InputEventMouseMotion and dragging:
		follow_player = false
		camera.position -= event.relative / camera.zoom.x
	elif event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_G:
			show_grid = not show_grid
			queue_redraw()
		elif event.keycode == KEY_F:
			follow_player = true
			camera.zoom = Vector2.ONE * 1.4
		elif event.keycode == KEY_R:
			set_view(0)
		elif event.keycode >= KEY_1 and event.keycode <= KEY_4:
			set_view(event.keycode-KEY_1)

func _draw() -> void:
	if not show_grid:
		return
	var radius: int = int(layout.map_cells)/2
	for x in range(-radius, radius+1):
		draw_line(grid_point(x, -radius), grid_point(x, radius), Color(1, 1, 1, .2), 1)
	for y in range(-radius, radius+1):
		draw_line(grid_point(-radius, y), grid_point(radius, y), Color(1, 1, 1, .2), 1)
