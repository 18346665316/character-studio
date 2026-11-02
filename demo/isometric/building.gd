extends Node2D
const PLAYER = preload("res://building_player.gd")
var sorting: Node2D
var building: Node2D
var player: CharacterBody2D
var footprint: Polygon2D
var entrance: Vector2
var entrance_status: Label
var inside_entrance := false
var interactions := 0
var record: Dictionary
var grid_visible := true
var source_scale := .75

func _ready() -> void:
	RenderingServer.set_default_clear_color(Color("24313b"))
	texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	record = JSON.parse_string(FileAccess.get_file_as_string("res://assets/building.json"))
	source_scale = float(record.scale)
	var anchor := Vector2(record.anchor_px[0], record.anchor_px[1])
	for y in range(-6, 7):
		for x in range(-6, 7):
			var tile := Sprite2D.new()
			tile.z_index = -5
			tile.texture = load("res://assets/textures/ground_%d.png" % posmod(x * 3 + y * 5, 4))
			tile.position = Vector2(550 + (x-y)*64, 460 + (x+y)*32)
			add_child(tile)
	sorting = Node2D.new()
	sorting.y_sort_enabled = true
	add_child(sorting)
	building = Node2D.new()
	building.name = "Building"
	building.position = Vector2(550, 480)
	sorting.add_child(building)
	var sprite := Sprite2D.new()
	sprite.texture = load("res://assets/textures/building.png")
	sprite.centered = false
	sprite.position = -anchor * source_scale
	sprite.scale = Vector2.ONE * source_scale
	building.add_child(sprite)
	var points := PackedVector2Array()
	for p in record.footprint_px:
		points.append((Vector2(p[0], p[1])-anchor)*source_scale)
	var body := StaticBody2D.new()
	body.collision_layer = 1
	body.collision_mask = 2
	var shape := CollisionPolygon2D.new()
	shape.polygon = points
	body.add_child(shape)
	building.add_child(body)
	footprint = Polygon2D.new()
	footprint.polygon = points
	footprint.color = Color(1, .65, .15, .35)
	footprint.position = building.position
	footprint.z_index = 5
	footprint.visible = false
	add_child(footprint)
	entrance = building.position + (Vector2(record.entrance_px[0], record.entrance_px[1])-anchor)*source_scale
	player = PLAYER.new()
	player.position = Vector2(610, 620)
	sorting.add_child(player)
	var ui := CanvasLayer.new()
	add_child(ui)
	var panel := PanelContainer.new()
	panel.position = Vector2(20, 16)
	ui.add_child(panel)
	var column := VBoxContainer.new()
	panel.add_child(column)
	for text in ["建筑接入验证 · 真实生成素材 / 128×64 地格", "方向键移动 · F 占地 · G 地格 · E 入口测试 · R 复位 · 1/2/3 前/后/侧观察点", "占地为测试估计；整栋单图排序；人物仅验证比例，尚未匹配等距视角。"]:
		var label := Label.new()
		label.text = text
		column.add_child(label)
	entrance_status = Label.new()
	column.add_child(entrance_status)

func _process(_delta: float) -> void:
	inside_entrance = player.position.distance_to(entrance) < 30
	entrance_status.text = "入口范围内：按 E 测试交互（不切换室内）" if inside_entrance else "绕建筑走动，检查遮挡和碰撞；黄色圆圈为入口测试区。"
	if interactions > 0:
		entrance_status.text += "  已触发 %d 次" % interactions

func _draw() -> void:
	if grid_visible:
		for i in range(-7, 8):
			draw_line(Vector2(550+(i+7)*64,460+(i-7)*32), Vector2(550+(i-7)*64,460+(i+7)*32),Color(1,1,1,.14))
			draw_line(Vector2(550+(-7-i)*64,460+(-7+i)*32), Vector2(550+(7-i)*64,460+(7+i)*32),Color(1,1,1,.14))
	if entrance != Vector2.ZERO:
		draw_arc(entrance, 30, 0, TAU, 48, Color("ffd270"), 2)

func observation(index: int) -> void:
	# These are inspection positions, not navigation or pathfinding results.
	player.position = [Vector2(610,620), Vector2(550,350), Vector2(380,500)][index]

func _unhandled_key_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_F: footprint.visible = not footprint.visible
			KEY_G:
				grid_visible = not grid_visible
				queue_redraw()
			KEY_E:
				if inside_entrance: interactions += 1
			KEY_R: observation(0)
			KEY_1: observation(0)
			KEY_2: observation(1)
			KEY_3: observation(2)
			KEY_ESCAPE: get_tree().quit()
