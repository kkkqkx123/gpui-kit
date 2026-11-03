# Submodule 真机验证的 Example/Bin 补充与分阶段验证方案

前置阅读：`docs/plan/submodule-e2e-verification.md`（验证分层 L1–L4 与各平台验收清单）。本文回答两件事：**每个 submodule 需要补充/改造哪些 example 或 bin 才能支撑真机验证**，以及**验证分几个阶段推进、每阶段的准入/准出标准**。

## 一、现状与缺口

| Submodule | 现有入口 | 已覆盖 | 真机验证缺口 |
| --- | --- | --- | --- |
| tray | `examples/tray_demo`（单 bin，GUI） | 图标、原生菜单、左键动作 | close-to-tray / 点击恢复 / 纯托盘三条生命周期路径、图标更新、无宿主失败路径——目前只能靠改代码重编译验证 |
| autostart | `examples/autostart`（windowless CLI：status/enable/disable） | 注册/注销/状态查询，参数化、可脚本 | 缺「enable 后断言平台痕迹存在」的自校验闭环；登录后是否真的自启动无法用 CLI 验证 |
| global-hotkey | `examples/hotkey_demo`（GUI，注册 Ctrl+Alt+G） | 注册 + 失焦触发 | 未注册/注销/冲突注册路径；脚本化触发（xdotool）无退出码可断言；不可用平台的降级路径 |
| gpui-image | `examples/image_demo`（GUI，程序生成 PNG + fallback） | core 管线、bridge、`ImageFallback` | 真实文件解码路径（磁盘加载/损坏文件）、`ObjectFit` 实拍、WASM 目标 |
| compograph | `crates/app/compograph`（完整图编辑器） | 全功能，适合人工交互验收 | 无自动退出/无帧计数，不能做「启动 N 帧不崩」的冒烟断言 |

原则：**一个行为路径 = 一个可独立调用的入口**。不往单个 GUI demo 里塞全部路径，而是用 CLI 参数/子命令拆分，保证每条验收项都有明确的启动命令；同时所有 GUI demo 保持「默认运行即展示核心路径」的约定，验收清单里的命令因此可以逐行照抄执行。

## 二、各 submodule 的 Example/Bin 补充方案

### 1. tray：拆分生命周期演示为独立 bin

- 保留 `tray_demo` 为默认体验（图标 + 菜单 + 左键动作 + tooltip + `ToggleAutoStart`）。
- 新增 `examples/tray_lifecycle.rs`（独立 bin，复用 `tray_demo` workspace 成员）：
  - CLI 子命令对应三条路径：`hide-to-tray`（`on_should_close` 拦截 → `hide()`，托盘 `ShowWindow` 恢复）、`pure-tray`（`ActivationPolicy::Accessory`，无主窗口）、`icon-update`（运行后定时切换两个生成的图标，验证 `TrayIcon::update`）。
  - 每个子命令在窗口里显示当前阶段文本，人工按 checklist 打勾；Linux 另需一次「无 StatusNotifierItem 宿主环境」（如 `env -u` 会话或最小 WM）下启动，断言进程报错退出而非挂起。
- 验收命令形态：`cargo run --bin tray_lifecycle -- hide-to-tray` 等，逐条对应 checklist。

### 2. autostart：CLI 增加 verify 子命令 + 登录冒烟 bin

- 现有 CLI 补 `verify` 子命令：`enable` 后直接断言平台痕迹（Windows 读 Run 键值、macOS 调 `SMAppService` 状态查询、Linux 读 `$XDG_CONFIG_HOME/autostart/*.desktop` 内容并校验 Exec 指向），`disable` 后断言痕迹消失；断言失败返回非零退出码。macOS/Windows 本机一条命令完成注册→校验→注销闭环。
- 新增 `examples/autostart_probe.rs`（可选，仅 macOS/Windows 真机用）：注册自启动后打印「本次登录期望启动」提示并退出，供人工注销重登一次做最终确认。Linux 无需此 bin（`.desktop` 断言足够）。

### 3. global-hotkey：补脚本化验证 bin + 冲突路径

- 保留 `hotkey_demo` 为默认体验。
- 新增 `examples/hotkey_probe.rs`（windowless CLI/半自动）：
  - `--register` 模式：注册指定热键，阻塞等待事件，**收到事件即打印并以 0 退出**，超时（如 10s）非零退出——这是 `xvfb-run + xdotool` 自动化断言的落点，也是 macOS/Windows 人工验收的「事件确实到达」客观凭证；
  - `--unregister` 与 `--conflict` 模式：注册同一热键两次、注销后再触发（不应收到事件），分别断言错误返回与静默；
  - `--probe` 模式：只打印 `is_available()` / `x11_available()` 并退出，覆盖 Wayland（无 X11）降级路径。
- 该 bin 不建窗口，纯事件通道（flume）验证，三平台手动验收共用。

### 4. gpui-image：CLI 化真实文件路径 + WASM 冒烟

