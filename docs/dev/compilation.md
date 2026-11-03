# 编译指南

本文说明 GPUI Kit 工作区的编译方式、常用命令与构建注意事项。面向日常开发与排障，发布流程见 `CONTRIBUTING.md`。

## 前置条件

- Rust 工具链（edition 2024，需较新的 stable）
- 平台依赖：
  - **Windows**：无需额外系统库（MSVC 工具链）
  - **macOS**：Xcode Command Line Tools（Metal）
  - **Linux**：X11/Wayland 开发库、GTK（`crates/story` 在 Linux 上依赖 gtk 0.18），可参考 `script/install-linux.sh`
- 可选工具：`typos`（拼写检查）、`cargo-machete`（未使用依赖检查）

## 工作区结构

- workspace 默认成员（`default-members`）是 `crates/story`，所以在仓库根目录直接 `cargo run` / `cargo build` 操作的是 Story Gallery，而不是整个工作区。
- 核心发布 crate：`crates/kit`（`gpui-kit`，伞形 crate）、`crates/base`（`gpui-base`）、`crates/component`（`gpui-component`）、`crates/component-macros`、`crates/assets`、`crates/shell`（`gpui-shell`）、`crates/webview`、`crates/fps`。
- 示例：`examples/` 下每个目录都是独立成员，用 `cargo run -p <包名> --example <名字>` 或 `cargo run --example <名字>`（story 成员内的 example）运行。
- 依赖解析使用 resolver = "2"。

## GPUI 快照与锁定

GPUI 来自 `gpui-pre-*` 快照（Zed 的发布快照），workspace 中以**精确版本**锁定：

- `gpui = { package = "gpui-pre", version = "=0.3.10" }`
- `gpui_platform`（gpui-pre-platform）、`gpui_web`、`gpui_macros`、`sum-tree`、`reqwest_client`、`reqwest` 均为 `=0.3.10` 系列
- `gpui-fast = 0.1.12`（可选后端，通过 `gpui-fast` feature 选择）

注意事项：

- 快照之间可能有 API 变化，必须整组一起升级，并同步刷新 `Cargo.lock`；`script/check-gpui-pin.ts` 会在 CI 校验 pin 是否精确。
- `[workspace.metadata.gpui-kit] zed-rev` 记录快照对应的 Zed 提交，是子模块卫星 crate（`crates/autostart`、`crates/global-hotkey` 等）git rev 的唯一事实来源，由 `script/check-submodule-pins.py` 校验。

## 常用命令

```bash
# 运行 Story Gallery（workspace 默认成员）
cargo run

# 编译整个工作区
cargo build --workspace

# 运行单个示例（示例均为独立成员）
cargo run -p hello-world          # examples/hello_world
cargo run -p editor               # examples/editor

# Lint 与格式
cargo clippy --workspace -- --deny warnings
cargo fmt --check

# 拼写检查、未使用依赖
typos
cargo machete
```

### 测试

按用户配置，日常开发无需主动运行测试；以下命令供需要时使用。

```bash
cargo test --all
cargo test -p gpui-component
cargo test -p gpui-component --doc
```

特殊测试目标（`crates/kit`）：

- `ui`：需要 `test-support` + `component` feature
- `rendering`：需要 Metal（macOS）或 WGPU（Linux），显式 `cargo test -p gpui-kit --test rendering`
- `native_shutdown`：使用原生事件循环与隐藏窗口，需要桌面会话，显式运行

## Feature 体系

GPUI Kit 的核心 feature（定义在 `crates/kit`，其余 crate 转发）：

| Feature | 作用 |
| --- | --- |
| `gpui-fast`（默认关） | 切换到 GPUI Fast 后端（核心、平台、Web 全链路） |
| `component`（默认开） | 启用样式组件库 `gpui_kit::component` |
| `assets`（默认开） | 默认图标集 `gpui_kit::assets` |
| `test-support` | GPUI 测试 harness、native-platform 渲染、Kit UI 测试助手 |
| `profiler` / `inspector` | 帧事件插桩 / UI 检查器（性能构建下默认关闭） |
| `speech` | 语音输入（麦克风采集 + 系统识别器） |
| `tree-sitter` / `syntect` | 语法高亮；tree-sitter 按语言逐个启用（`tree-sitter-rust` 等），两者同开时 tree-sitter 优先 |
| `decimal` | 十进制数字输入支持 |

Story Gallery 的 `tree-sitter` feature 映射到 `gpui-kit/tree-sitter-languages`（一次性启用全部语言语法），是其默认 feature。

## 编译加速（workspace profile 配置）

根 `Cargo.toml` 已做调优，一般无需改动：

- `profile.dev`：`debug = "limited"`、`split-debuginfo = "unpacked"`；保留 256 个 codegen units（调低会让增量重建整个单元，实测单行改动重建 CPU 增加约 50%）。
- `profile.dev.package`：对渲染/文本热路径（`resvg`、`rustybuzz`、`taffy`、`gpui-pre(-platform)`、`tree-sitter`、`ropey`、`quickjs-jit-*` 等）设置 `opt-level = 3`。注意 `quickjs-jit-sys` 通过 `cc` 编译 QuickJS 本体，读取的是包自身的 opt-level。
- `profile.release`：`strip = "symbols"`（不增加编译时间，减少约四分之一发布二进制体积）。
- proc-macro crate 故意不优化（只在编译器内运行）。

## WebAssembly（story-web）

Web 版 Story Gallery 在 `crates/story-web`，构建走 Makefile：

```bash
cd crates/story-web
make install       # 添加 wasm32-unknown-unknown target、wasm-bindgen-cli、www 前端依赖（bun）
make build-wasm    # release 模式构建 WASM（scripts/build-wasm.sh --release）
make build-wasm-dev
make build-web     # 构建前端（bun run build）
```

要点：

- 目标为 `wasm32-unknown-unknown`；WASM 下无 tree-sitter 语法，Editor story 用 `syntect` 高亮（原生用 tree-sitter）。
- WASM 下需要 `getrandom` 的 `js` feature（已在 story 的 wasm 依赖中处理）；`errno` 使用 stub。
- WASM 依赖 `gpui-pre-web` / `gpui-fast-web`（非 iOS/Android 的原生目标依赖 `gpui-pre-platform`）。

## 常见问题排查

- **快照 API 不匹配编译错误**：确认 `Cargo.lock` 中 `gpui-pre*` 系列版本一致且等于根 Cargo.toml 的 pin；运行 `script/check-gpui-pin.ts`。
- **Linux 缺系统库**：先跑 `script/install-linux.sh`。
- **`cargo run` 跑错了目标**：根目录默认成员是 `crates/story`；操作其他 crate 请带 `-p`。
- **UI 测试编译失败**：缺 `--features test-support`（部分还需 `component`、`assets`）。
