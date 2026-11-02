# 等距资产接入验证

独立 Godot 4 项目，用于验证 Studio 素材的 2:1 地格、占地中心锚点和 Y 排序，不属于 Studio 的地图或游戏生产功能。

项目根目录执行：

```
.local/python/bin/python3 pipeline/build_isometric_demo.py
/Applications/Godot.app/Contents/MacOS/Godot --headless --editor --path demo/isometric --import
/Applications/Godot.app/Contents/MacOS/Godot --path demo/isometric
```

默认复用已生成草地纹理；石头、木箱为明确标注的程序几何样本，不代表 AI 生成效果。接入真实等距素材：

```
.local/python/bin/python3 pipeline/build_isometric_demo.py --rock <等距石头包ID> --crate <等距木箱包ID>
```

不调用生图服务，不把已有斜俯视物件改标签冒充等距素材。原包保持不变。生成资源位于被 Git 忽略的 assets/，需本机保留源素材包。

方向键移动青色测试标记，F 切换占地建议，R 重置。青色标记仅为排序测试图形。这里由游戏主动启用导出的碰撞建议，生产包仍默认关闭。投影角度、落地锚点和实际美术遮挡仍需人工验收。

## 建筑验证

双击 `play-building.command` 打开独立建筑场景，保留原有石头/箱子验证入口。
复用本机建筑候选 `20261102-153942-af274361 / 20261102-153942-a99c4e06`，
以及 yard 中已有的96px人物素材，不调用生图，不发布建筑包，不修改原候选。
需要本机已有 `assets/textures/ground_*.png` 和 `demo/yard/assets/character_assets/`。

方向键移动，F 显示估计占地，G 切换128×64地格，E 测试入口事件，R 复位；
1/2/3 跳转到前、后、侧后观察点（用于观察排序，不代表人物能走进该位置）。
入口事件只累计触发次数，不包含室内场景。占地与入口为场景测试估计，未标记为用户正式标定。

```
.local/python/bin/python3 pipeline/build_building_demo.py
/Applications/Godot.app/Contents/MacOS/Godot --headless --editor --path demo/isometric --import
/Applications/Godot.app/Contents/MacOS/Godot --headless --path demo/isometric --script building_check.gd
# 图形模式还会检查实际渲染排序，并把截图和报告写入指定的已有目录。
/Applications/Godot.app/Contents/MacOS/Godot --path demo/isometric --script building_check.gd -- /absolute/output/directory
```

测试沿用本项目的原生SceneTree输入/物理帧与渲染检查，不依赖未安装的godot-e2e插件。
8项交互/物理检查和2项前后渲染检查通过，不表示建筑所有方向遮挡通过。
已观察到侧后方整栋单图排序错误，以及建筑侧边与地格方向不完全一致。
人物是已有three-quarter素材，仅用于比例与移动检查，不代表已完成等距角色适配。
详见 `docs/building-game-validation-2026-11-02.md`。
