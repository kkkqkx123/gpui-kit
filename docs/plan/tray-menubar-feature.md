# 系统托盘/菜单栏图标（Tray）功能设计

日期：2026-10-16 · 状态：设计稿（待评审）

## 结论

- gpui（本仓库 pin 的 `gpui-pre =0.3.9` 快照）与 gpui-kit 当前均无托盘能力，需要在本仓库以自有 crate 补齐；gpui 已具备的四个相邻能力——原生 app menu、锚定父窗口的 popup、Wayland layer-shell、DBus 系统通知——分别提供了 API 形态、能力边界、平台扩展点与事件桥接的模板。
- 仓库组织采用 compograph 模式：本仓库（宿主）已以 submodule（浅克隆，`--depth 1`，指针 `6d84907`）引入 gpui-kit，托盘功能作为宿主自有 crate（`crates/tray`）实现，永不修改 gpui-kit 内任何文件。上游同步 = 更新 submodule 指针 + 对齐 `gpui-pre` 精确 pin，不产生任何合并冲突。
- 托盘后端按平台分治：Linux 用 ksni 0.3.x（纯 zbus 的 StatusNotifierItem 实现，无 GTK 依赖，与 gpui Linux 栈同源）；macOS 自实现 objc2 薄层封装 NSStatusItem（对齐 gpui-pre-macos 已链接的 objc2 0.6 / objc2-app-kit 0.3.2，零新增运行时）；Windows 用 tray-icon（win32 Shell_NotifyIcon）。菜单一律走平台原生菜单（DBusMenu / NSMenu / HMENU），菜单项动作统一映射为 gpui `Action`，经 `App::dispatch_action` 分发——与 gpui 原生 app menu 的桥接方式完全一致。
- 窗口生命周期配套（close-to-tray、托盘点击恢复、纯托盘模式）基于 gpui 现有 `on_should_close` / `Platform::hide` / `App::activate` / `ActivationPolicy::Accessory` 即可实现 v1；gpui 缺少 per-window hide 是已识别缺口，走上游提案路线，v1 以应用级 `hide()` 覆盖。

## 现状

### 仓库结构（compograph 模式解读）

compograph 是理解本方案的样板。它作为独立仓库（kkkqkx123/compograph）以 submodule 挂在 gpui-kit 的 `crates/compograph`，具备四个特征：

1. **独立 workspace**：compograph 根目录自带 `[workspace]`（`crates/foundation|engine|render|app` 四层）、独立 `Cargo.lock`、独立 `rust-toolchain.toml`，与 gpui-kit 的工作区互不包含。gpui-kit 根 `Cargo.toml` 的 `members` 列表没有它，任何 gpui-kit crate 的依赖图里也完全没有 `cg-*` 包（已逐一核对 `crates/*/Cargo.toml`）——submodule 只是"源码放在树里"的组织手段，构建图完全解耦。
2. **同源 gpui pin**：compograph 的 `[workspace.dependencies]` 直接从 crates.io 消费 `gpui-pre` / `gpui-pre-platform`，`=` 精确锁定，与 gpui-kit 的 pin 对齐（其 `docs/plan/compograph-gpui-pre-migration.md` 论证了"两端 gpui 必须同源，否则同一进程出现两套不相连的 gpui 类型"这一决定性约束）。
3. **宿主零改动**：compograph 从不修改 gpui-kit 文件，gpui-kit 上游同步 = 更新 submodule 指针。
4. **文档就地沉淀**：设计与迁移方案写在各仓库自己的 `docs/plan/`。

本仓库已按同一模式接线：`git submodule add --depth 1 https://github.com/kkkqkx123/gpui-kit gpui-kit`，`.gitmodules` 已生成，指针固定在 `6d84907`（kkkqkx123 fork，跟踪 longbridge/gpui-kit 上游，当前分支含 `feat/compograph` 合并）。

### gpui 平台能力盘点（gpui-pre 0.3.9，与本功能相关）

