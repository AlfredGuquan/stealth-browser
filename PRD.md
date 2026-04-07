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

---

## V2: 通用浏览器自动化

V2 目标：从反检测专用工具升级为通用浏览器自动化 CLI，替代 agent-browser 成为唯一浏览器 skill，同时保留反检测优势。

### F6: Snapshot Refs 系统

- 动机: 当前交互需要传完整 CSS selector，脆弱且吃 token。Ref 系统让 agent 用 `click @e3` 替代 `click "div.container > button:nth-child(2)"`，更短、更稳、对 LLM 更自然。这是 token 效率和交互可靠性的根本性改进。
- 描述: `snapshot -i` 输出时为每个可交互元素分配 ref ID（`@e1` `@e2` ...），daemon 侧维护 ref → element 的映射。所有交互命令（click、fill、select、check）同时接受 ref 和 CSS selector。Ref 在每次 `snapshot -i` 时重新生成，旧 ref 失效；导航后自动失效。
- 约束: Ref 映射存在 daemon 内存中，不持久化。Ref 本质是对 DOM 快照时刻元素的引用，DOM 变化后可能 stale——命令执行时若 ref 对应元素不存在，返回清晰错误提示重新 snapshot。
- 验收标准:
  - `snapshot -i` 输出 `@e1 <button> Submit` 格式
  - `click @e1` 正确点击对应元素
  - `fill @e2 "hello"` 正确填写对应输入框
  - 新 snapshot 后旧 ref 失效，使用旧 ref 返回错误
  - 导航后使用旧 ref 返回错误
- 依赖: F5

### F7: Wait 条件

- 动机: 动态页面没有 wait，agent 只能盲等或重试。显式 wait 让 agent 精确等待条件满足后再交互，避免 race condition。
- 描述: `wait` 命令支持四种模式：`wait element <selector|ref>` 等待元素出现、`wait text <text>` 等待文本出现在页面上、`wait network-idle` 等待网络空闲、`wait <ms>` 显式等待毫秒数。默认超时跟随全局 `--timeout`。
- 验收标准:
  - `wait element "button.submit"` 在元素出现后立即返回
  - `wait text "Success"` 在页面包含文本后返回
  - `wait network-idle` 在无新请求 500ms 后返回
  - `wait 2000` 等待 2 秒后返回
  - 超时返回非零退出码和错误信息
- 依赖: F1

### F8: Dialog 处理

- 动机: 页面弹 alert/confirm/prompt 时若无处理机制，浏览器事件循环阻塞，整个 session 卡死。
- 描述: 自动监听 dialog 事件，默认 auto-dismiss 防止阻塞。提供 `dialog accept [text]` 和 `dialog dismiss` 命令让 agent 显式控制。最近一次 dialog 的信息（类型、消息文本）通过 `dialog info` 查询。
- 验收标准:
  - 页面弹出 alert 后 session 不卡死，dialog 被自动 dismiss
  - `dialog accept` 能接受 confirm dialog
  - `dialog info` 返回最近 dialog 的类型和消息
- 依赖: F1

### F9: 导航原语

- 动机: 缺少 back/forward/reload，agent 只能靠 `open` 重新导航，丢失历史栈。
- 描述: 添加 `back`、`forward`、`reload` 命令，映射到 Playwright 的 `page.go_back()`、`page.go_forward()`、`page.reload()`。导航后自动失效当前 refs。
- 验收标准:
  - `back` 回到上一页，`forward` 前进
  - `reload` 重新加载当前页
  - 导航后旧 ref 失效
- 依赖: F1

### F10: Select / Check

- 动机: 下拉框和 checkbox 是表单自动化基本操作，当前 fill/click 覆盖不了。
- 描述: `select <selector|ref> <value>` 选择下拉选项（by value, label, or index）。`check <selector|ref>` / `uncheck <selector|ref>` 操作 checkbox/radio。行为模拟：select 前 hover + 点击展开，check 前 hover。
- 验收标准:
  - `select @e3 "option-value"` 正确选中下拉选项
  - `check @e5` 勾选 checkbox
  - `uncheck @e5` 取消勾选
  - 对已勾选的 checkbox 执行 check 不报错（幂等）
- 依赖: F6（使用 ref）, F3（行为模拟）

### F11: 多 Tab 管理

