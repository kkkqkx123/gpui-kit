# 图像处理与图像显示（gpui-image）设计方案

状态：已明确，待评审。基于 `kkkqkx123/gpui-kit` 当前 `main` 源码静态分析；
所有事实均附 `file:line` 引用。原草案中关于工具链与镜像站的环境描述已经过时，
本文不将其作为依据；工具链统一使用默认 stable（仓库已删除 `rust-toolchain.toml`，与上游一致）。

## 〇、结论速览

- **图像显示：部分支持。** GPUI 提供 `img()` 原语与 `ImageSource`
 （`Resource/Uri/Path/Embedded`、`Render`、`Image`、`Custom`），gpui-kit 仅将其封装进
  两个专用组件 `Avatar`（头像）与 `Attachment`（附件预览），**没有通用 `<Image>` 组件**。
- **图像处理：基本不支持。** 全仓除 `crates/shell` 以 `image 0.25`（仅 `png` 特性）
  做壳层解码外，组件层与基础层无任何解码–编码管线、变换、滤镜、格式转换、缩略图或
  EXIF 能力。`compograph` 子模块是图形合成引擎，但**未纳入主 workspace `members`**，
  不参与图像显示/处理。
- **落地方式：** 在 `crates/` 下新建独立子仓库 `gpui-image`（git submodule，
  对齐既有 4 个子模块先例），分层提供「解码/编码 → 处理 → 渲染桥接 → 可选 Image 组件」，
  并以最小化、可增量的方式与 `gpui-kit` 协同，不影响与上游（longbridge/gpui-kit）的同步。

---

## 一、背景与目标

需求方要求：分析 gpui-kit 当前是否支持图像处理与图像显示，并给出实现相关功能的设计方案；
新功能建议放在 `crates/` 下新建子仓库，以避免影响与上游的同步。

目标：

1. 准确界定现状能力边界与缺口（附事实依据）；
2. 给出不破坏 `gpui-base`、符合 `AGENTS.md` / `docs/ARCHITECTURE.md` 约定的分层架构；
3. 明确新 crate 的组织方式，使上游 `git pull` 的冲突面最小；
4. 给出可执行的 API 草图与分阶段实施路线。

---

## 二、现状分析：gpui-kit 当前能力

### 2.1 图像显示（部分支持）

GPUI 本身已具备图像渲染原语，gpui-kit 在其上做了少量封装：

- **GPUI 原语**（以 `gpui-pre 0.3.10` 为准，`~/.cargo` 缓存源码核对）：
  - `gpui::img(source)` 构造 `Img` 元素（`gpui-pre-0.3.10/src/elements/img.rs:201`）；
  - `gpui::ImageSource` 只有四种形态（`img.rs:42-51`）：
    `Resource(Resource)`、`Render(Arc<RenderImage>)`、`Image(Arc<Image>)`、
    `Custom(…)`。其中 `Resource` 再分 `Uri` / `Path` / `Embedded`
   （`asset_cache.rs:71-78`）；
  - **字节流显示走 `ImageSource::Image`**，其荷载为平台侧可直接构造的
    `platform::Image { format: ImageFormat, bytes: Vec<u8>, id: u64 }`
   （`platform.rs:3316-3323`）；
  - `gpui::ImageFormat` 为 `Png | Jpeg | Webp | Gif | Svg | Bmp | Tiff | Ico | Pnm`，
    自带 `mime_type()` / `extension()` / `from_mime_type()`（`platform.rs:3239+`）；
  - `gpui::ObjectFit` 为 `Fill | Contain | Cover | ScaleDown | None`（`style.rs:29+`）。
- **`Attachment` 组件**：在媒体槽中直接调用 `img()`，用 `ObjectFit::Cover` 铺满，
  并在上传/失败态叠加遮罩与进度环——这是目前唯一一处「通用图片预览」封装。
  见 `crates/component/src/attachment.rs:855-860`。
- **`Avatar` 组件**：基础层提供无样式的 `AvatarImage::new(src)` 槽位
 （`crates/base/src/avatar.rs:69-77`），gpui-kit 侧封装见
  `crates/component/src/avatar/avatar.rs:5,130`（render 中 `AvatarImage::new(src)`）。
  无图时退化为姓名首字母占位。
