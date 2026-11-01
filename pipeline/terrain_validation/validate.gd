extends Control
# Independent consumer of exported ZIP files. No production Python helpers.
var checks: Array = []
var captures: Dictionary = {}
var failed := false
var tabs: TabContainer

func check(ok: bool, description: String) -> void:
    checks.append({"passed":ok,"description":description})
    if not ok:
        failed=true
        push_error(description)

func variant_at(x: int,y: int,count: int,seed: int=17) -> int:
    var value := ((x*374761393)^(y*668265263)^seed)&0xffffffff
    value=((value^(value>>13))*1274126177)&0xffffffff
    return (value^(value>>16))%count

func manifest(role: String) -> Dictionary:
    return JSON.parse_string(FileAccess.get_file_as_string("res://assets/"+role+"/manifest.json"))

func same_pixels(a: Image,b: Image) -> bool:
    if a.get_size()!=b.get_size(): return false
    var left := a.duplicate() as Image
    var right := b.duplicate() as Image
    left.convert(Image.FORMAT_RGBA8);right.convert(Image.FORMAT_RGBA8)
    return left.get_data()==right.get_data()

func image_at(path: String) -> Image:
    var image:=Image.new()
    var error:=image.load_png_from_buffer(FileAccess.get_file_as_bytes(path))
    check(error==OK,"read exported PNG: "+path)
    return image

func tile_set(role: String,m: Dictionary) -> TileSet:
    var texture: Texture2D=load("res://assets/"+role+"/atlas.png")
    var raw := image_at("res://assets/"+role+"/atlas.png")
    check(same_pixels(texture.get_image(),raw),role+": imported atlas preserves source pixels")
    check(not texture.get_image().has_mipmaps(),role+": mipmaps disabled")
    var source := TileSetAtlasSource.new()
    source.texture=texture
    source.texture_region_size=Vector2i(m.tile_size,m.tile_size)
    var result := TileSet.new()
    result.tile_size=Vector2i(m.tile_size,m.tile_size)
    result.add_source(source,0)
    var entries: Array=[]
    if role=="water":
        entries=m.tiles
    else:
        for group in m.variants:
            entries.append({"atlas_cell":group.ground_cell,"image":group.ground})
            entries.append_array(group.tiles)
    for entry in entries:
        var cell := Vector2i(entry.atlas_cell[0],entry.atlas_cell[1])
        if not source.has_tile(cell): source.create_tile(cell)
        var crop := raw.get_region(Rect2i(cell*int(m.tile_size),Vector2i(m.tile_size,m.tile_size)))
        check(same_pixels(crop,image_at("res://assets/"+role+"/"+entry.image)),role+": atlas coordinate "+str(cell))
    return result


func validate_seams(role: String,water_masks: bool=false) -> void:
    var m:=manifest(role)
    var count: int=int(m.variants) if role=="water" else m.variants.size()
    var groups: Array=[]
    var size:=int(m.tile_size)
    for v in count:
        var group: Array=[]
        for b in 16:
            var tile: Dictionary=m.tiles[v*16+b] if role=="water" else m.variants[v].tiles[b]
            var relative: String=tile.water_mask if water_masks else tile.image
            group.append(image_at("res://assets/"+role+"/"+relative))
        groups.append(group)
    var pairs:=0
    var matches:=true
    for va in count:
        for vb in count:
            for a in 16:
                for b in 16:
                    var horizontal: bool
                    var vertical: bool
                    if role=="water":
                        horizontal=bool(a&2)==bool(b&1) and bool(a&4)==bool(b&8)
                        vertical=bool(a&8)==bool(b&1) and bool(a&4)==bool(b&2)
                    else:
                        horizontal=bool(a&2)==bool(b&8)
                        vertical=bool(a&4)==bool(b&1)
                    if horizontal:
                        pairs+=1
                        matches=matches and same_pixels(groups[va][a].get_region(Rect2i(size-1,0,1,size)),groups[vb][b].get_region(Rect2i(0,0,1,size)))
                    if vertical:
                        pairs+=1
                        matches=matches and same_pixels(groups[va][a].get_region(Rect2i(0,size-1,size,1)),groups[vb][b].get_region(Rect2i(0,0,size,1)))
    check(matches,role+(" masks" if water_masks else "")+": all "+str(pairs)+" legal cross-variant edges")


