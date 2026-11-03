# Submodule 手动验收指南（Windows / msvc + Win11 SDK）

本文列出五个 submodule 的真机验收入口：每个验证工具的**源文件位置、构建命令、可执行文件路径与逐步操作**。所有验证均为本机手动执行（当前不建 CI，不交叉编译其他平台产物）。

## 0. 一次性构建与脚本预检

先跑统一校验脚本（pin 一致性 + 五个入口的 gpui-kit flavor 编译矩阵）：

```sh
bash script/verify-submodules.sh          # 默认 flavor
bash script/verify-submodules.sh --fast   # 追加 gpui-fast flavor 编译（可选）
```

准出：末行 `verify-submodules: OK`。

按需构建 tray_demo（默认体验 demo，脚本不构建它）：

```sh
cd crates/tray && cargo build -p tray_demo
```

各入口的可执行文件（debug 构建）：

| 入口 | 可执行文件 |
| --- | --- |
| hotkey_probe | `crates/global-hotkey/target/debug/hotkey_probe.exe` |
| autostart CLI | `crates/autostart/target/debug/examples/autostart.exe` |
| tray_lifecycle | `crates/tray/target/debug/tray_lifecycle.exe` |
| tray_demo | `crates/tray/target/debug/tray_demo.exe` |
| image_demo | `crates/gpui-image/target/debug/image_demo.exe` |
| compograph | `crates/compograph/target/debug/compograph.exe` |

## 1. global-hotkey：`hotkey_probe`（无窗口，退出码断言）

源文件：`crates/global-hotkey/examples/hotkey_probe/src/main.rs`（workspace 成员 `examples/hotkey_probe`）。

| 验证项 | 命令 | 期望 |
| --- | --- | --- |
| 可用性探测 | `hotkey_probe --probe` | 打印 `global hotkey available: true`，退出码 0 |
| 注册 + 事件到达 | `hotkey_probe --register`（默认 Ctrl+Alt+G，10s 超时） | 窗口保持无窗口状态；**在任意其他应用获得焦点的情况下**按 Ctrl+Alt+G；打印 `hotkey event received: state=…` 并以 0 退出 |
| 注册 + 超时失败 | `hotkey_probe --register` 后 10s 内不按键 | 打印 `timeout: no hotkey event within …`，退出码 1 |
| 注销释放 | `hotkey_probe --unregister` | `unregister + re-register … succeeded`，退出码 0 |
| 冲突拒绝 | `hotkey_probe --conflict` | `duplicate registration rejected as expected`，退出码 0 |
| 自定义热键 | `hotkey_probe --register --hotkey ctrl+shift+f9 --timeout 15` | 同「注册 + 事件到达」 |

## 2. autostart：`autostart` CLI（verify 子命令闭环）

源文件：`crates/autostart/examples/autostart.rs`（单文件 example，`verify` 子命令为本次新增）。

```sh
autostart.exe status     # 查询当前状态
autostart.exe verify     # enable → 独立断言 → disable → 独立断言，全过退出码 0
```

`verify` 的断言链（每步有打印，失败即退出码 1）：

1. `enable`；
2. 库状态断言 enabled；
3. **独立平台痕迹断言**（不经库）：读注册表 `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run` 下名为 `GPUI Autostart Example` 的值，且内容包含本 exe 路径——可自行用 `reg query` 复核；
4. `disable`；
5. 库状态断言 disabled + 注册表值已消失。

最终确认（可选，人工一次性）：`verify` 通过后重新 `enable`，打开「设置 → 应用 → 启动」应出现 *GPUI Autostart Example*；再执行 `disable` 清理。

## 3. tray：`tray_lifecycle`（三条生命周期路径）+ `tray_demo`（默认体验）

源文件：`crates/tray/examples/tray_lifecycle/src/main.rs`（workspace 成员）。

| 验证项 | 命令 | 操作与期望 |
| --- | --- | --- |
| 默认体验 | `tray_demo.exe` | 托盘出现圆形图标；左键恢复/显示窗口；右键菜单含 Show Window / Launch at Login（勾选态）/ Quit；勾选 Launch at Login 后窗口文本翻转；Quit 后托盘图标消失 |
| close-to-tray | `tray_lifecycle.exe hide-to-tray` | 点击窗口 ✕：**窗口消失但进程不退出**（stdout 先打印 `win::hide: hwnd=… visible true -> false`，再打印 `close intercepted: window hidden to tray`），托盘图标仍在；托盘菜单 Show Window 恢复并前置窗口。若需退出用托盘菜单 Quit（不是任务管理器） |
| close-to-tray 自测 | `tray_lifecycle.exe hide-to-tray --auto-close` | 无人值守路径：程序化发 `WM_CLOSE`，断言可见性 `Some(true)` → 拦截隐藏 → `Some(false)`，约 2 秒后自动退出 |