- **编辑器内联图片**：文本引擎支持把 `ImageSource` 作为内联节点渲染，含 SVG。
  见 `crates/base/src/text/node.rs:10`（引入 `Image, ImageFormat, ImageSource`）
  及 `:878-887`、`2668-2683` 的图片源解析。
- **SVG 图标**：`Icon` 组件基于 resvg 渲染 SVG 资源，
  依赖见 `crates/component/Cargo.toml:249`（`resvg = "0.45.1"`）。

> 缺口：以上均为「特定场景封装」或「GPUI 原语直用」，**不存在可被任意业务复用的通用
> `Image` 组件**（`crates/component/src/lib.rs` 与 `crates/kit/src/lib.rs` 均无 `image`
> 相关导出，grep 验证无结果）。要在按钮、卡片、列表里显示一张图，目前只能手工拼
> `img()`，或借用 `Attachment` / `Avatar` 这两个语义不通用（附件/头像）的组件。

### 2.2 图像处理（基本不支持）

- **`image` crate 仅出现在壳层**：`crates/shell/Cargo.toml:91` 声明
  `image = { version = "0.25", default-features = false, features = ["png"] }`，
  仅 png、仅用于 JavaScript 扩展壳（截图/剪贴板解码），**未向组件层暴露任何 API**。
- **组件/基础层无任何处理原语**：全仓（除 shell）未依赖 `image` / `tiny-skia` /
  `kamadak-exif` 等，无缩放、裁剪、旋转、滤镜、格式转换、缩略图、EXIF 朝向矫正等实现。
- **`compograph` 子模块未启用**：`compograph`（图形合成引擎）在 `.gitmodules` 中定义，
  但**不在**主 `Cargo.toml` 的 workspace `members` 内；它是「被 vendored 但未编译进
  主 workspace」的独立仓库，不能直接作为图像处理底座使用。

---

## 三、能力差距矩阵

| 能力 | 现状 | 缺口 / 风险 |
| --- | --- | --- |
| 显示：通用 `Image` 组件 | 仅 `Avatar` / `Attachment` 专用封装 | 无通用组件，复用需手写 `img()` |
| 显示：占位/加载/失败态 | `Attachment` 有上传/失败遮罩 | 通用图片缺少 fallback、骨架屏、error 态 |
| 显示：`object-fit` / 宽高比 | `AttachmentMedia` 用 `Cover` | 无通用 `Contain` / `Fill` / aspect-ratio 封装 |
| 显示：懒加载 / 远程 URL | `ImageSource::Resource::Uri` 可用 | 无加载生命周期管理与缓存 |
| 解码：常见格式（png/jpg/webp/gif/bmp/tiff） | shell 仅 png | 组件层无解码能力，webp/avif/gif 缺失 |
| 处理：缩放/裁剪/旋转/翻转 | 无 | 完全缺失 |
| 处理：滤镜（模糊/锐化/亮度/对比/灰度） | 无 | 完全缺失 |
| 处理：格式转换 / 缩略图 | 无 | 完全缺失 |
| 处理：EXIF 朝向 / 元数据 | 无 | 完全缺失 |
| 合成/特效（GPU） | `compograph` 未接入 | 需桥接，且不在主 workspace |

---

## 四、设计目标与原则

1. **不破坏上游同步**（首要）：新功能以独立子仓库形态存在于 `crates/`，
   对原仓库的改动保持「最小、增量化、低冲突」。
2. **遵守 `AGENTS.md` 架构约束**：默认不修改 `gpui-base`（`AGENTS.md` 架构重构约束节）；
   组件行为与视觉落在 `crates/component` 或应用层/新 crate。
3. **元素构造沿用现有风格**：`Image` 等元素走 `new()` + 链式 setter（对齐
   `AttachmentMedia::src`、`Avatar::src/placeholder` 的命名习惯），`Sizable`/`Styled`/
   `RenderOnce` 与 `when` / `when_some` 链式装配；跨 seam 的状态/能力/上下文类型
   才适用「字段私有 + builder + 方法读取，`with_`/`is_`/`has_` 命名」
  （`AGENTS.md` 公共数据类型节、`docs/ARCHITECTURE.md` 同名节）。