- `image_demo` 增加 `--path <file>` 参数：从磁盘加载指定图片走 core 解码管线显示；传入损坏/非图片文件时显示 `ImageFallback`（覆盖真实解码失败路径，区别于现有的「无 source fallback」）；`--fit <cover|contain|fill>` 参数切换 `ObjectFit` 供截图比对。
- 不新增独立 bin；WASM 验证为编译冒烟：`cargo build -p image_demo --target wasm32-unknown-unknown`（验证解码器在 wasm 目标的可用性），加 `trunk serve`（或 `www` 前端既有流程）人工确认浏览器渲染一张图与一张 fallback。
- `image-core` 补一组固定测试图（PNG/JPEG/WebP 各一 + 各一损坏版）作为 fixtures，供 L1 单测与 `--path` 验收共用。

### 5. compograph：加帧冒烟入口 + 纯逻辑层测试

- app crate 增加 `--smoke-frames N` 启动参数：打开固定布局的图，跑 N 帧后调用 `cx.quit()` 并打印帧耗时统计（可接 `gpui-fps`）。这把「启动 N 帧不崩、帧时间不劣化」变成可自动/半自动断言，也是三平台编译矩阵之外的真实渲染冒烟。
- L1 补测试落在 `cg-graph` / `cg-geometry`（无 gpui 依赖，纯算法）与 `cg-layout` 的确定性快照；`cg-render` / app 交互继续以 L3 人工验收为主（节点增删、连线、拖拽、缩放平移）。

## 三、分阶段验证方案

当前不建 CI：所有验证均为**本机手动执行**的脚本/代码验证与编译运行后的手动端到端验证。三个阶段按「机器可断言 → 脚本半自动 → 纯人工」递进，每阶段给出执行命令与准出标准。

### 阶段 0：代码验证（单元测试 + pin 一致性 + 编译矩阵）

目标：submodule 指针更新或代码改动后，一条命令完成机器可断言的部分。

- [ ] `script/verify-submodules.sh`：双 GPUI flavor 编译矩阵（本机平台）+ 五个 submodule 的 gpui pin 与宿主一致性断言（扩展 `check-submodule-pins.py`）。
- [ ] L1 测试补齐：compograph（cg-graph/cg-geometry 起步）、global-hotkey（热键解析/事件映射）、gpui-image（fixtures 解码断言）。
- [ ] 本机脚本冒烟：autostart `verify` 子命令、hotkey `--probe`/`--conflict`、gpui-image wasm 编译（`cargo build --target wasm32-unknown-unknown`）。
- 准出：`script/verify-submodules.sh` 一条命令全绿（本机执行，不依赖 CI）。

### 阶段 1：脚本化事件验证（半自动）

目标：OS 集成路径中最「事件链路」的部分由脚本断言，不再依赖纯肉眼。

- [ ] 补齐阶段 0 依赖的新入口：`hotkey_probe`（`--register/--unregister/--conflict`）、tray `tray_lifecycle`、compograph `--smoke-frames`。
- [ ] Linux：`xvfb-run` + `xdotool` 脚本驱动 `hotkey_probe --register`，断言退出码；tray 在无托盘宿主环境断言干净失败（本机手动执行）。
- [ ] compograph `--smoke-frames 600` 本机跑一遍，记录帧耗时基线。
- 准出：hotkey 与 tray 的失败路径全部有脚本断言；compograph 有可对比的帧基线。

### 阶段 2：手动端到端验收（三平台编译运行）

目标：真实编译出二进制后在桌面会话按 checklist 逐项执行，覆盖 UI/系统集成观感与平台行为。入口全部来自阶段 0/1 的 example/bin。

- [ ] tray：`tray_demo` + `tray_lifecycle` 三个子命令，Windows/macOS/Linux 各一轮（Linux 含 GNOME/KDE 两种宿主）。
- [ ] autostart：CLI `verify` 闭环 + macOS/Windows 登录重登一次（`autostart_probe`），Linux 仅 verify。
- [ ] global-hotkey：`hotkey_demo` 手动失焦触发一轮（含 macOS 权限、Windows 前台策略观感）。
- [ ] gpui-image：`image_demo --path` 正常图 + 损坏图 + `--fit` 三种模式截图留档；浏览器 WASM 一轮。
- [ ] compograph：完整编辑器人工交互验收（增删/连线/拖拽/缩放），对照阶段 1 帧基线确认无回归。
- 准出：checklist 全勾，截图/现象记录沉淀到各 submodule 仓库 `docs/`。

### 复验规则（gpui snapshot 升级或 submodule 指针更新时）

不设固定门禁流程，按影响面手动执行：

- [ ] 阶段 0 全绿（本机跑 `verify-submodules.sh`）。
- [ ] 阶段 1 冒烟在本机跑一遍（帧基线对比）。
- [ ] 阶段 2 中受影响面（改了哪个 submodule 就验哪个；snapshot 升级则全量）按 checklist 复验。
- [ ] `python3 script/check-submodule-pins.py` 与 `script/check-gpui-lock-pin.sh` 通过。

## 四、执行顺序建议

1. 先做阶段 0 的两个纯脚本项（verify-submodules.sh、pin 校验扩展）——成本最低、立刻防回归。
2. 按「缺口最大优先」补 example/bin：`hotkey_probe`（global-hotkey 目前零测试零断言）→ autostart `verify` → compograph `--smoke-frames` → `tray_lifecycle` → gpui-image `--path`。
3. 阶段 1、2 依赖这些入口，按入口落地顺序推进；复验规则在每次 snapshot 升级时手动执行。
