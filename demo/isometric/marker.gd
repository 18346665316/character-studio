extends CharacterBody2D
var enabled := true
func _ready() -> void:
	var collision := CollisionShape2D.new()
	var shape := CircleShape2D.new()
	shape.radius = 7
	collision.shape = shape
	add_child(collision)
func _physics_process(_delta: float) -> void:
	if not enabled:
		return
	velocity = Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down") * 170
	move_and_slide()
func _draw() -> void:
	draw_circle(Vector2(0, -10), 12, Color("56e8db"))
	draw_circle(Vector2.ZERO, 4, Color.WHITE)
