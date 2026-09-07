# API 设置模态窗口视觉 QA

- 参考图：`C:/Users/Macro/AppData/Local/Temp/codex-clipboard-c856abce-d933-4f40-b55e-2c916a8a1877.png`
- 原生确认框参考：`C:/Users/Macro/AppData/Local/Temp/codex-clipboard-b04af967-ea1c-45c8-8a4d-7dcf51e7fa75.png`
- 实现页面：`http://127.0.0.1:13000/`
- 实现截图：已在 Codex 桌面端内置浏览器中与两张参考图并置检查；因窗口按用户要求明文显示 API Key，为避免额外落盘泄露密钥，截图不持久化。

## 检查结果

- API 设置已脱离主文档流，作为居中浮层显示；主页面使用深色半透明遮罩。
- 模态窗口在窄窗口下保持完整边距、圆角、标题区、内部滚动区和固定底部操作区，没有水平溢出。
- 文本、图片、语音节点层级清楚，现有米白、橙色描边和深色主按钮视觉体系保持一致。
- 点击“立即保存”后页面内显示“设置已保存”，未出现浏览器原生确认或警告窗口。
- 关闭按钮可正常退出浮层，背景页面恢复交互。

final result: passed

## 任务详情命名与图片打包 QA（2026-09-07）

- source visual truth path：`C:/Users/Macro/AppData/Local/Temp/codex-clipboard-30d95827-5e61-4ee5-8b62-8ab5e2dfd551.png`、`C:/Users/Macro/AppData/Local/Temp/codex-clipboard-a26c4d66-d876-43f5-a375-938606315f90.png`
- implementation：`http://127.0.0.1:13000/`；实现截图已由 Codex 内置浏览器捕获并与上述两张参考图共同检查，未额外落盘。
- viewport：桌面 1200 × 900 CSS px、device scale factor 1；另在默认约 457 px 窄视口检查响应式布局。参考图均为 1107 × 868 px，按相同详情页内容区域归一比较。
- state：18 张图片的已完成任务详情；分别检查默认详情、修改名称弹窗、重新渲染命名弹窗。

### Full-view comparison evidence

- 保留参考图中的米白背景、三列图片区、右侧参数与素材卡、绿色重新渲染按钮，不改变原信息层级。
- “修改名称”位于状态标签后的任务标题同一标题区；“保存全部图片”位于生成图片区右上方，均落在用户红框所指区域。
- 重新渲染弹窗居中覆盖详情页，遮罩、圆角、边框和主次按钮继续使用项目现有视觉 token。

### Focused region comparison evidence

- 标题区：任务名仍保持单行省略；新增按钮为紧凑次级按钮，不挤压关闭按钮或状态时间行。
- 图片标题区：ZIP 按钮与生成状态并列；1200 px 桌面三列不变，520 px 以下改为纵向标题布局。
- 命名弹窗：展示自动版本名称、30 字计数、原任务不会覆盖的说明，以及明确的取消/确认操作。

### Required fidelity surfaces

- Fonts and typography：沿用现有微软雅黑/PingFang 与 Georgia 标题栈，字号、粗细与任务详情原层级一致。
- Spacing and layout rhythm：桌面详情网格和卡片间距未漂移；新增控件使用 7–9 px 圆角与现有间距节奏。
- Colors and visual tokens：使用既有 `--ink`、`--muted`、`--red`、`--green`、`--line`，没有引入冲突色。
- Image quality and asset fidelity：生成图片原图、裁切和比例完全未改；没有新增或替换图像资产。
- Copy and content：按钮分别明确为“修改名称”“保存全部图片”“复制并开始重新渲染”，弹窗明确告知原任务与原成片不会覆盖。

### Interaction and technical checks

- 已实际打开两个弹窗并核对预填名称；取消操作正常关闭，未产生任务副作用。
- 后端回归验证改名持久化、连续版本号、新目录复制与 ZIP 内容；浏览器控制台 error/warning 为 0。
- 首轮比较未发现 P0/P1/P2；无需视觉修复迭代。剩余 P3：极窄屏下标题按钮改为两行，这是为避免截断的预期响应式行为。

final result: passed

## 可选声音模式重构 QA（2026-09-07）

- 桌面窄窗口（762 × 706）检查了“无旁白”“克隆音色”“直接使用旁白”三个完整切换状态。
- 无旁白状态不显示上传框，明确说明分镜仍沿用完整文案的语义和叙事规划；进度首项显示“建立视频节奏”。
- 克隆音色状态显示短声音样本上传框；完整旁白状态显示完整录音上传框，三个模块没有互相残留。
- 762 像素宽度下无横向滚动、卡片无截断，标题、说明和输入区域层级清楚。
- 后端 API 合约测试确认 `voice_mode=none` 不带 multipart 音频文件也能成功创建任务。

final result: passed
