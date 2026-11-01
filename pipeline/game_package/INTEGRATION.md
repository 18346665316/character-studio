# Character asset integration

Read `asset.json` first. Paths inside that contract are relative to its directory.
Copy the entire character_assets folder into your Godot 4 project. Do not copy
project.godot over an existing project. Instantiate character.tscn under your
controller/CharacterBody2D. The instance root is the ground anchor in pixel units.

Public API (call after adding the instance to the scene tree):

```gdscript
var visual = preload("character.tscn").instantiate() # adjust path for your script
add_child(visual)
visual.action_finished.connect(_on_action_finished)
visual.play_action("walk")
# Repeated walk calls continue playback. To replay a completed one-shot:
visual.play_action("jump", true)
# Invalid actions return false without altering playback.
```

The game owns movement, collision, speed and gameplay state. Do not guess movement
speed from frame count or PNG dimensions. Build game input/state separately.
`action_finished(action)` fires once per completed non-looping action. Choose your
own next state; the asset does not automatically return to idle.

Jump elevation is already in the images. Adding a second visual jump offset will
double its apparent height. Horizontal raster displacement may remain in source
clips. Review before choosing platformer versus ground-plane behavior.

Only the view listed in asset.json exists. `set_mirrored(true)` mirrors it while
keeping the ground anchor fixed; this is not an eight-direction character.
Equipment in the images cannot be detached at runtime. Semantic roles are user
assignments: check validation warnings, source clips and preview before treating
an idle or loop as production-approved. Structural validation does not certify art.

Use preview.tscn to inspect actions against the ground line. Use integer scaling
and nearest filtering; retain per-frame durations rather than using an average FPS.
