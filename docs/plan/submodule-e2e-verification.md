# Submodule 卫星 crate 端到端验证方案

## 结论

- 五个 submodule（`compograph`、`tray`、`autostart`、`global-hotkey`、`gpui-image`）都是独立仓库、独立 workspace，与宿主工作区构建图解耦，唯一共享的契约是 **gpui pin**（`gpui-pre =0.3.10` / `gpui-fast 0.1.12`）。端到端验证因此分三层：**crate 自身测试** → **示例程序在真机三平台跑通**（submodule 的功能都是 OS 集成，单元测试覆盖不到真正的端到端路径）→ **与宿主的 pin/锁文件一致性校验**。
- 目前缺口最大的两处：`compograph` 内嵌测试为 0，`global-hotkey` 内嵌测试为 0；tray / autostart / gpui-image 已有单元测试但均无自动化端到端路径。OS 集成类功能（托盘、自启动、全局热键）的真实验证只能靠人工在真机执行示例，方案将其固化为**可勾选的人工验收清单**，并把可自动化的部分（编译、pin 校验、无头可测逻辑）脚本化。
- 建议新增 `script/verify-submodules.sh`：本机一条命令跑「编译全矩阵 + pin 一致性」；真机交互验收按平台各跑一轮。当前不建 CI，所有验证均为本机手动执行。

## 验证分层

| 层 | 内容 | 可自动化 | 覆盖的 submodule |
| --- | --- | --- | --- |
| L1 单元测试 | 各 crate 内嵌 `#[test]` / `static_assertions` | 是 | 全部 |
| L2 编译矩阵 | 两个 GPUI flavor × 三平台 × 默认/全部 feature | 是 | 全部 |
| L3 示例端到端 | 运行 `examples/*`，在真实 OS 上人工验收 | 部分（启动可自动，断言人工） | tray / autostart / global-hotkey / gpui-image |
| L4 pin 一致性 | submodule gpui pin 与宿主 `Cargo.lock` 对齐；`zed-rev` 与 submodule git rev 对齐 | 是 | 全部 |

## 各 submodule 方案

### 1. compograph（`crates/compograph`，独立 workspace，7 个 crate）

现状：内嵌测试 0，有 `docs/plan`、`scripts/publish.sh`，自身 `docs/dev/` 已沉淀 gpui-pre 依赖设计。

- **L1 补测试**：四层中优先补 `cg-graph` / `cg-geometry`（纯算法层，无 gpui 依赖，单测即可全覆盖：图操作不变量、几何边界值）；`cg-layout` / `cg-render` 补基于固定输入快照的确定性测试。
- **L2**：`cargo build --workspace` + `cargo clippy --workspace -- --deny warnings`（其 lints 已配置 deny 集）；另用 gpui-fast flavor 编译一轮 `compograph` app crate，确认两个后端 API 都走通。
- **L3**：`crates/app/compograph` 作为图编辑器示例，人工验收：节点增删、连线、拖拽、缩放/平移、渲染帧率（可用 `gpui-fps`）。渲染正确性可用 `crates/kit` 现成的 snapshot 思路（`rendering` test 需要 Metal/WGPU），先不引入，v1 以人工验收为主。
- **L4**：其 `[workspace.dependencies]` 的 `gpui-pre*` pin 与宿主根 `Cargo.toml` 逐项比对——纳入 `script/check-submodule-pins.py` 同一脚本扩展。

### 2. tray（`crates/tray`，7 个内嵌测试，example：`tray_demo`）

- **L1**：保留现有菜单模型 / 事件映射测试；补 Linux ksni 菜单序列化、Windows HMENU 构建的纯逻辑测试（不触 OS）。
- **L2**：`cargo build --features gpui-kit` 与 `--no-default-features --features gpui-fast` 各一轮；其余平台在本机拿到硬件后手动各编译一轮。
- **L3（真机人工验收，核心）**：
  - Windows：托盘图标显示、左键/右键菜单弹出、菜单项 Action 到达 GPUI 主线程、图标更新、退出后图标消失；
  - macOS：NSStatusItem 显示、菜单交互、`ActivationPolicy::Accessory` 纯托盘模式；
  - Linux：在 GNOME/KDE（有 StatusNotifierItem 宿主）下验证 ksni 路径，并验证无托盘宿主时失败路径干净（不挂起）。
  - close-to-tray / 点击恢复 / 纯托盘模式三条窗口生命周期路径各验一次。