| 能力 | API | 与托盘的关系 |
| --- | --- | --- |
| 原生应用菜单 | `Platform::set_menus(Vec<Menu>)`、`on_app_menu_action`、`on_will_open_app_menu`、`on_validate_app_menu_command`（`platform.rs:488-505`） | API 形态模板：菜单项承载 `Box<dyn Action>`，平台回调统一回 `App` |
| 动作分发 | `App::dispatch_action(&mut self, action: &dyn Action)`（`app.rs:2828`）；`cx.is_action_available` 做可用性校验 | 托盘菜单激活的最终出口 |
| 桥接模板 | `init_app_menus`（`platform/app_menu.rs:331-360`）：平台回调 → `AsyncApp`（`cx.to_async()`）→ `app.update(|cx| cx.dispatch_action(..))` | 托盘事件回主线程的官方姿势 |
| DBus 异步模板 | Linux `system_notifications.rs`：notify-rust（DBus XDG 通知）+ `futures::channel::mpsc` + gpui `Task` 循环收事件 | 托盘 DBus 事件桥接的直接模板 |
| 激活策略 | `App::set_activation_policy(ActivationPolicy)`，`Regular` / `Accessory`（`platform.rs:165-171`，仅 macOS 生效） | 纯托盘应用（无 Dock 图标）模式 |
| 窗口关闭拦截 | `PlatformWindow::on_should_close(Box<dyn FnMut() -> bool>)`（`platform.rs:1271`） | close-to-tray 的入口 |
| 窗口控制 | `PlatformWindow::activate/minimize/zoom/set_title/request_attention`、`on_visibility_change`、`WindowVisibility::{Visible,Hidden}` | 托盘点击恢复、attention |
| 应用级隐藏/激活 | `Platform::hide()`、`Platform::activate(ignoring_other_apps)`（`platform.rs:381-386`） | close-to-tray v1 的隐藏手段 |
| 锚定弹层 | `platform/popup.rs`：`PopupOptions` 锚定**父窗口**的 anchor_rect/gravity/constraint_adjustment，Wayland 经 xdg-popup 定位 | 边界确认：托盘图标处没有父窗口锚点，Wayland 又禁止任意定位普通窗口，应用内弹层无法充当托盘菜单主路径 |
| layer-shell | `platform/layer_shell.rs`（Wayland overlay/top 等层锚定屏幕边缘） | 说明 Linux 平台层有直接对接 Wayland 协议的扩展点，但托盘图标本身由 Shell（SNI 协议）承载，无需 layer-shell |
| 系统通知 | Linux 走 notify-rust（zbus 栈）；macOS 有独立 `system_notifications.rs` | 证明 gpui 事件循环可以稳定承载 DBus 异步回调；zbus 已在依赖树中 |

明确**缺失**的能力：`Platform`/`PlatformWindow` 无任何 tray 相关方法（全源码 `tray` 零匹配）；`Window` 无公开的 per-window `hide()`（`WindowVisibility::Hidden` 只由平台回报——macOS 看 `occlusionState`、Wayland 看 `xdg_toplevel::State::Suspended`，`window.rs` 仅有 `minimize_window()`）。

### gpui-kit 现状

- 伞 crate `gpui-kit`（`crates/kit`）：`application()` 打开平台、`init(cx)` 初始化各层、`open_window` 助手，re-export gpui + base + component + assets。
- 应用内菜单组件（`crates/component/src/menu/`：`popup_menu.rs`、`app_menu_bar.rs`、`context_menu.rs` 等）是 **GPUI 渲染的应用内 UI**，生命周期依附于 gpui 窗口；与"系统托盘"是两个正交领域，托盘菜单走原生路径（见分析）。
- `crates/assets` 的 `IconName`/`IconNamed` 管线把图标解析为 asset 路径，`svg()` 绘制进 gpui 画布——这条管线服务窗口内渲染；托盘图标需要的是位图（RGBA/ARGB），需要单独的栅格化管线（见方案）。
- pin 纪律：gpui-kit 根 `Cargo.toml` 对全部 `gpui-pre-*` 用 `=0.3.9` 精确锁定，`script/check-gpui-pin.ts` 在 CI 校验；compograph 当前 pin `=0.3.8` 已与 gpui-kit 漂移（两者构建图无交集所以无碍，但印证了"漂移随时会发生，必须靠机制而非记忆对齐"）。

## 分析

### 为什么直接改 gpui-kit 是坏选择

gpui-kit 是上游活跃仓库（longbridge/gpui-kit，kkkqkx123 fork 跟随其 main）。托盘功能涉及：新增 crate、改根 `Cargo.toml` members、可能动 `Platform` 层。若直接在 clone 里改：

