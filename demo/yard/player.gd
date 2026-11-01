extends CharacterBody2D
const WALK_SPEED:=130.0
const RUN_SPEED:=210.0
var appearance: Node2D
var enabled:=true

func _ready() -> void:
    name="Player"
    collision_layer=2;collision_mask=1
    motion_mode=CharacterBody2D.MOTION_MODE_FLOATING
    var shape:=CollisionShape2D.new()
    var circle:=CircleShape2D.new();circle.radius=9
    shape.shape=circle;add_child(shape)
    appearance=load("res://assets/character_assets/hunyuan-guard/character.tscn").instantiate()
    add_child(appearance)
    add_to_group("player")

func _physics_process(_delta: float) -> void:
    var direction:=Input.get_vector("move_left","move_right","move_up","move_down") if enabled else Vector2.ZERO
    var running:=Input.is_action_pressed("sprint")
    velocity=direction*(RUN_SPEED if running else WALK_SPEED)
    move_and_slide()
    # This source-authored view faces left; mirror only when moving right.
    if absf(direction.x)>.01: appearance.set_mirrored(direction.x>0)
    appearance.play_action("idle" if direction==Vector2.ZERO else "run" if running else "walk")
