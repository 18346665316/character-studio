# 陈伯：现有人物成果展示

此工程将 Studio 已有成果整理为可运行样例：同一角色的待机、行走、跑步与跳跃在同一固定视角下播放。无需图片服务、Python 或重新生成素材。

用 Godot 4 导入 `project.godot` 后运行，或在仓库根目录执行：

```bash
godot --headless --path examples/characters/chenbo --editor --import
godot --path examples/characters/chenbo
```

本次验证版本为 Godot 4.6.2。界面可重新播放所有动作或水平镜像。动作结束策略、移动和碰撞由游戏决定；本工程展示素材播放，没有人物移动控制器。

## 这组成果说明什么

- 原画、模型准备阶段的预览和动作图集来自现有角色，制作本展示没有新发起生成、重建或动作下载。
- 角色 `character-50e87c3235`，原显示名为「陈伯 · 宋村老农」；名称不是历史准确性证明。
- 图集来自 `20261103-152200-80af08c8` 的游戏精简版。四种动作共用绑定、渲染视角、96 像素标准人物高度及配色；场景按 2 倍显示。
- 来源动作集另含一个呈坐姿的交谈候选。此处只选取四个基础移动动作，没有修改来源动作集或重新认定交谈用途。
- 逐帧时序和脚底锚点来自原始导出。GIF 每秒记录 12 个引擎画面，播放器仍按各动作实际时长运行。GIF 为展示循环，跳跃素材本身仍是单次播放。
- `asset.json` 保留 `manual_review: pending` 等来源状态。通过引擎结构检查不代表完成美术、动作语义或循环接缝验收。

## 文件

`character_assets/character-50e87c3235/` 为 Studio 导出快照；PNG 图集与来源文件逐字节一致。`reference.png` 是原画缩至 512×512 的展示副本；`model-preview.png` 是模型准备阶段的已有预览。

`showcase.gd` 是展示消费者，仅实例化导出人物并调用动作 API；原始人物预览入口也保留在 `character_assets/character-50e87c3235/preview.tscn`。`provenance.json` 记录来源标识与文件指纹。

接入自己的项目时，复制整个 `character_assets/` 目录。使用方法与限制见 [INTEGRATION.md](character_assets/character-50e87c3235/INTEGRATION.md)。不要用示例的 `project.godot` 覆盖自己的工程。

## 复现展示媒体

在仓库根目录执行，`godot` 替换为本机 Godot 4 可执行文件。录制需要图形渲染环境，不能使用 `--headless`：

```bash
godot --headless --path examples/characters/chenbo --editor --import
godot --path examples/characters/chenbo --fixed-fps 12 --resolution 1280x620 \
  --script res://capture.gd -- "$PWD/.local/readme-showcase/frames"
.local/python/bin/python3 examples/characters/chenbo/build_media.py \
  --frames .local/readme-showcase/frames --output docs/assets/showcase
```

媒体整理脚本需要 Pillow。它把 120 张真实引擎画面编码为 10 秒 GIF，并用已有图片制作静态流程对照。GIF 编码使用统一的 256 色调色板，PNG 原图和游戏纹理保持原样；展示中没有新增绘制或修饰角色。

引擎接入检查：

```bash
godot --headless --path examples/characters/chenbo \
  --script "$PWD/pipeline/tests/action_set_integration.gd" \
  -- res://character_assets/character-50e87c3235/character.tscn
```

本次输出 `ACTION_SET_INTEGRATION_PASS`，覆盖动作列表、循环、逐帧时长、镜像锚点与单次动作结束行为。