1. 上游每周级别更新（gpui-pre 快照、组件 API、CI 脚本），本地改动越积越多，rebase 冲突集中爆发在 `Cargo.toml`/`Cargo.lock` 这类高频冲突文件上。
2. compograph 迁移文档已经给出反面教材的变体：gpui-kit 历史上曾同时挂载未被引用的 `zed-gpui` submodule（"纯冗余"），说明树上随意挂东西会留下清理债。
3. 托盘是宿主应用的功能诉求，不是 gpui-kit 组件库的通用诉求；进上游需要走 PR 评审，节奏不归本仓库控制。

### compograph 模式如何解决上游同步

submodule 挂载把"上游代码"与"自有代码"切到两个 git 仓库：

- gpui-kit/ 目录内容 100% 属于上游，本仓库对它的全部操作是 `git submodule update`/指针前移，git 层面不可能产生文本冲突。
- 本仓库的一切自有产物（`crates/tray`、`docs/plan/`、应用 crate、CI）都在宿主仓库，天然没有同步问题。
- gpui-pre 版本升级时的"同步"动作收敛为一个明确的流程（见方案-上游同步流程），用 CI 脚本防漂移，机制对齐而非人工记忆。

### 依赖同源性：一个进程只允许一套 gpui

宿主应用链接 gpui-kit（path 依赖进 submodule），托盘 crate 也要操作 gpui 的 `App`/`Action`/`Entity`。两者必须解析到**同一个** `gpui-pre` 版本，否则 `Entity`/`Context`/`Window` 类型不相连，托盘回调无法触碰应用状态。方案：

- 宿主 workspace 的 `[workspace.dependencies]` 写 `gpui = { package = "gpui-pre", version = "=0.3.9" }`，与 gpui-kit 的 pin 字面一致；
- 托盘 crate 经宿主 workspace 消费同一依赖键；
- CI 脚本校验宿主 pin == gpui-kit workspace pin（M0 任务，仿 `script/check-gpui-pin.ts`）。

与 compograph 的差异说明：compograph 目前与 gpui-kit 构建图无交集，pin 漂移不会编译失败（只在真正嵌入同一应用时爆发）；宿主与 gpui-kit 有交集，pin 漂移会直接在依赖解析/类型层面报错——失败模式显式，配合校验脚本可控。

### Linux 托盘技术选型

| 选项 | 机制 | 与 gpui Linux 栈的关系 | 结论 |
| --- | --- | --- | --- |
| **ksni 0.3.6** | 纯 Rust 实现 StatusNotifierItem + DBusMenu（zbus 5，default-features 关闭；async-io / tokio / async-executor 运行时可选） | 无 GTK；zbus 与 gpui 依赖树中 notify-rust/ashpd/oo7 的 DBus 基建同族；自有线程服务 DBus，事件经 channel 回 gpui | **采用** |
| tray-icon | Linux 后端走 libappindicator | libappindicator 依赖 GTK3 并要求 GTK 主循环；gpui Linux 是 calloop 纯 Rust 循环，引入 GTK 循环与事件优先级冲突，依赖链陡增 | 排除 |
| 自实现 SNI over zbus | 直接实现 org.kde.StatusNotifierItem/DBusMenu | ksni 已是该协议的成熟薄封装，自实现只有维护成本 | 排除 |

环境事实：KDE Plasma 原生支持 SNI；GNOME 需 AppIndicator/StatusNotifier 扩展（Ubuntu/Fedora 主流镜像常见预装）；Wayland 下托盘图标只能由 Shell 经 SNI 承载（X11 embedding 已是历史方案），ksni 在 Wayland/X11 下行为一致。

### macOS 托盘技术选型

| 选项 | 机制 | 结论 |
| --- | --- | --- |
| **自实现 objc2 薄层** | NSStatusBar.systemStatusBar.statusItem(length:-1) + NSMenu + NSStatusItem.button.target/action；约 300-500 行 | **采用**。gpui-pre-macos 0.3.9 已链接 objc2 0.6 / objc2-app-kit 0.3.2 / block2 0.2，自实现零新增运行时、避免双 objc2 版本共存；主线程即 gpui 主线程（ForegroundExecutor 在主线程驱动），回调经 `AsyncApp` 回 gpui，与 `init_app_menus` 同构 |
| tray-icon | objc2 实现的 NSStatusItem 封装，要求主线程 | 备选。需核对其 objc2 版本能否与 0.6 统一；其事件模型（全局 channel）与本方案一致，若自实现受阻可降级到此 |

