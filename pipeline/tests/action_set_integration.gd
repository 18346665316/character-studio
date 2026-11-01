extends SceneTree
# Run against any exported action set, including sets without idle or jump.
var finished: Array = []
func _initialize(): call_deferred("verify")
func verify():
    var scene_path: String = OS.get_cmdline_user_args()[0]
    var base := scene_path.get_base_dir()
    var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(base+"/manifest.json"))
    var actor = load(scene_path).instantiate()
    root.add_child(actor)
    await process_frame
    var sprite: AnimatedSprite2D = actor.get_node("Sprite")
    actor.action_finished.connect(func(action): finished.append(action))
    assert(sprite.sprite_frames.get_animation_names().size()==manifest.actions.size())
    for action in manifest.actions:
        var record: Dictionary = manifest.actions[action]
        assert(actor.play_action(action,true))
        assert(actor.get_action()==action)
        assert(sprite.sprite_frames.get_animation_loop(action)==record.loop)
        assert(sprite.sprite_frames.get_frame_count(action)==record.frame_count)
        var seconds := 0.0
        for frame in record.frame_count:
            seconds += sprite.sprite_frames.get_frame_duration(action,frame)/sprite.sprite_frames.get_animation_speed(action)
        assert(abs(seconds-record.duration_seconds)<0.00001)
        var anchor: Array = record.anchor_px
        var expected := Vector2(record.frame_size/2.0-float(anchor[0]),record.frame_size/2.0-float(anchor[1]))
        actor.set_mirrored(false)
        assert(sprite.offset.is_equal_approx(expected))
        actor.set_mirrored(true)
        assert(sprite.offset.is_equal_approx(Vector2(-expected.x,expected.y)))
        if not record.loop:
            finished.clear()
            sprite.speed_scale = maxf(1.0,float(record.duration_seconds)/0.05)
            var deadline := Time.get_ticks_msec()+2000
            while finished.is_empty() and Time.get_ticks_msec()<deadline: await process_frame
            assert(finished==[action])
            assert(sprite.frame==record.frame_count-1)
            assert(actor.get_action()==action)
            sprite.speed_scale = 1.0
    print("ACTION_SET_INTEGRATION_PASS actions/loops/timing/anchors/completion")
    quit()
