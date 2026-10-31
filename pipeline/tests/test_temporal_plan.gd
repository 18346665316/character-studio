extends SceneTree

func _initialize() -> void:
    var planner = load('res://temporal_plan.gd')
    for rate in [24,30,60]:
        var clip := Animation.new()
        clip.length = 10.0
        var track := clip.add_track(Animation.TYPE_POSITION_3D)
        for i in range(rate*10+1):
            clip.position_track_insert_key(track,float(i)/rate,Vector3(float(i),0,0))
        var plan: Dictionary = planner.plan(clip)
        assert(plan.frame_count == 300, str(plan))
        assert(is_equal_approx(plan.source_fps,float(rate)),str(plan))
        assert(plan.rows == int(ceil(float(plan.frame_count)/16.0)))
    # Sparse interpolation must retain motion between authored keys.
    var sparse := Animation.new()
    sparse.length = 1.0
    var track := sparse.add_track(Animation.TYPE_POSITION_3D)
    sparse.position_track_insert_key(track,0.0,Vector3.ZERO)
    sparse.position_track_insert_key(track,0.5,Vector3.UP)
    sparse.position_track_insert_key(track,1.0,Vector3.ZERO)
    assert(planner.plan(sparse).frame_count == 30)
    assert(planner.plan(sparse).source_fps == 2.0)
    var short_clip := Animation.new()
    short_clip.length = 0.1
    assert(planner.plan(short_clip).frame_count == 3)
    assert(planner.plan(short_clip).cadence_basis == 'fallback_30')
    print('Temporal plan: 24/30/60 FPS, sparse interpolation, complete duration, short clip and fallback passed')
    quit()