主线程约束：NSStatusItem/NSMenu 必须在主线程创建与更新。gpui 的 `application().run(|cx| ..)` 闭包及所有 `App` update 都在主线程执行，`Tray` 的全部公开方法设计为在 `&mut App`/`&App` 上下文调用或内部转发主线程，满足约束。

### Windows 托盘技术选型

tray-icon（win32 后端：Shell_NotifyIcon + 内部隐藏窗口/消息线程 + 全局事件 channel，原生 HMENU 弹出菜单）成熟且与 gpui 的 win32 消息循环互不干扰。自实现需重写消息窗口样板（约 600 行 + 图标资源管理），收益低。**采用 tray-icon**，其内部线程模型与 channel 语义在 M3 实现期核对。

### 事件桥接与线程模型

统一事件流（复用 gpui 两个既有模板）：

```text
[平台后端]                          [桥接]                        [gpui 主线程]
ksni 服务线程(异步-io)  ─┐
macOS objc 回调(主线程)  ─┼─→ TrayEvent channel(smol/futures mpsc) ─→ cx.spawn 循环
win32 消息线程           ─┘        TrayEvent::{IconActivated,             cx.update(|cx|
                                    MenuItemActivated{id},                  dispatch_action /
                                    ContextMenuRequested, ...})             状态回调)
```

- `Tray::new(cx)` 保存 `AsyncApp`（`cx.to_async()`，同 `init_app_menus`），并 `cx.spawn` 一个桥接任务，循环收事件后 `cx.update`；
- 菜单项激活优先映射为 `Action`：`cx.dispatch_action(&action)`，可用性沿用 `cx.is_action_available` 校验（与原生 app menu 行为一致）；非 Action 项用 `Box<dyn FnMut(&mut App)>` 回调兜底；
- 反向通道（主线程 → 后端）：`Tray` 句柄 `Clone + Send`，后端各自保证线程安全（ksni `Handle::update` 本身跨线程；macOS 更新方法内部经主线程 executor 转发；Windows tray-icon API 自带线程安全），`set_icon/set_menu/set_tooltip` 从任意 gpui update 中调用即可。

### 菜单统一模型与平台渲染

```rust
pub enum TrayMenuItem {
    Separator,
    Submenu(TrayMenu),
    Item(TrayItem),
}
pub struct TrayItem {
    pub id: MenuItemId,                       // 稳定 id，事件回传用
    pub label: SharedString,
    pub enabled: bool,
    pub checked: Option<bool>,                // Some => checkbox/radio 项
    pub action: Option<Box<dyn Action>>,      // 优先
    pub on_activate: Option<Box<dyn FnMut(&mut App)>>,  // 兜底
    pub accelerator: Option<Keystroke>,       // 仅 macOS NSMenu 渲染
    pub icon: Option<TrayIconRef>,            // 主题图标名/位图，Linux 走 icon-name
}
```

平台渲染路径：Linux 由 ksni 的 `Tray` trait 实现导出为 DBusMenu（Shell 负责绘制，符合 SNI 生态惯例）；macOS 映射为 NSMenu（keyEquivalent 渲染 accelerator）；Windows 交给 tray-icon 的原生菜单。**应用内 PopupMenu（gpui-kit 组件）明确降级为窗口内场景**：Wayland 禁止在托盘坐标处定位普通窗口，popup API 又只支持父窗口锚定，原生菜单是唯一全平台一致的主路径。

### 图标管线

托盘图标需要位图，gpui 的 svg 管线服务窗口内绘制，二者并接：

```rust
pub struct TrayIconData { pub width: u32, pub height: u32, pub rgba: Vec<u8> } // sRGBA
```

- 来源 A：gpui-kit `IconName` 的 SVG 资源 → 托盘 crate 内用 resvg/usvg 栅格化（gpui 依赖树已含 resvg，版本随同一把 lock 统一）；渲染结果缓存，`IconName + size` 为 key。
- 来源 B：应用自备 `TrayIconData`（动态状态图标：如连接状态、未读角标）。
- 平台转换（实现期细节，各后端内聚）：Linux SNI 要求 ARGB32 预乘 alpha（dbus 结构 `iiay`），ksni 的 `icon_pixmap` 字段直接吃；macOS 经 `NSBitmapImageRep` 构造 NSImage，单色图标走 `template = YES`（自动适配深浅色菜单栏）；Windows tray-icon `Icon::from_rgba`。
- 更新节流：内容 hash 变化才提交后端，避免菜单栏高频重绘。

