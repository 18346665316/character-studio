extends Node2D
## Game-side controller for the unchanged Studio character package.
var appearance: Node2D
var jumping := false
var walk_speed := 150.0

func configure(scene_path: String) -> void:
	appearance = load(scene_path).instantiate()
	add_child(appearance)
	appearance.action_finished.connect(func(action: String):
		if action == "jump":
			jumping = false
			appearance.play_action("idle"))

func _physics_process(delta: float) -> void:
	var direction := Vector2(
		float(Input.is_physical_key_pressed(KEY_D) or Input.is_physical_key_pressed(KEY_RIGHT)) - float(Input.is_physical_key_pressed(KEY_A) or Input.is_physical_key_pressed(KEY_LEFT)),
		float(Input.is_physical_key_pressed(KEY_S) or Input.is_physical_key_pressed(KEY_DOWN)) - float(Input.is_physical_key_pressed(KEY_W) or Input.is_physical_key_pressed(KEY_UP)))
	var running := Input.is_physical_key_pressed(KEY_SHIFT)
	position += direction.normalized() * walk_speed * (1.7 if running else 1.0) * delta
	if absf(direction.x) > .01:
		appearance.set_mirrored(direction.x > 0)
	if not jumping:
		appearance.play_action("idle" if direction == Vector2.ZERO else ("run" if running else "walk"))

func _unhandled_key_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_SPACE and not jumping:
		jumping = appearance.play_action("jump", true)