4. **向后兼容**：不改动既有导入（如 `use gpui_kit::component::button::Button;`），
   新能力以「新增模块/新增 re-export」方式提供。
5. **后端可替换**：处理层先以 CPU 侧 `image` crate 自包含实现，GPU 合成/特效作为
   可选后端（未来桥接 `compograph`），不把新 crate 与 `compograph` 强耦合。
6. **与 GPUI 渲染解耦**：渲染桥接只产出 `gpui::ImageSource`
  （字节流走 `ImageSource::Image(Arc<platform::Image>)`，远端/文件/内嵌走
   `ImageSource::Resource`），从而复用 GPUI 既有纹理上传与 `img()` 显示路径。
7. **职责单一**：新 crate 只负责「解码 → 处理 → 显示」，不引入网络拉取依赖；
   「取字节」是调用方的职责（规避 `reqwest` 等重依赖）。

---

## 五、总体架构

新建 crate **`gpui-image`**，定位为「图像处理 + 图像显示组件」的独立库。
它是独立 git 仓库，经 `.gitmodules` 挂在 `crates/gpui-image`，自带 `[workspace]`、
独立 `Cargo.lock`（无自带工具链 pin，使用默认 stable，与主仓库一致），
**不进入**主 workspace `members`（与 `tray` / `autostart` / `compograph` 一致的先例）。

```text
crates/gpui-image/                # 独立 git 子仓库（submodule）
├── Cargo.toml                    # facade（gpui-image）+ workspace（members: crates/*, examples/*）
├── （无 rust-toolchain.toml，使用默认 stable）
├── script/check-gpui-kit-pin.py  # pin 对齐校验（仿 tray）
├── crates/
│   ├── image-core/               # 解码/编码 + 处理原语（纯逻辑，无 GPUI 依赖）
│   ├── image-gpui/               # GPUI 桥接：ImageSource 构造、缓存（flavor: gpui-kit/gpui-fast）
│   └── image-component/          # 通用 Image 组件（Sizable/Styled，视情况依赖 gpui-component）
└── examples/
    └── image_demo/               # 演示（依赖已发布 gpui-kit，如 tray_demo）
```

- **`image-core`（无 GPUI 依赖）**
  - 解码/编码：基于 `image 0.25`，默认启用 `png/jpeg/gif/webp/bmp`，
    `tiff`/`avif` 走可选 feature（`all-formats` 一键全开）。
  - 处理：`resize`（多种采样算法）、`crop`（越界钳制）、`rotate`/`flip`、
    `filter`（blur/unsharp/brightness/contrast/huerotate/grayscale/invert）、
    `thumbnail`（等比，最长边约束）、`convert`/`encode`（目标格式序列化）。
  - SVG 为直通形态：core 不做光栅化解码（留给 resvg/GPUI），但桥接层支持
    `Svg` 字节以 `ImageFormat::Svg` 原样送显。
  - `auto_orient`（EXIF 朝向）：Phase 1 为直通占位（行为=原图，文档明示），
    Phase 2 引入 EXIF 解析后再做真实矫正，避免首期引入额外依赖。
- **`image-gpui`（依赖 GPUI）**
  - `still_image(bytes, format) -> ImageSource`：包出
    `ImageSource::Image(Arc<Image { format, bytes, id }>)`，`id` 由进程内
    `AtomicU64` 计数器分配，保证唯一。
  - `EncodedImage`（core 产物）→ `ImageSource` 的 `From` 转换，含 core 格式到
    GPUI `ImageFormat` 的映射（`Png/Jpeg/Webp/Gif/Bmp/Tiff/Svg`）。
  - `ImageCache`：按 key 记忆 `ImageSource`（派生图/远端图解码结果复用），
    纯内存 Map，不碰网络、不碰 `App`。
  - flavor 与 `tray` 一致：`gpui-kit`（`gpui-pre`）/ `gpui-fast` 二选一，
    `compile_error!` 拒绝双开；pin 精确锁定已发布 gpui-kit 同代快照。
- **`image-component`（依赖 gpui-component，可选）**
  - 通用 `Image` + `ImageFallback`，对齐 shadcn 语义：
    `src` / `object_fit` / `placeholder` / `aspect_ratio` / `Sizable`，
    无图时渲染 fallback slot（首字母/图标由调用方提供）。
  - 此层仅在需要「组件级复用」时构建；若只想要处理能力，业务可直接用
    `image-core` + `image-gpui`。

