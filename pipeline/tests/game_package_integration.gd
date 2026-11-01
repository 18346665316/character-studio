extends SceneTree
var finished: Array = []
func _initialize(): call_deferred("verify")
func verify():
    var actor = load(OS.get_cmdline_user_args()[0]).instantiate()
    root.add_child(actor)
    actor.position = Vector2(100,200)
    await process_frame
    actor.action_finished.connect(func(action): finished.append(action))
    assert(actor.has_action("walk"))
    assert(not actor.play_action("missing"))
    assert(actor.get_action()=="idle")
    for action in ["walk","run"]:
        assert(actor.play_action(action))
        var before: Vector2 = actor.position
        actor.position.x += 20
        assert(actor.position.x>before.x)
        actor.get_node("Sprite").set_frame_and_progress(1,0.5)
        actor.play_action(action)
        assert(actor.get_node("Sprite").frame==1)
    actor.play_action("jump",true)
    var offset: Vector2 = actor.get_node("Sprite").offset
    actor.set_mirrored(true)
    assert(actor.get_node("Sprite").offset.is_equal_approx(Vector2(-offset.x,offset.y)))
    var deadline = Time.get_ticks_msec()+5000
    while finished.is_empty() and Time.get_ticks_msec()<deadline:
        await process_frame
    assert(finished==["jump"],"one-shot did not emit exactly one completion")
    assert(actor.get_action()=="jump")
    actor.play_action("idle")
    assert(actor.get_action()=="idle")
    print("AI_CONTRACT_INTEGRATION_PASS movement/action/restart/mirror/completion/recovery")
    quit()