func road_grid() -> Array:
    var grid: Array=[]
    for y in 9:
        var row: Array=[]
        for x in 12: row.append(false)
        grid.append(row)
    for x in range(2,10): grid[2][x]=true;grid[6][x]=true
    for y in range(2,7): grid[y][2]=true;grid[y][9]=true;grid[y][6]=true
    for x in 12: grid[4][x]=true
    grid[0][6]=true;grid[1][6]=true;grid[8][4]=true
    return grid

func make_sample(role: String,title: String) -> void:
    var m:=manifest(role)
    var set:=tile_set(role,m)
    var size:=int(m.tile_size)
    var width:=16 if role=="water" else 12
    var height:=10 if role=="water" else 9
    var layer:=TileMapLayer.new()
    layer.tile_set=set
    layer.texture_filter=CanvasItem.TEXTURE_FILTER_NEAREST
    # Atlas tiles already occupy [cell * size, (cell + 1) * size).
    layer.position=Vector2.ZERO
    var cpu:=Image.create(width*size,height*size,false,Image.FORMAT_RGBA8)
    var atlas:=image_at("res://assets/"+role+"/atlas.png")
    atlas.convert(Image.FORMAT_RGBA8)
    var grid:=road_grid()
    for y in height:
        for x in width:
            var cell: Array
            var v:=variant_at(x,y,int(m.variants) if role=="water" else m.variants.size(),int(m.get("variant_seed",17)))
            if role=="water":
                var vertices: Array=m.example_vertices
                var bits:=int(vertices[y][x])+int(vertices[y][x+1])*2+int(vertices[y+1][x+1])*4+int(vertices[y+1][x])*8
                cell=m.tiles[v*16+bits].atlas_cell
            elif role=="material":
                cell=m.variants[v].ground_cell
            else:
                var bits:=0
                if grid[y][x]:
                    if y>0 and grid[y-1][x]: bits|=1
                    if x<width-1 and grid[y][x+1]: bits|=2
                    if y<height-1 and grid[y+1][x]: bits|=4
                    if x>0 and grid[y][x-1]: bits|=8
                cell=m.variants[v].tiles[bits].atlas_cell if grid[y][x] else m.variants[v].ground_cell
            var coord:=Vector2i(cell[0],cell[1])
            layer.set_cell(Vector2i(x,y),0,coord)
            check(layer.get_cell_atlas_coords(Vector2i(x,y))==coord,role+": cell "+str(Vector2i(x,y)))
            cpu.blit_rect(atlas,Rect2i(coord*size,Vector2i(size,size)),Vector2i(x*size,y*size))
    check(same_pixels(cpu,image_at("res://assets/"+role+"/preview.png")),role+": independent layout matches exported preview")
    add_sample(role,title,layer,Vector2i(width*size,height*size))

func add_sample(role: String,title: String,content: Node2D,dimensions: Vector2i) -> void:
    var viewport:=SubViewport.new()
    viewport.size=dimensions
    viewport.disable_3d=true
    viewport.render_target_update_mode=SubViewport.UPDATE_ALWAYS
    viewport.canvas_item_default_texture_filter=Viewport.DEFAULT_CANVAS_ITEM_TEXTURE_FILTER_NEAREST
    viewport.add_child(content)
    add_child(viewport)
    captures[role]=viewport
    var panel:=Control.new()
    panel.name=title
    tabs.add_child(panel)
    var view:=TextureRect.new()
    view.texture=viewport.get_texture()
    view.texture_filter=CanvasItem.TEXTURE_FILTER_NEAREST
    view.position=Vector2(12,12)
    view.size=dimensions
    panel.add_child(view)

