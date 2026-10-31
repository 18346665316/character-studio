extends SceneTree
## Run in a staged baker project with --headless --script test_framing.gd.
func _initialize() -> void:
    var baker = load("res://baker.gd")
    var a: Rect2 = baker.project_bounds(AABB(Vector3(-1, 0, -1), Vector3(2, 3, 2)), Transform3D.IDENTITY, Vector3.RIGHT)
    var deep: Rect2 = baker.project_bounds(AABB(Vector3(-1, 0, -100), Vector3(2, 3, 200)), Transform3D.IDENTITY, Vector3.RIGHT)
    assert(a.is_equal_approx(deep), "Camera depth must not shrink a front-view sprite")
    var moved: Rect2 = baker.project_bounds(AABB(Vector3(-1, 0, -1), Vector3(2, 3, 2)), Transform3D(Basis.IDENTITY, Vector3(4, 2, 90)), Vector3.RIGHT)
    assert(moved.position.is_equal_approx(a.position + Vector2(4, 2)), "Projected motion must be retained")
    assert(a.merge(moved).size.is_equal_approx(Vector2(6, 5)), "All frames must share the complete movement range")
    var side: Rect2 = baker.project_bounds(AABB(Vector3.ZERO, Vector3(2, 3, 5)), Transform3D.IDENTITY, Vector3.FORWARD)
    assert(side.size.is_equal_approx(Vector2(5, 3)), "Side framing must use depth as screen width")
    print("PROJECTED_FRAMING_QA_PASS")
    quit()
