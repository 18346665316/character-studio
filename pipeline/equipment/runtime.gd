extends RefCounted
## Coordinates: hand points in source hand-bone space; weapon points in metres.
static func frame(points: Array) -> Transform3D:
    var origin := Vector3(points[0][0],points[0][1],points[0][2])
    var axis := (Vector3(points[1][0],points[1][1],points[1][2])-origin).normalized()
    var side := Vector3(points[2][0],points[2][1],points[2][2])-origin
    side = (side-axis*side.dot(axis)).normalized()
    return Transform3D(Basis(side,axis,side.cross(axis).normalized()),origin)

static func sword() -> Node3D:
    var root := Node3D.new()
    # grip is at (0,0,0), blade points +Y, blade face points +Z.
    for part in [[Vector3(0,0,0),Vector3(0.028,0.14,0.028),Color("50392c")],
                 [Vector3(0,0.085,0),Vector3(0.18,0.025,0.045),Color("bba360")],
                 [Vector3(0,0.40,0),Vector3(0.065,0.60,0.018),Color("bccbd0")],
                 [Vector3(0,-0.09,0),Vector3(0.048,0.035,0.048),Color("bba360")]]:
        var mesh := MeshInstance3D.new()
        var box := BoxMesh.new()
        box.size=part[1]
        var material := StandardMaterial3D.new()
        material.albedo_color=part[2]
        material.roughness=0.8
        box.material=material
        mesh.mesh=box
        mesh.position=part[0]
        root.add_child(mesh)
    return root

static func attach(skeleton: Skeleton3D, config: Dictionary) -> Node3D:
    var attachment := BoneAttachment3D.new()
    attachment.bone_name=config.bone
    skeleton.add_child(attachment)
    var weapon := sword()
    attachment.add_child(weapon)
    var hand := frame(config.hand_points)
    var grip := frame(config.weapon_points)
    var basis := hand.basis * grip.basis.inverse() * float(config.source_units_per_meter) * float(config.weapon_scale)
    weapon.transform=Transform3D(basis,hand.origin-basis*grip.origin)
    return attachment