> 为何不直接把 `compograph` 当底座：`compograph` 是 GPU 合成/布局引擎，体量重且
> 当前**未纳入主 workspace**。把它作为图像处理唯一底座会强制把整个图形引擎拉进
> 主构建，违背「最小侵入」。结论：基础处理用 `image` crate 自包含；
> `compograph` 仅作为**未来可选 GPU 加速后端**（feature-gated）的桥接对象。

---

## 六、核心 API 草图（示意，以脚手架代码为准）

```rust
// image-core：纯处理，无 GPUI 依赖
pub struct ImageBuffer { /* 持有 DynamicImage，字段私有 */ }
impl ImageBuffer {
    pub fn decode(bytes: &[u8]) -> Result<Self, Error>;   // 自动探测格式
    pub fn dimensions(&self) -> (u32, u32);
    pub fn resize(mut self, width: u32, height: u32, filter: ResizeFilter) -> Self;
    pub fn crop(mut self, x: u32, y: u32, width: u32, height: u32) -> Self; // 越界钳制
    pub fn rotate(self, rotation: Rotation) -> Self;       // R90/R180/R270
    pub fn flip(self, flip: Flip) -> Self;                // Horizontal/Vertical
    pub fn filter(self, filter: Filter) -> Self;          // Blur/Sharpen/Brightness/...
    pub fn thumbnail(self, max_edge: u32) -> Self;        // 等比，最长边 <= max_edge
    pub fn auto_orient(self) -> Self;                     // Phase 1 直通，Phase 2 接 EXIF
    pub fn encode(&self, format: EncodedFormat) -> Result<Vec<u8>, Error>;
    pub fn to_encoded(self, format: EncodedFormat) -> Result<EncodedImage, Error>;
}

// image-gpui：桥接（修正点：GPUI 没有 ImageSource::Bytes，字节流走 ImageSource::Image）
pub fn still_image(bytes: Vec<u8>, format: gpui::ImageFormat) -> gpui::ImageSource;
impl From<EncodedImage> for gpui::ImageSource { /* format 映射 + 唯一 id */ }

pub struct ImageCache { /* 私有 map + builder */ }
impl ImageCache {
    pub fn new() -> Self;
    pub fn get(&self, key: &str) -> Option<gpui::ImageSource>;
    pub fn get_or_insert(&mut self, key: &str, make: impl FnOnce() -> gpui::ImageSource) -> gpui::ImageSource;
    pub fn len(&self) -> usize;
    pub fn is_empty(&self) -> bool;
    pub fn clear(&mut self);
}

// image-component：通用显示组件（元素风格对齐 Avatar/Attachment：src/placeholder  plain setter）
pub struct Image { /* 私有字段 + Sizable/Styled/RenderOnce */ }
impl Image {
    pub fn new() -> Self;
    pub fn src(self, src: impl Into<ImageSource>) -> Self;
    pub fn object_fit(self, fit: ObjectFit) -> Self;
    pub fn placeholder(self, el: impl IntoElement) -> Self;
    pub fn aspect_ratio(self, ratio: f32) -> Self;
    // readers: has_source(), object_fit(), aspect_ratio()
}
pub struct ImageFallback { /* ParentElement children 槽，对齐 AvatarFallback */ }
```

跨 seam 的公开类型（`EncodedImage` 产物、`ImageCache` 等）字段私有、`new()` + 链式
setter、方法读取；布尔态用 `is_*`，其余用 `with_*` 前缀（`AGENTS.md` 公共数据类型节）。
元素 builder（`Image::src/object_fit/placeholder`）沿用既有组件命名习惯。

---

## 七、与上游同步的隔离策略

既有 4 个子模块 `compograph` / `autostart` / `tray` / `global-hotkey` 均为**独立 git
仓库**，经 `.gitmodules` 引入，且**均未进入主 workspace `members`**。本方案沿用同一先例：

