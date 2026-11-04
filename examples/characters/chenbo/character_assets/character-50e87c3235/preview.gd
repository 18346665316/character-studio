extends Node2D
var actor: Node2D
func _ready():
    var base: String = get_script().resource_path.get_base_dir()
    actor = load(base+"/character.tscn").instantiate()
    actor.position = Vector2(480,350)
    add_child(actor)
    var layer := CanvasLayer.new()
    add_child(layer)
    var column := VBoxContainer.new()
    column.position = Vector2(24,24)
    layer.add_child(column)
    var label := Label.new()
    label.text = "CHARACTER STUDIO / asset preview\nGround anchor at crosshair · F1/F2/F3: 1×/2×/3×"
    column.add_child(label)
    for action in ["idle", "walk", "run", "jump"]:
        var button := Button.new()
        button.text = action
        button.pressed.connect(func(): actor.play_action(action))
        column.add_child(button)
    queue_redraw()
func _draw():
    draw_line(Vector2(250,350),Vector2(750,350),Color("6d9183"),1)
    draw_line(Vector2(480,335),Vector2(480,365),Color("c9dfd3"),1)
func _unhandled_key_input(event):
    if event.pressed and event.keycode in [KEY_F1,KEY_F2,KEY_F3]:
        actor.scale = Vector2.ONE*(event.keycode-KEY_F1+1)
