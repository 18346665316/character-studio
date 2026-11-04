extends Node2D
## A consumer of the unmodified Studio export; all motion is baked into its sprites.
const CHARACTER = preload("res://character_assets/character-50e87c3235/character.tscn")
const ACTIONS = ["idle", "walk", "run", "jump"]
var actors: Array[Node2D] = []
var mirrored := false

func text_at(value: String, point: Vector2, size_px: int, color := Color("dce7e6")):
	var label := Label.new()
	label.text = value
	label.position = point
	label.add_theme_font_size_override("font_size", size_px)
	label.add_theme_color_override("font_color", color)
	add_child(label)

func _ready():
	RenderingServer.set_default_clear_color(Color("152328"))
	text_at("One character. A whole set of motion.", Vector2(32, 25), 32)
	text_at("PIXEL ANIMATION STUDIO  /  CHENBO  /  GODOT 4", Vector2(34, 76), 15, Color("93b7aa"))
	text_at("01  SOURCE ART", Vector2(34, 132), 17)
	var reference := Sprite2D.new()
	reference.texture = preload("res://reference.png")
	reference.position = Vector2(34, 170)
	reference.centered = false
	reference.scale = Vector2.ONE * (270.0 / reference.texture.get_width())
	reference.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	add_child(reference)
	text_at("02  EXPORTED 2D ACTIONS", Vector2(340, 132), 17)
	for index in ACTIONS.size():
		var x := 444.0 + index * 224.0
		var actor := CHARACTER.instantiate()
		actor.position = Vector2(x, 424)
		actor.scale = Vector2.ONE * 2
		add_child(actor)
		actor.play_action(ACTIONS[index], true)
		actors.append(actor)
		text_at(ACTIONS[index].to_upper(), Vector2(x - 36, 188), 18)
		text_at("LOOP" if index < 3 else "ONE-SHOT", Vector2(x - 36, 216), 12, Color("93b7aa"))
	text_at("Existing source art + rig + motion clips. No new generation for this showcase.", Vector2(34, 492), 16)
	text_at("One fixed view  /  96 px body at 2x  /  original frame timing  /  shared ground anchors", Vector2(34, 520), 15, Color("93b7aa"))
	var replay := Button.new()
	replay.text = "Replay all actions"
	replay.position = Vector2(34, 562)
	replay.pressed.connect(restart)
	add_child(replay)
	var mirror := Button.new()
	mirror.text = "Mirror horizontally"
	mirror.position = Vector2(210, 562)
	mirror.pressed.connect(func():
		mirrored = not mirrored
		for actor in actors: actor.set_mirrored(mirrored))
	add_child(mirror)
	text_at("Animation playback sample / game movement and physics are separate.", Vector2(446, 568), 14, Color("93b7aa"))
	queue_redraw()

func restart():
	for index in actors.size(): actors[index].play_action(ACTIONS[index], true)

func _draw():
	for index in ACTIONS.size():
		var x := 444.0 + index * 224.0
		draw_line(Vector2(x - 68, 424), Vector2(x + 68, 424), Color("3c5d59"))
		draw_line(Vector2(x, 420), Vector2(x, 429), Color("93b7aa"))
