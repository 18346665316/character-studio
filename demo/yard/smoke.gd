extends SceneTree
var game: Node2D
var checks: Array=[]
var passed:=true
func _initialize() -> void:call_deferred("verify")
func record(ok: bool,label: String,details: Dictionary={}) -> void:
    checks.append({"passed":ok,"test":label,"details":details})
    if not ok:passed=false;push_error(label+" "+str(details))
func frames(count: int) -> void:
    for _i in range(count):await physics_frame
func press(action: String,count:=2) -> void:
    Input.action_press(action);await frames(count);Input.action_release(action);await frames(2)
func place(point: Vector2) -> void:
    game.player.position=point;game.player.velocity=Vector2.ZERO;await frames(3)
func travel(point: Vector2) -> void:
    var budget:=500
    while game.player.position.distance_to(point)>4 and not game.won and budget>0:
        var delta: Vector2=point-game.player.position
        var action: String=("move_right" if delta.x>0 else "move_left") if absf(delta.x)>4 else ("move_down" if delta.y>0 else "move_up")
        Input.action_press(action);await frames(1);Input.action_release(action);budget-=1
    await frames(2)
    record(budget>0,"reachable waypoint",{"target":[point.x,point.y],"end":[game.player.position.x,game.player.position.y]})
func verify() -> void:
    game=load("res://main.tscn").instantiate();root.add_child(game);await frames(5)
    var start: Vector2=game.player.position
    await press("move_right",15)
    var walked: float=game.player.position.x-start.x
    record(walked>20,"movement changes position",{"walked":walked})
    record(game.player.appearance.get_action()=="idle","release returns to idle")
    start=game.player.position
    Input.action_press("sprint");await press("move_right",15);Input.action_release("sprint")
    record(game.player.position.x-start.x>walked*1.3,"shift increases movement speed")
    await place(Vector2(340,555));await press("move_up",30)
    record(game.player.position.y>527,"rock footprint blocks player",{"end_y":game.player.position.y})
    await place(Vector2(300,645));await press("move_down",30)
    record(game.player.position.y<662,"closed fence blocks player")
    await place(Vector2(544,645));await press("move_down",30)
    record(game.player.position.y>690,"opening admits radius9 player")
    await place(Vector2(512,390));await press("move_up",30)
    record(game.player.position.y>360,"game-authored water blocker prevents entry")
    await press("interact");record(game.checked.count(true)==0,"distant interaction does not check a crate")
    await press("restart");record(game.player.position.distance_to(game.SPAWN)<1,"restart restores spawn")
    await travel(Vector2(544,480));await travel(Vector2(260,480));await travel(Vector2(260,375))
    await press("interact");record(game.checked.count(true)==1,"nearby E checks first crate")
    await press("interact");record(game.checked.count(true)==1,"same crate cannot count twice")
    await travel(Vector2(260,480));await travel(Vector2(900,480));await travel(Vector2(900,380))
    await press("interact");record(game.checked.count(true)==2,"second crate increments objective")
    await travel(Vector2(900,480));await travel(Vector2(900,620));await travel(Vector2(820,620));await travel(Vector2(820,595))
    await press("interact");record(game.checked.count(true)==3 and not game.won,"all crates still require returning to entrance")
    await travel(Vector2(820,640));await travel(Vector2(544,640));await travel(Vector2(544,608))
    record(game.won and not game.player.enabled,"returning to entrance completes game")
    await press("restart");record(not game.won and game.checked.count(true)==0 and game.player.enabled,"restart clears completed state")
    var report: Dictionary={"passed":passed,"engine":Engine.get_version_info().string,"checks":checks}
    var destination: String=ProjectSettings.globalize_path("res://../../.local/debug/props/yard-smoke.json")
    var file:=FileAccess.open(destination,FileAccess.WRITE);file.store_string(JSON.stringify(report,"  "));file.close()
    if not DisplayServer.get_name()=="headless":
        await process_frame;await RenderingServer.frame_post_draw
        root.get_texture().get_image().save_png(ProjectSettings.globalize_path("res://../../.local/debug/props/yard-demo.png"))
    print("YARD_SMOKE ",passed," checks=",checks.size())
    quit(0 if passed else 1)
