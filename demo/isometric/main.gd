extends Node2D
const Marker = preload("res://marker.gd")
var player: CharacterBody2D
var objects: Array[Node2D] = []
var footprints: Array[Polygon2D] = []
var status: Label
var sources: Dictionary
var sorting: Node2D

func _ready() -> void:
	RenderingServer.set_default_clear_color(Color("222c35"))
	sources = JSON.parse_string(FileAccess.get_file_as_string("res://assets/sources.json"))
	for y in range(7):
		for x in range(7):
			var tile := Sprite2D.new()
			tile.texture = load("res://assets/textures/ground_%d.png" % ((x * 3 + y * 5) % 4))
			tile.position = Vector2(550 + (x - y) * 64, 160 + (x + y) * 32)
			add_child(tile)
	sorting = Node2D.new()
	sorting.y_sort_enabled = true
	add_child(sorting)
	add_prop("rock", Vector2(440, 365))
	add_prop("crate", Vector2(650, 420))
	player = Marker.new()
	player.position = Vector2(550, 480)
	sorting.add_child(player)
	var ui := CanvasLayer.new()
	add_child(ui)
	var title := Label.new()
	title.text = "等距资产接入验证 · 2:1"
	title.position = Vector2(35, 24)
	title.add_theme_font_size_override("font_size", 28)
	ui.add_child(title)
	var hint := Label.new()
	hint.text = "方向键移动青色测试标记 · F 显示占地建议 · R 重置\n地格128×64；物件按占地中心排序，游戏自行启用建议碰撞。"
	hint.position = Vector2(35, 68)
	ui.add_child(hint)
	status = Label.new()
	status.position = Vector2(35, 660)
	var fixture_count := 0
	for item in sources.objects.values():
		if item.fixture:
			fixture_count += 1
	status.text = "草地复用已有素材，无新增AI调用。\n%d / 2 个物件为程序几何验证样本，非AI美术，不代表真实等距生成效果。" % fixture_count
	ui.add_child(status)

func add_prop(kind: String, at: Vector2) -> void:
	var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://assets/%s.json" % kind))
	var actor := Node2D.new()
	actor.position = at
	actor.scale = Vector2(0.6, 0.6)
	sorting.add_child(actor)
	objects.append(actor)
	var sprite := Sprite2D.new()
	sprite.texture = load("res://assets/textures/%s.png" % kind)
	sprite.centered = false
	sprite.offset = Vector2(manifest.sprite_offset_px[0], manifest.sprite_offset_px[1])
	actor.add_child(sprite)
	var points := PackedVector2Array()
	for point in manifest.suggested_collision.polygon:
		points.append(Vector2(point[0], point[1]))
	if points.size() >= 3:
		# This validation game explicitly enables a suggestion. Studio exports it disabled.
		var body := StaticBody2D.new()
		var collider := CollisionPolygon2D.new()
		collider.polygon = points
		body.add_child(collider)
		actor.add_child(body)
		var footprint := Polygon2D.new()
		footprint.polygon = points
		footprint.color = Color(1, 0.65, 0.2, 0.5)
		footprint.z_index = 2
		footprint.visible = false
		actor.add_child(footprint)
		footprints.append(footprint)

func _unhandled_key_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		get_tree().quit()
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_F:
			for footprint in footprints:
				footprint.visible = not footprint.visible
		if event.keycode == KEY_R:
			player.position = Vector2(550, 480)