1. **推荐：git submodule + 不进主 `members`**（与现有子模块完全一致）
   - 在 `.gitmodules` 新增 `crates/gpui-image` 条目；其源码是独立仓库，历史与原仓库解耦。
   - 主仓库的根 `Cargo.toml` / `Cargo.lock` **零改动**，与上游逐字一致；
     业务/示例通过已发布 `gpui-kit` + `gpui-image` 双依赖集成（`tray_demo` 模式）。
   - 冲突面：上游 `git pull` 时仅 submodule 指针前移，`git` 层面不可能产生文本冲突。
2. **pin 对齐机制（仿 tray）**
   - 子仓库精确 pin 已发布 gpui-kit 同代的 `gpui-pre` / `gpui-fast`
    （当前已发布 `gpui-kit 0.8.0` → `gpui-pre =0.3.9`、`gpui-fast 0.1.10`）；
   - `script/check-gpui-kit-pin.py` 在子仓库 CI 中比对 crates.io 最新已发布 gpui-kit
     的 manifest，主仓库侧不参与校验。
   - 主仓库当前处于 `0.8.1` / `gpui-pre =0.3.10` 开发周期，与子仓库 pin 存在预期内的
     代差；下次 gpui-kit 发版后按校验脚本提示抬升子仓库 pin 即可。
3. **不做：直接修改 `gpui-base` / 主 workspace `members` / 主 `Cargo.lock`**
   ——三者都会扩大与上游的 diff，本方案排除。

> 关键约束再强调：无论哪种粒度，都**不修改 `gpui-base`**；组件行为落在 `gpui-image`
>（或其 `image-component` 层）/应用层。

---

## 八、分阶段实施路线

- **Phase 0 — 脚手架（本次落地）**：`crates/gpui-image` 独立 workspace + 三层 crate +
  `image_demo` + `check-gpui-kit-pin.py` + `.gitmodules` 条目；主仓库零改动
  （除本文档与 `.gitmodules` 一行）。
- **Phase 1 — 解码 + 显示桥接**：`image-core::decode/encode` + `image-gpui::still_image`
  + `ImageCache`，使任意字节/文件可被 `img()` 显示；单测（格式探测、字节往返、缓存命中）。
- **Phase 2 — 处理原语**：`resize/crop/rotate/flip/filter/thumbnail/convert` 落实单测；
  `auto_orient` 接入 EXIF（新增小依赖，走 feature 门控，保持 core 默认依赖面不变）。
- **Phase 3 — 通用 `Image` 组件**：`Image` / `ImageFallback` 落实 `Sizable` / `Styled` /
  `RenderOnce` + builder 单测；在 `crates/story`（主仓库示例应用）中以「直接依赖
  已发布 `gpui-image`」的方式演示（不改 umbrella 导出，避免上游冲突）。
- **Phase 4 — 上游同步验证**：在 fork 上做一次模拟 `git pull` 上游，确认
  `Cargo.toml` / `Cargo.lock` 零冲突、`git submodule update` 正常；补 `examples/` 演示。
- **（可选）Phase 5 — GPU 后端**：feature-gated 桥接 `compograph` 做特效/合成，默认关闭。

`Image` 组件是否纳入 `gpui-kit` umbrella 的公开 API（`crates/kit/src/lib.rs` 的
`pub use`），待 Phase 3 完成后再议——纳入意味着每次发版都要履行 `AGENTS.md` 的
`## Public API` 披露义务，且会永久扩大上游同步的合并面，默认不纳入。

---

## 九、事实依据与引用清单