func mask_sample() -> void:
    var m:=manifest("water")
    var size:=int(m.tile_size)
    var output:=Image.create(16*size,10*size,false,Image.FORMAT_RGBA8)
    var masks: Array=[]
    for tile in m.tiles:
        var image:=image_at("res://assets/water/"+tile.water_mask)
        check(image.get_size()==Vector2i(size,size),"water mask: dimensions "+tile.water_mask)
        check(image.get_pixel(0,0).r==(1.0 if int(tile.corners)&1 else 0.0),"water mask: NW bit "+tile.water_mask)
        check(image.get_pixel(size-1,0).r==(1.0 if int(tile.corners)&2 else 0.0),"water mask: NE bit "+tile.water_mask)
        check(image.get_pixel(size-1,size-1).r==(1.0 if int(tile.corners)&4 else 0.0),"water mask: SE bit "+tile.water_mask)
        check(image.get_pixel(0,size-1).r==(1.0 if int(tile.corners)&8 else 0.0),"water mask: SW bit "+tile.water_mask)
        image.convert(Image.FORMAT_RGBA8)
        masks.append(image)
    for y in 10:
        for x in 16:
            var v:=variant_at(x,y,int(m.variants))
            var vertices: Array=m.example_vertices
            var bits:=int(vertices[y][x])+int(vertices[y][x+1])*2+int(vertices[y+1][x+1])*4+int(vertices[y+1][x])*8
            output.blit_rect(masks[v*16+bits],Rect2i(0,0,size,size),Vector2i(x*size,y*size))
    var sprite:=Sprite2D.new()
    sprite.texture=ImageTexture.create_from_image(output)
    sprite.centered=false
    add_sample("mask","水面覆盖遮罩",sprite,output.get_size())
    output.save_png("res://qa/mask_expected.png")

func _ready() -> void:
    DirAccess.make_dir_recursive_absolute("res://qa")
    var heading:=Label.new()
    heading.text="素材接入验收 · 1倍像素 / 最近邻 · 仅静态素材，无游戏碰撞与水波动画"
    heading.position=Vector2(20,12)
    add_child(heading)
    tabs=TabContainer.new()
    tabs.position=Vector2(20,45);tabs.size=Vector2(1048,700)
    add_child(tabs)
    make_sample("road","草地与道路")
    make_sample("material","独立水面材质")
    make_sample("water","静态水岸")
    mask_sample()
    validate_seams("road")
    validate_seams("water")
    validate_seams("water",true)
    if "--qa" in OS.get_cmdline_user_args():
        for i in tabs.get_tab_count():
            tabs.current_tab=i
            await get_tree().process_frame
            await RenderingServer.frame_post_draw
        for role in captures:
            var capture: Image=captures[role].get_texture().get_image()
            check(capture!=null and not capture.is_empty(),role+": rendered capture available")
            if capture!=null and not capture.is_empty():
                capture.save_png("res://qa/"+role+"_render.png")
                var expected:=image_at("res://qa/mask_expected.png" if role=="mask" else "res://assets/"+role+"/preview.png")
                check(same_pixels(capture,expected),role+": actual TileMap render matches exported pixels")
    var report={"passed":not failed,"checks":checks,"engine":Engine.get_version_info().string,
        "scope":"ZIP consumption, imported pixels, atlas coordinates, road/corner rules, masks and rendered samples",
        "rendered_check": "--qa" in OS.get_cmdline_user_args(),
        "art_review":"pending","limitations":["No automatic TileSet terrain painting rules","No animation, collision or navigation"]}
    var report_path: String="res://qa/report.json" if "--qa" in OS.get_cmdline_user_args() else "res://qa/preview_session.json"
    var file:=FileAccess.open(report_path,FileAccess.WRITE)
    file.store_string(JSON.stringify(report,"  "));file.close()
    print("TERRAIN_INTEGRATION_", "PASS" if not failed else "FAIL", " checks=",checks.size())
    if "--qa" in OS.get_cmdline_user_args(): get_tree().quit(1 if failed else 0)
