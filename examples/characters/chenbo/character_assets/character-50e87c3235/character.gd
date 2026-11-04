extends Node2D
## Public asset API. Root position is the ground anchor; game owns physics.
signal action_finished(action: String)
@onready var sprite: AnimatedSprite2D = $Sprite
func _ready():
    sprite.animation_finished.connect(func(): action_finished.emit(String(sprite.animation)))
    play_action("idle")
func has_action(action: String) -> bool:
    return sprite.sprite_frames.has_animation(action)
func get_action() -> String:
    return String(sprite.animation)
func play_action(action: String, restart: bool = false) -> bool:
    if not has_action(action): return false
    if restart: sprite.stop()
    sprite.play(action)
    _apply_anchor()
    return true
func set_mirrored(value: bool):
    sprite.flip_h = value
    _apply_anchor()
func _apply_anchor():
    var offset: Array = OFFSETS[String(sprite.animation)]
    sprite.offset = Vector2(-float(offset[0]) if sprite.flip_h else float(offset[0]),float(offset[1]))

const OFFSETS = {"idle": [-2.0, -52.0], "walk": [-2.0, -52.0], "run": [-2.0, -52.0], "jump": [-2.0, -52.0]}
