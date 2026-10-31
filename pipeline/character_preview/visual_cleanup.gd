extends RefCounted
## Hide only explicitly reviewed detached components in the runtime copy.
## Original FBX, UVs, vertices, bone weights and bind matrices remain intact.

static func hide_reviewed_components(mesh: Mesh, expected: PackedInt32Array) -> Mesh:
    if expected.is_empty() or mesh.get_surface_count() != 1:
        return mesh
    var arrays := mesh.surface_get_arrays(0)
    var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
    var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
    if indices.is_empty():
        return mesh
    var parents := PackedInt32Array()
    parents.resize(vertices.size())
    var welded := {}
    for vertex in range(vertices.size()):
        # Reconstruction FBX is ~0.017 m tall before runtime normalization.
        var key := Vector3i((vertices[vertex] * 100000000.0).round())
        if welded.has(key):
            parents[vertex] = welded[key]
        else:
            parents[vertex] = vertex
            welded[key] = vertex
    for face in range(0, indices.size(), 3):
        for corner in [1, 2]:
            var left := _root(parents, indices[face])
            var right := _root(parents, indices[face + corner])
            parents[right] = left
    var counts := {}
    for face in range(0, indices.size(), 3):
        var component := _root(parents, indices[face])
        counts[component] = int(counts.get(component, 0)) + 1
    var reviewed_roots := {}
    for size_value in expected:
        var matching := []
        for component in counts:
            if counts[component] == size_value:
                matching.append(component)
        if matching.size() != 1:
            push_warning("Reviewed accessory signature changed; preserving original geometry")
            return mesh
        reviewed_roots[matching[0]] = true
    var kept := PackedInt32Array()
    for face in range(0, indices.size(), 3):
        if not reviewed_roots.has(_root(parents, indices[face])):
            kept.append(indices[face])
            kept.append(indices[face + 1])
            kept.append(indices[face + 2])
    if kept.size() < indices.size() * 0.9:
        push_warning("Accessory cleanup would remove too much geometry; preserving original")
        return mesh
    arrays[Mesh.ARRAY_INDEX] = kept
    var cleaned := ArrayMesh.new()
    cleaned.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
    cleaned.surface_set_material(0, mesh.surface_get_material(0))
    print("Reviewed accessory cleanup: ", indices.size() / 3, " -> ", kept.size() / 3, " triangles")
    return cleaned

static func _root(parents: PackedInt32Array, vertex: int) -> int:
    var current := vertex
    while parents[current] != current:
        parents[current] = parents[parents[current]]
        current = parents[current]
    return current
