extends RefCounted
## Key spacing is diagnostic, not source FPS: sparse tracks still interpolate motion.
static func plan(clip: Animation) -> Dictionary:
    var intervals: Array[float] = []
    for track in range(clip.get_track_count()):
        if clip.track_get_type(track) not in [Animation.TYPE_POSITION_3D,Animation.TYPE_ROTATION_3D,Animation.TYPE_SCALE_3D]: continue
        var count := clip.track_get_key_count(track)
        for key in range(1,count):
            var delta := clip.track_get_key_time(track,key)-clip.track_get_key_time(track,key-1)
            if delta > 0.00001: intervals.append(delta)
    intervals.sort()
    var source_fps := 1.0 / intervals[int(intervals.size()/2)] if not intervals.is_empty() else 30.0
    # Round import float noise near common integer rates, preserving 29.97 etc.
    if absf(source_fps-roundf(source_fps)) < 0.01: source_fps=roundf(source_fps)
    var target := 30.0
    var count := maxi(1,int(ceil(clip.length*target-0.00001)))
    return {"duration_seconds":clip.length,"frame_count":count,"fps":float(count)/clip.length,
        "source_fps":source_fps,"target_fps":target,"sampling_policy":"fixed_30_before_pixel_compaction_v2",
        "cadence_basis":"median_imported_key_interval" if not intervals.is_empty() else "fallback_30",
        "columns":mini(count,16),"rows":int(ceil(float(count)/16.0))}