- **L3 可自动化部分**：`cargo run -p tray_demo` 启动 5 秒不崩溃即认为初始化路径可用（仅本机桌面会话跑）。

### 3. autostart（`crates/autostart`，17 个内嵌测试，example：`autostart.rs`）

- **L1**：已覆盖注册/注销逻辑（tempfile 沙箱）；补 Windows 注册表写入路径的模拟断言（现有用 tempfile 模拟，保留）。
- **L2**：同 tray 的双 flavor 编译。
- **L3（真机人工验收）**：
  - macOS：`SMAppService` 注册后「系统设置 → 登录项」出现该 app、注销后消失、错误状态（无签名 bundle）可读出；
  - Windows：注册后 Run 键存在且指向当前 exe，注销后清空；
  - Linux：XDG autostart `.desktop` 文件落盘内容正确。
  - Linux 路径自动化程度最高：直接对 `$XDG_CONFIG_HOME/autostart` 断言，本机 headless Linux 即可跑。

### 4. global-hotkey（`crates/global-hotkey`，内嵌测试 0，example：`hotkey_demo`）

现状最薄弱，优先补齐：

- **L1 补测试**：`hotkey.rs` 的快捷键解析（字符串 → 热键描述）与 `event.rs` 事件桥接映射是纯逻辑，先补这两处；`x11_available()` 探测逻辑用假 X11 环境（`xvfb-run`）测真实探测。
- **L2**：双 flavor 编译；Linux 下确认 `x11rb 0.13.1` 与 `global-hotkey` 0.9 内锁版本一致（`cargo tree -d`，只允许一份）。
- **L3（真机人工验收）**：注册热键 → 应用失焦状态下按键 → 事件到达 GPUI 主线程回调；再验证注销后不再触发、冲突注册的错误路径。X11 下可在 `xvfb` + `xdotool` 里做半自动触发（keydown 注入 + 断言 flume 通道收到事件），Wayland 无 X11 server 时必须走 `is_available() == false` 降级路径。
- **L3 自动化**：`xvfb-run cargo run -p hotkey_demo` + `xdotool key` 注入脚本，作为 Linux 端到端冒烟。

### 5. gpui-image（`crates/gpui-image`，7 个内嵌测试，workspace 含 `image-core` + `examples/image_demo`）

- **L1**：`image-core` 的解码/处理是纯逻辑，补对固定测试图（PNG/JPEG/WebP 各一，多色域）的解码结果断言；bridge 层现有 compile_error! 防呆测试保留。
- **L2**：默认（gpui-kit + component）与 `--no-default-features --features gpui-fast,component` 各编译一轮；其自带 `script/check-gpui-kit-pin.py` 已做 pin 校验，确认覆盖 `gpui-component =0.8.1` pin。
- **L3（真机人工验收）**：`cargo run -p image_demo`（其 example 为独立成员）：PNG/JPEG 正常显示、损坏文件走 `ImageFallback`、缩放/`ObjectFit` 表现、WASM 目标 `cargo build --target wasm32-unknown-unknown -p image_demo` 编译通过（解码在 wasm 的可用性是关键差异点）。

## 横切：pin 一致性（L4，全自动）

现有工具链已覆盖大半，补两点：

1. `script/check-submodule-pins.py`：已校验 autostart / global-hotkey 的 git rev 与 `zed-rev`；扩展为**全部五个 submodule**，并新增「各 submodule Cargo.toml 中的 `gpui-pre*` / `gpui-fast` 版本 == 宿主根 `Cargo.toml` pin」断言（compograph 比对 workspace.dependencies，其余比对 dependencies）。
2. `script/check-gpui-lock-pin.sh`：确认宿主 `Cargo.lock` 解析出的 gpui 版本与 pin 一致（防 caret 漂移）。
3. gpui-image 自带 `script/check-gpui-kit-pin.py`，保留在其仓库内执行，宿主侧不重复。

## 落地步骤

1. 新增 `script/verify-submodules.sh`：L2 编译矩阵（本机平台、双 flavor）+ L4 pin 校验，一条命令跑完。
2. compograph / global-hotkey 各补一轮 L1 测试（优先纯逻辑层）。
3. tray / autostart / global-hotkey / gpui-image 的真机验收项整理为各仓库 `docs/` 下的 checklist（按上表），发版前逐项勾选。
4. Linux 冒烟（autostart XDG 断言、global-hotkey xvfb+xdotool）作为本机可重复执行的脚本保留，不接 CI。
