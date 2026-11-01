# 小庭院巡查

独立的 Godot 4.6 游戏演示，使用 Studio 已有人物、草地道路、水岸、围栏、石头、木箱和灌木。目标是检查三只木箱，然后返回下方青色入口圆环。

双击 `play.command` 运行，或在 Godot 中打开本目录的 `project.godot`。它不依赖 Studio 服务或图片 API。

| 操作 | 按键 |
| --- | --- |
| 移动 | WASD / 方向键 |
| 跑步 | Shift |
| 检查附近木箱 | E |
| 重新开始 | R |

素材复制在本工程内，不修改 Studio 原包。`sources.json`记录来源与ZIP指纹；人物来自混元高精度人物的统一投影四动作交付包。本演示使用待机、走路、跑步，采用单个三分之四视角和左右镜像，不提供四方向人物画面。

围栏使用导出的地面深度层，与角色共用Y排序父节点。角色碰撞为半径9px的落脚圆，围栏永久开口为24px。石头和木箱的占地在游戏侧单独校准，灌木只作装饰；水岸素材只提供视觉，池水阻挡矩形由本演示自行定义。与素材包默认关闭的碰撞建议相互独立。

重新组装素材（需要本地保留`sources.json`对应的Studio产物）：

```sh
.local/python/bin/python3 pipeline/build_yard_demo.py
```

从仓库根目录运行真实引擎玩法检查：

```sh
/Applications/Godot.app/Contents/MacOS/Godot --headless --path demo/yard --script smoke.gd
```

检查通过输入驱动真实游戏，覆盖走跑、碰撞、入口通行、完整可达路线、附近交互、重复交互、返回完成和重开。报告输出至仓库`.local/debug/props/yard-smoke.json`。`assets/`与Godot导入缓存不提交版本库，可由组装脚本恢复。