- 动机: 对比页面、跨 tab 操作、OAuth 回调窗口都需要 tab 切换。
- 描述: daemon 内一个 browser context 支持多个 page（tab）。命令：`tab list`（列出所有 tab 及 ID）、`tab create [url]`（新建 tab，可选导航）、`tab switch <id>`（切换活跃 tab）、`tab close [id]`（关闭 tab，默认当前）。daemon 不再绑定单一 site，`open` 按 URL 域名自动注入对应 cookie。切换 tab 后当前 ref 失效。
- 约束: 所有交互命令作用于当前活跃 tab。Tab ID 为自增整数，从 1 开始。关闭最后一个 tab 不关闭 daemon（保持空 context）。
- 验收标准:
  - `tab create https://example.com` 新建 tab 并导航
  - `tab list` 显示所有 tab（ID、URL、标题、活跃标记）
  - `tab switch 2` 切换到 tab 2，后续命令作用于 tab 2
  - `tab close` 关闭当前 tab，自动切到上一个
- 依赖: F1

### F12: iframe 支持

- 动机: 支付框、嵌入编辑器、验证码等核心内容常在 iframe 内，snapshot 看不到 iframe 内容 agent 就是瞎子。
- 描述: `snapshot -i` 自动检测并内联 iframe 内的可交互元素，ref ID 统一编号（不区分主文档和 iframe）。交互命令通过 ref 自动定位到正确的 frame，agent 无需感知 iframe 边界。对 cross-origin iframe 标注 `[cross-origin]` 但不内联内容（浏览器安全限制）。
- 验收标准:
  - 包含 same-origin iframe 的页面，`snapshot -i` 列出 iframe 内元素
  - `click @e15`（iframe 内元素）正确执行
  - cross-origin iframe 在 snapshot 中标注但不展开
- 依赖: F6

### F13: Batch 模式

- 动机: 多命令流程（填 10 个表单字段）每次 CLI 调用有 Python 启动 + socket 连接开销（100-200ms）。Batch 在 daemon 内部执行，去掉进程开销。
- 描述: `batch` 命令从 stdin 读取 JSON 数组，daemon 内顺序执行。命令间注入 200-800ms 随机停顿模拟人类认知间隙（单独调用时进程启动开销天然提供了这个间隙，batch 去掉了进程开销也去掉了间隙）。`--fast` flag 跳过间隔，用于本地测试等非反检测场景。遇到错误停止执行，返回已成功命令的结果 + 错误命令的信息。
- 验收标准:
  - `echo '[{"cmd":"click","ref":"@e1"},{"cmd":"fill","ref":"@e2","text":"hello"}]' | stealth-browser batch` 顺序执行两个命令
  - 命令间有可观测的随机间隔（200-800ms）
  - `--fast` 跳过间隔
  - 第 2 条命令失败时，返回第 1 条的成功结果和第 2 条的错误
- 依赖: F6（使用 ref）

---

## V3: QA Migration（替代 agent-browser）

V3 目标：补齐 stealth-browser 对 ui-qa-review → browser-qa-agent 调用链的能力支持，让 stealth-browser 能完整替代 agent-browser，最终下线 agent-browser CLI。本版本只覆盖 dogfood 必需的最小能力集，annotate / wait-url / localhost 之外的长尾（视频录制、viewport / device 模拟、network requests、diff）等遇到具体需求再补。

### F14: Localhost Cookie/Login 跳过

- 动机: dev server 都跑在 localhost，但 stealth-browser 的 `open` 默认对所有 URL 走 cookie 提取流程：找不到对应 cookie → 检测到 login 页面 → exit(1)。这一条直接阻塞 ui-qa-review 场景下使用 stealth-browser 替代 agent-browser。dev 场景的 cookie 通常通过其他方式设置（fixture、auth API、登录流程本身就是被测对象），不需要从用户的 Chrome 提取。
- 描述: `open` 命令在导航前判断 URL hostname。命中以下规则视为本地开发环境，自动跳过 cookie 提取/注入和 login_redirect 检测：
  - hostname ∈ {`localhost`, `127.0.0.1`, `[::1]`, `0.0.0.0`}
  - hostname 以 `.local` 结尾（mDNS / Bonjour）

  仍提供 `--no-cookie` 全局 flag 作为通用 escape hatch，对任意 URL 强制跳过 cookie 注入和 login_redirect 检测。两条路径走相同的"无 cookie 模式"分支，避免代码重复。
- 约束:
  - 内网 IP 段（10.x、192.168.x、172.16-31.x）**不算** localhost，仍走正常 cookie 注入分支——这些可能是真实部署的内网应用
  - localhost 自动识别和 `--no-cookie` flag 都不能影响小红书/Twitter 等公网站点的现有 cookie 注入回归
  - 跳过 cookie 注入的同时**也要跳过 login_redirect 检测**，否则 QA 测应用自身的登录功能时会被误判为 "session 过期"