### 窗口生命周期配套功能

| 功能 | v1 实现路径 | 依赖的 gpui API |
| --- | --- | --- |
| close-to-tray | `on_should_close` 返回 false 阻止关闭 → `App::hide()`（应用级隐藏，Windows 上 taskbar 项随之消失，语义正确） | `PlatformWindow::on_should_close`、`Platform::hide` |
| 托盘点击恢复主窗口 | IconActivated 事件 → `window_handle.activate()` + `App::activate(true)` | `PlatformWindow::activate`、`Platform::activate` |
| 纯托盘应用（macOS 无 Dock 图标） | 启动时 `set_activation_policy(Accessory)`；运行时切回 `Regular` 后需自行 `activate`（`app.rs:1964` 注释的已知行为） | `App::set_activation_policy` |
| 菜单状态同步 | 宿主 Entity 状态变更 → Subscription → `tray.set_menu(重建)`（全量重建，构建成本低，避免增量 diff 复杂度） | gpui Subscription |
| attention | v1 仅窗口侧 `request_attention` + 托盘图标切换；Linux SNI `Status: NeedsAttention`/AttentionIcon 列为 M4 可选项（KDE 支持良好，GNOME 支持参差） | `PlatformWindow::request_attention` |
| 退出 | 菜单项挂 `actions!(app, [Quit])`，dispatch 后走正常退出路径 | Action 分发 |

缺口处理：gpui 无 per-window hide，v1 用应用级 `hide()` 覆盖 close-to-tray；同时向上游（gpui-pre 快照发布链）提案 `PlatformWindow::set_visibility(Visible|Hidden)`——`WindowVisibility::Hidden` 状态与 mac occlusion/wayland Suspended 的回报逻辑已存在，只缺主动设置入口，提案成本低。托盘 crate 的后端 trait 边界保证未来可整体迁移。

### 平台行为矩阵与降级

| 平台 | 左键 | 右键 | 菜单 | 已知限制 |
| --- | --- | --- | --- | --- |
| Linux/KDE（SNI） | `Activate` 信号 → 恢复窗口 | `ContextMenu` → 菜单 | DBusMenu，Shell 绘制 | GNOME 需 AppIndicator 扩展 |
| Linux/GNOME+扩展 | 同上（部分版本仅菜单） | 同上 | 同上 | 无扩展时注册失败 → 降级（见下） |
| macOS | 自定义（默认弹菜单，可配置 action） | 弹菜单 | NSMenu | Accessory 策略下无 Dock 图标 |
| Windows | 事件回传（`show_menu_on_left_click` 配置） | 弹菜单 | 原生 HMENU | — |

降级策略：ksni 注册失败（无 SNI watcher，典型为 GNOME 无扩展）→ 记日志 + `Tray::is_available() == false` + 应用正常运行；宿主可在 UI 内提示"安装扩展后重启生效"。托盘不可用绝不阻塞应用启动。

## 方案

### 仓库布局

```text
/workspace（宿主仓库，本仓库）
├── .gitmodules                        # [submodule "gpui-kit"]（已落地，shallow clone）
├── gpui-kit/                          # 上游 submodule @ 6d84907，永不修改其文件
├── docs/plan/
│   └── tray-menubar-feature.md        # 本文档
├── Cargo.toml                         # 宿主 workspace（见下）
├── rust-toolchain.toml                # 宿主自持工具链（gpui-kit 无根级 toolchain 文件）
├── script/check-gpui-lock-pin.sh           # pin 校验（M0）
├── crates/
│   ├── tray/                          # gpui-tray：托盘功能 crate（本方案核心交付）
│   │   └── src/
│   │       ├── lib.rs                 # Tray 句柄、公开 API、feature 开关
│   │       ├── menu.rs                # TrayMenu/TrayItem 模型与 Action 映射
│   │       ├── event.rs               # TrayEvent、桥接任务
│   │       ├── icon.rs                # TrayIconData、resvg 栅格化、缓存
│   │       └── platform/
│   │           ├── linux.rs           # ksni 后端（feature = "linux"）
│   │           ├── macos.rs           # objc2 后端（feature = "macos"）
│   │           ├── windows.rs         # tray-icon 后端（feature = "windows"）
│   │           └── null.rs            # 无后端兜底（unsupported 平台，全部 no-op）
│   └── app/                           # 宿主应用（后续由应用需求展开）
└── examples/
    └── tray_demo/                     # 托盘演示：图标/菜单/close-to-tray/恢复
```