> **旧二进制鉴别**：修复前版本同样打印 `close intercepted`（文案为 `app hidden to tray`）但不会隐藏窗口（`App::hide()` 在 Windows 是空实现）。当前版本拦截时必先打印 `win::hide: hwnd=… visible true -> false` 诊断行——看不到这一行说明运行的是旧 exe，请结束所有 `tray_lifecycle.exe` 进程后重新构建运行。
| 纯托盘模式 | `tray_lifecycle.exe pure-tray` | 启动后**没有**任何窗口，仅托盘图标；托盘菜单 Show Window 打开窗口；关闭该窗口进程不退出，再次 Show Window 会重新打开一个新窗口 |
| 图标更新 | `tray_lifecycle.exe icon-update` | 托盘图标每秒在蓝/橙间切换，stdout 打印 `tray icon toggled (count N)`；观察 ≥3 次切换 |

每项结束后用任务管理器确认进程退出、托盘图标已消失。

> **平台差异说明（hide-to-tray）**：pin 的 `gpui-pre-windows 0.3.10` 中 `Platform::hide()` 是空实现（`platform.rs` `fn hide(&self) {}`），gpui 也没有 per-window hide setter——仅 macOS 的应用级 `hide()` 可用。因此 demo 在 Windows 上经 raw-window-handle 取 HWND 后直接 `ShowWindow(SW_HIDE/SW_SHOW)` 实现隐藏/恢复；macOS/Linux 仍走 `App::hide()`。长期解法是上游为 `PlatformWindow` 增加 `set_visibility`（见 `docs/plan/tray-menubar-feature.md` M4）。

> **`Tray available` 输出与 Win11 托盘溢出**：修复后 `Tray available:` 在注册成功时应打印 `true`（gpui-tray 此前在 bridge task 首次轮询才标记 `Available`，启动闭包打印时恒为初始态 `Registering` → 误报 `false`；现改为 `NIM_ADD` 成功后同步标记）。**Windows 11 默认把新托盘图标收进任务栏右下角的「显示隐藏的图标」溢出区（`^` 箭头）**，应用无法强制常驻显示：请点开 `^` 找到蓝色圆形图标，可将其拖到任务栏，或在「设置 → 个性化 → 任务栏 → 其他任务栏图标」中设为始终显示。找不到图标时先检查溢出区，再判断是否为真实注册失败。

## 4. gpui-image：`image_demo`（真实文件解码 + ObjectFit）

源文件：`crates/gpui-image/examples/image_demo/src/main.rs`。

| 验证项 | 命令 | 期望 |
| --- | --- | --- |
| 默认演示 | `image_demo.exe` | 左卡显示程序生成的渐变（经 unsharp 滤镜 + PNG 编码），右卡显示 Spinner fallback |
| 真实文件解码 | `image_demo.exe --path C:\path\to\photo.jpg`（PNG/JPEG/WebP 均可） | 标题行显示文件路径与 `fit: cover`，左卡显示该图 |
| 损坏文件 fallback | 造一个非图片文件（如 `echo x > bad.png`）后 `image_demo.exe --path bad.png` | stdout 打印 `decode failed …`；左卡显示 fallback 占位 |
| ObjectFit 四模式 | 分别加 `--fit cover` / `contain` / `fill` / `scale-down` | 用同一张长宽比明显的图对比四种裁剪/留边行为 |

## 5. compograph：`--smoke-frames` 冒烟 + 完整编辑器人工验收

源文件：`crates/compograph/crates/app/compograph/src/main.rs`。

| 验证项 | 命令 | 期望 |
| --- | --- | --- |
| 帧冒烟 | `compograph.exe --smoke-frames 600` | 跑满 600 帧后自动退出，stdout 打印 `smoke: 600 frames in … (avg …/frame)`；记录本次均值作为基线 |
| 交互验收 | `compograph.exe`（不带参数） | 完整编辑器：节点增删、连线、拖拽、缩放/平移；与 smoke 基线对照无明显卡顿 |

## 验收结果记录

每项验收完成后，在对应行标注通过/失败与现象（含 `--smoke-frames` 的帧耗时数字）。发现失败时附上对应可执行文件的 stdout 输出，问题先定位到具体 submodule 仓库再回到宿主仓库提指针/接口问题。

## 重新验证时机

- 任一 submodule 指针更新：先跑 `script/verify-submodules.sh`，再按「改了哪个验哪个」复验对应章节。
- gpui-pre / gpui-fast 快照升级：全部章节复验一遍，并加跑 `--fast` 矩阵。