- 验收标准:
  - `open http://localhost:3000` 不尝试 cookie 提取，直接导航，stdout 输出 URL/Title，exit 0
  - `open http://localhost:3000/login` 显示应用的登录页，**不**报 "session expired"，exit 0
  - `open http://127.0.0.1:8080` 行为同 localhost
  - `open http://example.local` 行为同 localhost
  - `open http://192.168.1.100` 仍走 cookie 注入流程（验证内网 IP 不被误判为 localhost）
  - `--no-cookie open https://xiaohongshu.com` 跳过 cookie 注入和 login 检测
  - 对小红书/Twitter 的默认行为不变（回归）
- 依赖: F2（修改 cookie 注入分支）

### F15: Wait URL Pattern

- 动机: 现有 `wait` 命令支持 element/text/network-idle/<ms> 四种模式，但 SPA 的客户端路由跳转后页面 DOM 几乎不变（同一组件 reuse），用 `wait element` 或 `wait text` 都不可靠——需要直接等 URL 模式匹配。典型场景：登录后跳转 `/dashboard`，agent 用 `wait url "**/dashboard"` 比其他 wait 模式更精确。ui-qa-review 的 setup 流程（"提交表单后等待跳转到结果页"）会用到。
- 描述: 在 `wait` 命令下加 `wait url <pattern>` 子命令。pattern 支持 glob（`**` 通配任意路径段），daemon 内部用 Playwright 的 `page.wait_for_url(pattern, timeout=…)` 实现。命中后立即返回当前 URL 到 stdout，超时返回 exit 1 并打印 "timeout waiting for url pattern: …"。timeout 跟随全局 `--timeout`。
- 约束:
  - pattern 是完整 URL 而非 path 片段，匹配整个 URL 字符串
  - glob 而非 regex（避免转义复杂度，与 agent-browser 的 `wait --url` 语义对齐）
  - 不影响其他 wait 子命令
- 验收标准:
  - `wait url "**/dashboard"` 当前 URL 命中后立即返回，stdout 打印新 URL
  - `wait url "https://example.com/**"` 跨域跳转后命中
  - `wait url "**/notexist"` 默认超时后 exit 1，stderr 包含 timeout 信息
  - 已经在目标 URL 时立即返回（不需要 navigation 触发）
- 依赖: F7（wait 命令框架）

### F16: Screenshot Annotate

- 动机: ui-qa-review 的 VISION 模式让 LLM 通过截图理解页面状态。每个可交互元素叠一个编号标签（[1], [2]...）映射到 @e1, @e2... 后，LLM 可以直接从截图判断"点 [3]"，省一次 snapshot 调用并降低 ref 失配风险。这是 ui-qa-review 在视觉验证场景下的关键依赖。
- 描述: `screenshot` 命令加 `--annotate` flag。daemon 已维护 ref → element 映射（来自最近一次 `snapshot -i`），annotate 模式下用 `element.bounding_box()` 获取每个 ref 的屏幕坐标，在元素位置叠一个半透明黄色背景 + 黑色数字 label。Label 默认放在元素左上角内侧（避免越出 viewport）。截图保存后 stdout 第一行输出文件路径，后续行输出 legend：`[N] @eN <tag> "<text>"` 一行一个。
- 约束:
  - 必须先有 snapshot -i 缓存的 refs，否则 annotate 报错 `no refs cached, run snapshot -i first` 并 exit 1
  - Label 编号与 ref 编号一致（@e1 → [1]）
  - 不修改页面 DOM——叠加发生在截图后（PIL/Pillow 在图像层绘制），不通过 page.evaluate 注入 overlay。这避免对人类行为模拟和反检测的潜在干扰
  - 字号和颜色固定，不暴露配置
- 验收标准:
  - `snapshot -i` 后 `screenshot --annotate` 生成带编号标签的截图，路径打印到 stdout 第一行
  - stdout 后续行打印 legend：每行格式 `[N] @eN <tag> "<text>"`
  - 没有 ref 缓存时 `screenshot --annotate` 报错并 exit 1
  - 标签 [N] 视觉上在对应元素上方/左上角
  - 不改动页面 DOM（截图前后 snapshot 输出一致）
- 依赖: F6（refs 系统），新增 Pillow 依赖（uv add pillow）