### 宿主 workspace 接线（M0 交付物）

```toml
# /workspace/Cargo.toml
[workspace]
resolver = "2"
members = ["crates/tray", "examples/tray_demo"]

[workspace.package]
edition = "2024"

[workspace.dependencies]
# 与 gpui-kit 根 Cargo.toml 的 pin 字面一致，check-gpui-lock-pin.sh 强制校验
gpui = { package = "gpui-pre", version = "=0.3.9" }
gpui_platform = { package = "gpui-pre-platform", version = "=0.3.9",
    features = ["font-kit", "x11", "wayland", "runtime_shaders"] }
gpui-kit = { path = "gpui-kit/crates/kit" }
gpui-tray = { path = "crates/tray" }
anyhow = "1"
log = "0.4"
smol = "2"

[profile.dev]
debug = "limited"
```

要点：

- gpui-kit/ 自带 `[workspace]` 根，Cargo 自动将其排除在宿主 members 之外（嵌套 workspace 语义），两把 `Cargo.lock` 各自独立，由 `=0.3.9` 字面 pin 保证解析到同一份 gpui 源。宿主是应用仓库，`Cargo.lock` 应提交（当前模板 `.gitignore` 忽略 `**/Cargo.lock`，M0 需追加 `!Cargo.lock` 例外，仿 gpui-kit 的做法）。
- 托盘 crate 直接依赖 `gpui`（workspace 键）与平台后端 crate；对 gpui-kit 的依赖仅限 icon 资源路径约定（`TrayIconRef::Asset(path)`），把耦合面压到最小——资源串约定比 path 依赖 crates/assets 更松，宿主应用按需再引。

### 托盘 crate 公开 API 草案

```rust
// crates/tray/src/lib.rs（示意）
pub struct Tray { /* 后端句柄 + AsyncApp */ }

impl Tray {
    /// 必须在 application().run(|cx| ..) 内（主线程）调用。
    /// 内部：创建后端、cx.to_async() 保存 AsyncApp、cx.spawn 桥接任务。
    pub fn new(cx: &mut App) -> anyhow::Result<Self>;

    pub fn is_available(&self) -> bool;          // 平台不支持/SNI 不可用 => false
    pub fn set_visible(&self, visible: bool);
    pub fn set_icon(&self, icon: Option<TrayIconData>);
    pub fn set_tooltip(&self, tooltip: Option<SharedString>);
    pub fn set_menu(&self, menu: TrayMenu);      // 全量替换
    pub fn set_left_click_action(&self, behavior: LeftClick); // Menu | ActivateWindow
}

// 用法（examples/tray_demo）：
fn main() {
    gpui_kit::application().run(|cx| {
        gpui_kit::init(cx);
        let tray = Tray::new(cx)?;
        tray.set_tooltip(Some("Demo"));
        tray.set_icon(Some(icon_from(IconName::Bell, 32)));
        tray.set_menu(tray_menu(|m| {
            m.action(ShowWindow, "Show Window");
            m.separator();
            m.checked(auto_start, AutoStart, "Launch at Login");
            m.action(Quit, "Quit");
        }));
        // ...open_window 等
    });
}
```

### 上游同步流程（submodule 维护手册）

```bash
# 1. 更新 gpui-kit submodule（浅仓库直接拉新指针）
cd gpui-kit && git fetch --depth 1 origin main && git checkout FETCH_HEAD && cd ..

# 2. 对齐 pin：读 gpui-kit/Cargo.toml 中 gpui-pre 的版本号，同步改宿主 workspace 的 =pin
./script/check-gpui-lock-pin.sh   # 3. 校验两边字面一致（读两份 Cargo.toml 比对）

# 4. 刷新宿主锁并全量编译
cargo update -p gpui-pre && cargo check

# 5. 提交宿主仓库的 submodule 指针变更
git add gpui-kit && git commit -m "chore: bump gpui-kit submodule"
```

