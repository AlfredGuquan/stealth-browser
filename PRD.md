# Stealth Browser — PRD

## 背景与目标

AI agent 在操作网页时面临三重阻力：登录态丢失需要反复人工介入、反爬系统识别自动化特征后拦截、多个工具拼凑的碎片化体验。Stealth Browser 的目标是让浏览器操作对 AI agent 来说和 CLI 命令一样可靠——即使在有反爬检测的站点上。

V1 定位：反爬先行，架构留口。专注解决反爬站点的自动化问题，接口和架构为未来扩展成完整浏览器自动化工具留空间。

目标站点：小红书（creator.xiaohongshu.com）、Twitter/X（x.com）。

技术栈：Python + Patchright + pycookiecheat + human-cursor + OpenCV。uv 管理依赖。

---

### F1: 反检测浏览器引擎

- 动机: 现有工具（agent-browser）不隐藏任何自动化特征，`navigator.webdriver=true`、`Runtime.enable` 泄漏等信号被反爬系统轻松识别。这是所有其他功能的基础——引擎不隐蔽，Cookie 复用和行为模拟都没有意义。
- 描述: 基于 Patchright（Playwright 反检测 fork）构建浏览器引擎。Patchright 有 22 处源码级 patch，不调用 `Runtime.enable`，移除 `--enable-automation` 等参数。引擎以 daemon 进程常驻，浏览器实例在多次 CLI 命令之间保持打开。默认 headless，`--headed` 用于调试。
- 约束: 仅支持 Chromium（Patchright 不支持 Firefox/WebKit）。仅 macOS。daemon 需要优雅处理进程生命周期（启动、心跳、超时关闭、崩溃恢复）。
- 验收标准:
  - CLI 启动后 daemon 进程常驻，后续命令复用同一浏览器实例
  - 在 headless 模式下 `navigator.webdriver` 返回 `false`
  - creepjs.com 检测页面不标记为自动化浏览器
  - 空闲超时后 daemon 自动关闭，下次命令自动重启
- 依赖: 无

### F2: Cookie 自动管理

- 动机: 用户不想每次都手动登录。Cookie 从真实 Chrome 自动提取，维护登录态，只在 session 真正过期时才需要人工介入。这是"零介入全流程"原则的关键实现。
- 描述: 首次使用时通过 pycookiecheat 从 macOS Chrome 解密提取目标站点的 Cookie，注入 Patchright 浏览器上下文。Cookie 缓存到本地 session 文件（加密存储）。后续启动自动加载缓存。检测到登录页跳转时判定 session 过期，自动重新提取；仍失败则报告用户在 Chrome 中重新登录。
- 约束: pycookiecheat 需要 macOS Keychain 授权（首次弹窗，授权后记住）。Chrome 运行时也可读取（只读模式打开 SQLite）。session 文件需加密存储（含 session token）。
- 验收标准:
  - 用户在 Chrome 中已登录小红书/Twitter 的情况下，CLI 首次启动自动获取 Cookie 并成功访问已登录页面
  - Cookie 缓存后重启 daemon 不需要重新提取
  - Session 过期时自动重新提取，不需要用户手动操作
  - 重新提取仍失败时输出清晰的错误信息（"请在 Chrome 中重新登录 xxx"）
- 依赖: F1

### F3: 人类行为模拟

- 动机: 反爬系统不仅检测浏览器指纹，还分析交互行为模式。直线鼠标路径、固定延迟、瞬间滚动都是明显的自动化特征。行为模拟让工具的操作看起来像真人。
- 描述: 集成 humanization-playwright（基于 Patchright 的行为模拟库）实现鼠标轨迹模拟（贝塞尔曲线 + Gaussian 抖动 + overshoot）。打字模拟：库提供变速打字基础，偶发错字 + 退格修正需自行实现。滚动模拟：惯性减速、随机停顿、偶尔回滚。点击前自动 hover 50~300ms。所有行为参数随机化，不产生可识别的模式。注意：不使用库的 `undetected_launch()`（强制 headed），直接用 `Humanization(page, config)` 构造。
- 约束: 行为模拟增加操作耗时（每次点击多 200~500ms，每次打字按字数线性增加）。需要在"像人"和"不太慢"之间平衡。
- 验收标准:
  - 鼠标移动轨迹不是直线，有曲率和速度变化
  - 打字速度不均匀，偶尔出现退格修正
  - 滚动有惯性效果，不是瞬间跳转
  - 点击前有 hover 停留
- 依赖: F1

### F4: 滑块 CAPTCHA 自动解决

- 动机: 小红书在登录和发帖流程中常弹出滑块验证码。如果每次都要人工处理，"零介入"就是空话。V1 先解决最常见的滑块类型。
- 描述: 检测页面中的滑块 CAPTCHA 元素，截图后用 OpenCV 模板匹配/边缘检测确定拼图缺口位置，通过 `generate_bezier_points()` + 手动 mouse.down/move/up 模拟人类拖拽（库的 `drag_to()` 只接受 Locator 不接受坐标）。自动尝试最多 2 次，失败后截图并报告用户。V1 先做拼图滑块（tracer 已验证模板匹配 1px 误差），旋转滑块待真实数据验证后决定。
- 约束: 不处理 reCAPTCHA（图片选择）、Turnstile（行为分析）等复杂 CAPTCHA——直接失败报告。滑块识别精度依赖图像质量，极端情况可能需要重试。
- 验收标准:
  - 检测到滑块 CAPTCHA 时自动尝试解决，不需要用户介入
  - 拼图滑块成功率 > 70%（基于小红书实测）
  - 失败 2 次后停止尝试，返回截图和错误信息
  - 非滑块类 CAPTCHA 直接返回错误，不尝试解决
- 依赖: F1, F3

### F5: CLI 接口

- 动机: 工具通过 Claude Code 的 Bash tool 调用，CLI 是 agent 和工具之间的唯一接口。接口设计直接影响 agent 的使用效率和错误处理能力。
- 描述: 设计面向 AI agent 的 CLI 命令集。核心命令：导航（open）、页面快照（snapshot）、交互（click、fill、type、scroll、upload）、信息获取（get text/url/title）、截图（screenshot）、执行 JS（eval）、关闭（close）。输出格式为结构化纯文本，agent 可直接解析。错误输出到 stderr，包含诊断信息。
- 约束: 每个命令必须是幂等的或有明确的副作用说明。命令失败时返回非零退出码 + 结构化错误信息。不使用 JSON 协议开销（参考 gstack 的设计哲学）。
- 验收标准:
  - agent 通过 CLI 命令完成"打开页面 → 查看元素 → 点击 → 填写 → 截图"的完整流程
  - 错误信息包含足够的上下文让 agent 自主诊断和重试
  - 命令响应时间 < 500ms（daemon 已启动的情况下，不含网络延迟）
  - `--help` 输出所有可用命令和参数
- 依赖: F1, F2, F3

---

## V1 边界

**IN**: F1~F5 全部功能，对小红书和 Twitter 两个站点验证可靠。

**OUT**: reCAPTCHA/Turnstile 自动解决、并发 session、非 macOS 支持、agent-browser 命令兼容、ref 系统/snapshot 优化、CapSolver 集成。