| 结论 | 依据 |
| --- | --- |
| `img()` 原语 | `gpui-pre-0.3.10/src/elements/img.rs:201`（经本地 cargo 缓存核对） |
| `ImageSource` 仅 `Resource/Render/Image/Custom` 四态 | `img.rs:42-51` |
| `Resource` 为 `Uri/Path/Embedded`；字节流走 `ImageSource::Image` | `asset_cache.rs:71-78`；`platform.rs:3316-3323` |
| `ImageFormat` 九格式 + `mime_type/extension/from_mime_type` | `platform.rs:3239+` |
| `ObjectFit` 五档 | `style.rs:29+` |
| `img()` + `ObjectFit::Cover` 图片预览 | `crates/component/src/attachment.rs:855-860` |
| `Avatar` 经 `AvatarImage` 显示图片（base 类型） | `crates/base/src/avatar.rs:69-77`；`crates/component/src/avatar/avatar.rs:5,130` |
| 编辑器内联图片 / 图片源解析 | `crates/base/src/text/node.rs:10`、`:878-887`、`:2668-2683` |
| SVG 渲染依赖 resvg | `crates/component/Cargo.toml:249` |
| **无通用 `Image` 组件** | `crates/component/src/lib.rs`、`crates/kit/src/lib.rs` 无 `image` 相关导出（grep 验证） |
| **`image` crate 仅 shell 且仅 png** | `crates/shell/Cargo.toml:91` |
| 处理/变换/格式转换/EXIF 缺失 | 全仓（除 shell）无 `image`/`exif` 等依赖（grep 验证） |
| `compograph` 未纳入主 workspace | 主 `Cargo.toml` 的 `members` 无 `compograph`；`.gitmodules` 有其条目 |
| 默认不改 `gpui-base` | `AGENTS.md` 架构重构约束节 |
| 跨 seam 类型用 builder、无 pub 字段 | `AGENTS.md` 公共数据类型节；`docs/ARCHITECTURE.md` 同名节 |
| 子模块先例（独立 workspace、不进 members、pin 校验） | `crates/tray`（`Cargo.toml` + `script/check-gpui-kit-pin.py`）、`docs/plan/tray-menubar-feature.md` |

---

## 十、开放问题与待拍板项

1. **crate 命名**：`gpui-image`（facade）+ `gpui-image-core` / `gpui-image-gpui` /
   `gpui-image-component`。`gpui-image-component` 是否重命名为 `gpui-component-image`
   以贴近组件命名空间？倾向保持 `gpui-image-*` 前缀，单仓库内统一。
2. **`Image` 组件是否进入 umbrella**：默认不进入（见第八节末）；若未来进入，
   需在 `crates/kit/src/lib.rs` 增量化 re-export 并随发版披露 `## Public API`。
3. **`compograph` 定位**：本期不将其作为底座；是否/何时用 feature-gated 桥接其 GPU
   能力，待基础能力落地后再议。
4. **默认启用的图像格式**：`png/jpeg/gif/webp/bmp` 默认开，`tiff`/`avif` 走可选
   feature（体积/编译时间考量；`avif` 编解码重，默认关闭）。
5. **远程图加载与缓存策略**：不内置 `reqwest` 拉取；「取字节」归调用方，
   `gpui-image` 只负责「解码 → 处理 → 显示」+ 内存 `ImageCache`。
6. **`auto_orient` 的 EXIF 依赖选型**：Phase 2 时在 `kamadak-exif` 与手写 JPEG APP1
   最小解析之间二选一，默认倾向小体积的 feature-gated 可选依赖。
7. **子仓库远端建仓**：`https://github.com/kkkqkx123/gpui-image` 建仓后，
   执行 `git submodule add <url> crates/gpui-image` 将本次脚手架转为正式 submodule
   指针（本次先以 `.gitmodules` 条目 + 独立 workspace 结构占位，主构建零影响）。

---

## 附：本次落地清单（Phase 0）

- [x] 本设计文档（`docs/plan/image-processing-display.md`）。
- [x] `crates/gpui-image/` 独立 workspace 脚手架：
  `Cargo.toml`（facade + `members: crates/*, examples/*`）
  （与主仓库同频道）、`README.md` / `README_zh.md`、`LICENSE`、
  `script/check-gpui-kit-pin.py`。
- [x] `crates/image-core`（`gpui-image-core`）：decode/resize/crop/rotate/flip/
  filter/thumbnail/encode + 单测（纯逻辑，无 GPUI 依赖）。
- [x] `crates/image-gpui`（`gpui-image-gpui`）：`still_image` /
  `EncodedImage → ImageSource` / `ImageCache` + flavor 门控 + 单测。
- [x] `crates/image-component`（`gpui-image-component`）：`Image` /
  `ImageFallback`（`Sizable` / `Styled` / `RenderOnce`）+ builder 单测。
- [x] `examples/image_demo`：端到端演示（解码 → 处理 → `Image` 显示）。
- [x] `.gitmodules` 新增 `crates/gpui-image` 条目。
- [x] 主仓库零侵入确认：根 `Cargo.toml` / `Cargo.lock` / `crates/kit` 无改动；
  嵌套 `[workspace]` 使新目录自动排除在主 workspace 之外。
