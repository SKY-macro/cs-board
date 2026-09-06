# 研究发现

- 来源仓库可通过 Git 正常读取，Skill 包位于 `skill-package/story-to-handdrawn-video/SKILL.md`。
- 权威风格数据位于 `references/handdrawn-style-library.json`，确有 20 种风格；每项包含中文名、摘要、完整 prompt_blocks、色彩提示、排除项和示例图路径。
- 20 张示例图位于 `references/style-examples/01-...png` 至 `20-...png`，另有一张 contact sheet。
- 来源 Skill 明确说明示例图作为风格证据/比较图，不应当作具体场景或人物参考。用户要求“参考配图使用该项目中的配图”，因此界面卡片将直接使用这 20 张原图。
- 风格库中 repo-adapted 条目附带 MIT 许可，许可文本需要随集成资产保留。
- 当前 cs-board 已有 12 种风格卡片，静态预览位于 `web/public/styles`；后端风格配方位于 `webapp/server.py::STYLE_PRESETS`。
- 集成策略：保留现有 12 种风格，再追加来源 Skill 的 20 种，避免破坏历史任务；后端使用来源库完整配方，前端使用来源中文名、摘要与原始示例图。
