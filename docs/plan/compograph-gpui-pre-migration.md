# compograph 切换到 gpui-pre：分析与修改方案

日期：2026-10-09 · 状态：已实施（验证结果见文末）

## 结论

**应当切换。** compograph 的 gpui 依赖从自维护的 `zed-gpui`（kkkqkx123 fork 的 `lean`
快照 submodule + path 依赖）改为 longbridge 在 crates.io 发布的 `gpui-pre` /
`gpui-pre-platform` 快照，版本精确锁定 `=0.3.8`，与 gpui-kit 工作区当前 pin 完全一致。
gpui-kit 根工作区与 compograph 各自的 `zed-gpui` submodule 引用同时删除。

## 现状

- gpui-kit 通过 `[workspace.dependencies]` 消费 crates.io 上的 `gpui-pre-*` 快照
  （`gpui` 即 `gpui-pre`，`gpui_platform` 即 `gpui-pre-platform`），全部使用
  `=x.y.z` 精确 pin，并由 `script/check-gpui-pin.ts` 在 CI 强制校验。
- compograph（已作为 submodule 加入 `feat/zed-gpui` 分支）自带独立工作区，其
  `crates/vendor/zed-gpui` 挂载 zed-gpui `lean` 分支快照，以 path 依赖消费其中的
  `gpui`（包版本 0.2.2）、`gpui_platform`、`gpui_macros`、`gpui_shared_string`、
  `gpui_util`，并关闭了默认 features。
- gpui-kit 根工作区还额外挂了一个未被任何 manifest 引用的 `crates/zed-gpui`
  submodule（该分支引入，纯冗余）。

## 分析

### 集成可行性是决定性因素

compograph 加入本仓库的目的是为 gpui-kit 提供图可视化功能。gpui-kit 应用链接的
是 `gpui-pre` 提供的 `gpui` 库；若 compograph 依赖另一个来源的 gpui，同一进程里
会出现两套同名但不相连的 `gpui` 类型（`Entity`、`Context`、`Window`、`Render` 等），
gpui-kit 侧与 compograph 侧的状态、窗口、元素无法互相传递，图视图无法被 gpui-kit
应用嵌入使用。两条依赖链必须同源，这是切换的根本理由，其余论据都是次要收益。

### 选项对比

保留 zed-gpui 的理由及其不足：

- *可控裁剪（lean 精简依赖）*：compograph 实际使用的 gpui API 面很窄——实体与
  订阅（`Entity`/`Context`/`Subscription`/`EventEmitter`）、异步（`Task`/`AsyncApp`/
  `spawn`）、绘制（`div`/`canvas`/`PathBuilder`/`paint_path`/`paint_quad`）、焦点与
  鼠标键盘事件、路径选择对话框、`TestAppContext` 测试。裁剪带来的体积与编译收益
  有限，且由 gpui-pre 的快照发布流程统一承担即可。
- *可回灌上游修改*：compograph 至今没有需要修改 gpui 源码的需求；即使出现，也
  应先在 zed-gpui fork 内解决，与依赖来源是否为 submodule 无关。
- *版本节奏自选*：与 gpui-kit 绑定版本节奏恰恰是集成的前提——两端版本不一致时
  无法在同一个应用里共存。

切换 gpui-pre 的收益：

- 与 gpui-kit 同一条 API 基线、同一个 `Cargo.lock` 解析入口、同一套 CI pin 校验，
  消灭"两端 gpui 漂移后无法集成"的隐患。
- 依赖全部来自 crates.io（经镜像解析），去掉 zed-gpui path 依赖连带的三个 git
  依赖（proptest、scap、wasm_thread 的 zed fork rev），受限网络下不再需要 GitHub
  代理才能完成依赖解析。
- 删除两处 submodule（gpui-kit 根 1 个、compograph 内 1 个）及其 vendored 的
  27 个上游 crate 树，仓库结构回到"自建 crate 一眼可见"。
- 顺带修复一个真实缺陷：compograph 此前对 `gpui_platform` 未启用任何后端
  feature（其默认 feature 集为空），在 Linux 桌面会话下 `guess_compositor`
  返回 Wayland/X11 时会触发 `unreachable!` panic；本次按 gpui-kit 的取值启用
  `x11`、`wayland`（以及 macOS 的 `font-kit`、`runtime_shaders`），应用才能真正
  打开窗口。

### API 兼容性核验（切换前静态比对）

对 zed-gpui vendored 源码与 `gpui-pre` 0.3.8（`zed@279fe07` 快照）做逐文件 diff：

- compograph 使用的文件里，`path_builder`、`elements/canvas.rs`、`view`、`style`、
  `color`、`subscription`、`global` 等完全一致。
