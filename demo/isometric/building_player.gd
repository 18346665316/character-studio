extends CharacterBody2D
var enabled := true
var appearance: Node2D

func _ready() -> void:
	name = "Player"
	collision_layer = 2
	collision_mask = 1
	motion_mode = CharacterBody2D.MOTION_MODE_FLOATING
	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 8
	shape.shape = circle
	add_child(shape)
	appearance = load("res://assets/character_assets/hunyuan-guard/character.tscn").instantiate()
	add_child(appearance)
	add_to_group("player")

func _physics_process(_delta: float) -> void:
	var direction := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down") if enabled else Vector2.ZERO
	velocity = direction * 150
	move_and_slide()
	if absf(direction.x) > .01:
		appearance.set_mirrored(direction.x > 0)
	appearance.play_action("idle" if direction == Vector2.ZERO else "walk")