submodule 维持 shallow（`--depth 1` 拉取，后续 fetch 继续浅）：宿主对 gpui-kit 只做只读跟踪，浅历史足够；如需考古上游提交，再 `git fetch --unshallow`。

## 实施步骤

- **M0 仓库接线**（submodule 已落地）：宿主 workspace manifest、`rust-toolchain.toml`、`script/check-gpui-lock-pin.sh`、`.gitignore` 的 Cargo.lock 例外、CI 接线（校验脚本 + `cargo check`）。
- **M1 核心 + Linux 后端**：`menu.rs`/`event.rs` 模型与桥接、ksni 后端（含 sRGBA→ARGB32 预乘转换）、`tray_demo`（Linux 可真机验证：KDE 与 GNOME+扩展 × Wayland/X11）、无 watcher 降级路径单测。
- **M2 macOS 后端**：objc2 NSStatusItem/NSMenu 薄层（对齐 objc2 0.6）、template icon、Accessory 策略验证、accelerator 渲染。
- **M3 Windows 后端**：tray-icon 接入、左键行为配置、事件 channel 桥接核对。
- **M4 配套功能**：close-to-tray（`on_should_close` + `hide`）、托盘点击恢复、菜单状态同步（Entity Subscription → set_menu）、tooltip/动态图标节流、（可选）SNI attention；`PlatformWindow::set_visibility` 上游提案起草。

每步的验证口径见下节。

## 风险与开放问题

1. **gpui-pre 快照升级节奏**：宿主与 gpui-kit 必须同 pin。机制已闭环（字面 pin + 校验脚本 + 同步流程），但每次 gpui-kit 指针前移都伴随一次宿主 pin/lock 动作，成本约 10 分钟；compograph 与 gpui-kit 的 0.3.8/0.3.9 漂移是前车之鉴。
2. **GNOME 无 AppIndicator 扩展**：SNI 无 watcher，托盘整体不可用。已设计降级；是否在 UI 内引导安装扩展由宿主应用决定。
3. **DBusMenu 能力差异**：ksni 0.3 的菜单项暴露 label/enabled/icon_name/checked/submenu；per-item 位图图标与快捷键显示（DBusMenu 协议有 shortcut 字段但 ksni API 未暴露）为开放问题，影响面仅视觉细节，必要时可给 ksni 提 PR。
4. **macOS 兼容性**：NSStatusItem 在 gpui 所持 NSApplication run loop 内的兼容性理论上无冲突（仅要求主线程与已初始化的 NSApplication），需 M2 用 tray_demo 实测；Accessory→Regular 运行时切换后的 activate 行为按 gpui 文档注释处理。
5. **Windows 后端线程模型**：tray-icon 内部消息线程与事件 channel 的具体语义在 M3 实现期核对，必要时改为自管理线程包裹。
6. **测试边界**：托盘 UI 无法无头自动化。策略：模型层（menu 构造、事件→Action 映射、图标格式转换）全部单测；平台层走手动矩阵：Ubuntu（GNOME+扩展 / KDE）× Wayland/X11、macOS 14+、Windows 11；CI 仅承担编译与模型单测。

## 验证计划

- **编译/静态**：宿主 `cargo check`（Linux 目标）通过；`check-gpui-lock-pin.sh` 通过；宿主与 gpui-kit 的 lock 中 `gpui-pre` 版本一致（脚本比对）。
- **M1 验收（Linux）**：tray_demo 在 KDE Wayland 下图标出现、DBusMenu 弹出、勾选项状态正确、点击 `Show Window` 恢复窗口、`Quit` 退出；GNOME+扩展同等通过；X11 会话同等通过；无扩展环境应用正常启动且 `is_available()==false`。
- **M2 验收（macOS）**：菜单栏图标出现、template 图标随系统深浅色自适应、菜单动作触发 gpui Action、Accessory 模式下 Dock 无图标且托盘功能完整、close-to-tray 后点击托盘恢复。
- **M3 验收（Windows）**：托盘区图标、右键原生菜单、左键行为符合配置、close-to-tray 后 taskbar 项消失、托盘恢复后回归。
- **回归**：托盘功能关闭（feature off）时宿主应用行为与现状完全一致（null 后端全 no-op）。