- 有差异的 `app.rs`、`window.rs`、`platform.rs`、`test_context.rs` 中，compograph
  实际调用的签名（`open_window`、`activate`、`prompt_for_paths`、`Entity::update`、
  `focus`、`paint_path`、`paint_quad`、`TestAppContext` 等）没有任何变更；差异
  均为新增能力（挂起监控、窗口模式切换、`is_test`、泄漏检测 cfg 改写）或
  文档/条件编译调整。
- `gpui_platform::application()` 在 gpui-pre-platform 中同样存在并返回
  `gpui::Application`。
- `test-support` feature 在 gpui-pre 中仍然存在；其不再隐式开启 `leak-detection`，
  compograph 的测试未使用泄漏检测 API，无影响。

结论：compograph 现有代码无需源码级改写，只需替换 manifest 依赖与后端 feature。

## 修改方案

1. compograph 工作区 manifest：`gpui` 改为 `package = "gpui-pre"`、`gpui_platform`
   改为 `package = "gpui-pre-platform"`，两者均精确 pin `=0.3.8`（与 gpui-kit 一致）；
   `gpui_platform` 启用 `font-kit`、`x11`、`wayland`、`runtime_shaders`；删除成员
   crate 未使用的 `gpui_macros`、`gpui_shared_string`、`gpui_util` 三条 workspace
   依赖；删除 `crates/vendor/zed-gpui` 的 workspace exclude 与相应注释。
2. compograph submodule 清理：删除 `.gitmodules` 中 `crates/vendor/zed-gpui` 条目
   （文件因此清空并删除），移除 `crates/vendor/zed-gpui` 目录。
3. gpui-kit 根清理：删除 `.gitmodules` 中 `crates/zed-gpui` 条目，移除
   `crates/zed-gpui` 目录（根工作区没有任何 manifest 引用它）。
4. 文档同步：compograph 的 `AGENTS.md`、`docs/dev/`、`docs/architecture/` 中所有
   "上游以 submodule 挂载、path 依赖消费"的表述改为 "gpui 来自 crates.io 的
   gpui-pre 快照"；新增 `docs/dev/gpui-pre-dependency.md` 作为当前依赖说明。
   `docs/dev/zed-gpui-submodule.md` 保留为历史参考（文首注明已改用 gpui-pre），
   供将来若换回 submodule 方案时查阅。
5. 保持 compograph 为独立工作区：不并入 gpui-kit 的 `[workspace] members`。
   独立工作区保住它自己的 rust-toolchain 钉扎、更严格的 clippy 规则集与独立
   发布形态；两端通过相同版本 pin 保证同一 API 基线。并入工作区（共享 target
   目录、单一 pin、CI 直接覆盖）作为后续可选事项，等 compograph 真正被 gpui-kit
   crate 以 path 依赖消费时再决策。

## 验证

- compograph 内执行 `cargo clippy --workspace --all-targets --all-features`
  （一次性覆盖库、应用、测试与 bench 的编译和 lint，等同该仓库 AGENTS 的
  标准检查命令），作为切换后的编译验证。
- compograph 的 `Cargo.lock` 由该命令重新解析生成。
- gpui-kit 根工作区未改动任何 manifest，仅以 `cargo metadata --no-deps` 确认
  工作区解析不受 submodule 移除影响。
- `script/check-gpui-pin.ts` 现只校验根 manifest；compograph 的 pin 需要与
  gpui-kit 同步 bump，后续可把该脚本扩展到 compograph manifest（本机无 bun，
  未改动脚本）。

## 验证结果

- compograph：`cargo clippy --workspace --all-targets --all-features` 通过，
  0 警告 0 错误；7 个自建 crate（6 个 `cg-*` 与 `compograph` 应用）与
  gpui-pre 0.3.8 及其平台后端全部编译通过，依赖全量来自 crates.io 镜像。
- 切换过程未修改任何 Rust 源码，静态 diff 预判（无签名破坏）成立。
- gpui-kit 根：`cargo metadata --no-deps` 解析正常。
- 两端 pin 一致：均为 `gpui-pre` / `gpui-pre-platform` `=0.3.8`。
- compograph `Cargo.lock` 已不含任何 git 依赖源与 vendor path 条目。

## 风险与后续

- **pin 漂移**：`bump-gpui.ts` 只更新 gpui-kit 根 manifest；升级 gpui-pre 时需
  手动同步 compograph 的 pin（或按上文扩展 pin 校验脚本）。
- **工作区合并**：若后续 compograph crate 被 gpui-kit crate 直接依赖，需要把它
  并入根工作区或以 path 依赖引入；届时再统一 lint、toolchain 与 CI。
- **zed-gpui fork**：本次删除的是引用而非 fork 仓库本身，fork 可继续作为实验场，
  不再被本仓库依赖。
