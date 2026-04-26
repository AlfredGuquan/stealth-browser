# Stealth Browser

Universal browser automation CLI for AI agents with anti-detection. Python + Patchright + pycookiecheat + humanization-playwright + OpenCV. macOS only.

## Docs

| 文件 | 内容 |
|------|------|
| PRINCIPLES.md | 5 条核心原则：效果第一、零介入、完整链路、可靠胜过通用、可观测 |
| PRD.md | V1 五个 feature + V2 八个 feature（refs/wait/dialog/nav/select/tab/iframe/batch）+ 验收标准 |
| ARCHITECTURE.md | 数据流、模块地图、层级规则 |
| specs/prototype/ | tracer bullet findings（反检测验证、行为模拟验证） |

## Project Structure

```
stealth_browser/
├── cli.py          # CLI 入口，argparse 命令路由
├── daemon.py       # asyncio daemon（Unix socket），浏览器生命周期管理
├── engine.py       # Patchright 引擎封装，导航/交互/截图
├── cookies.py      # Chrome Cookie 提取（pycookiecheat）、缓存、过期检测
├── behavior.py     # 人类行为模拟 facade（鼠标/打字/滚动/拖拽）
├── captcha.py      # 滑块 CAPTCHA 检测 + OpenCV 解决
└── utils.py        # 共享工具（路径、UA 检测、错误输出）
tests/
├── unit/           # 单元测试（170 个，mock-based）
└── test_*.py       # tracer 验证脚本（集成测试，需真实 Chrome）
```

## Commands

```bash
# 导航
uv run stealth-browser open <url>              # 导航（自动注入 Cookie）
uv run stealth-browser back                    # 后退
uv run stealth-browser forward                 # 前进
uv run stealth-browser reload                  # 重新加载

# 观察
uv run stealth-browser snapshot [-i]           # 页面快照（-i 列出可交互元素 + @eN refs）
uv run stealth-browser screenshot [path]       # 截图
uv run stealth-browser get <text|url|title>    # 获取页面信息

# 交互（接受 @eN ref 或 CSS selector）
uv run stealth-browser click <selector>        # 点击（人类行为模拟）
uv run stealth-browser fill <selector> <text>  # 填写输入框（变速打字 + 偶发错字）
uv run stealth-browser type <text>             # 当前焦点位置打字
uv run stealth-browser select <selector> <val> # 下拉选择
uv run stealth-browser check <selector>        # 勾选 checkbox
uv run stealth-browser uncheck <selector>      # 取消勾选

# 等待
uv run stealth-browser wait element <sel>      # 等待元素出现
uv run stealth-browser wait text <text>        # 等待文本出现
uv run stealth-browser wait network-idle       # 等待网络空闲
uv run stealth-browser wait <ms>               # 等待毫秒数

# 断言（PASS=exit 0；FAIL=exit 1 + code:ASSERTION_FAILED；可在 batch 中使用）
uv run stealth-browser assert text <text>      # 断言文本存在于页面
uv run stealth-browser assert element <sel>    # 断言元素存在（@eN 或 CSS）

# Tab 管理
uv run stealth-browser tab list                # 列出所有 tab
uv run stealth-browser tab create [url]        # 新建 tab
uv run stealth-browser tab switch <id>         # 切换 tab
uv run stealth-browser tab close [id]          # 关闭 tab

# Dialog
uv run stealth-browser dialog accept [text]    # 接受 dialog
uv run stealth-browser dialog dismiss          # 关闭 dialog
uv run stealth-browser dialog info             # 查看最近 dialog 信息
uv run stealth-browser dialog auto-dismiss on  # 开启自动关闭

# 网络录制（always-on，所有请求自动缓冲）
uv run stealth-browser network start           # 标记录制起点
uv run stealth-browser network stop [--types xhr fetch]  # 返回起点后的请求
uv run stealth-browser network list [--types ...]        # 列出所有缓冲请求
uv run stealth-browser network clear           # 清空缓冲区

# 高级
uv run stealth-browser eval <js>               # 执行 JavaScript
uv run stealth-browser batch [--fast]          # 从 stdin 读 JSON 批量执行
uv run stealth-browser close                   # 关闭浏览器和 daemon

# 测试
uv run python -m pytest tests/unit/ -q         # 运行单元测试
```

## Git

Conventional commits. 不 `git add -A`，只 stage 当前变更涉及的文件。

**modifying engine.py or daemon.py:**
- 必须用 `patchright.async_api`，不能用 sync API（greenlet 不能跨线程）
- 浏览器启动必须 `channel='chrome'`（系统 Chrome），headless UA 必须显式覆盖
- Cookie 注入在 `new_context()` 之后、首次 `goto()` 之前

**modifying behavior.py:**
- 不使用 `undetected_launch()`（强制 headed），直接 `Humanization(page, config)` 构造
- 非 ASCII 字符（中文等）用 `keyboard.insert_text()`，不用 `keyboard.press()`
- 滑块拖拽用 `generate_bezier_points()` + 手动 mouse 操作，不用 `drag_to()`

**modifying cookies.py:**
- pycookiecheat `as_cookies=True` 返回自定义 dataclass：`host_key`（非 `domain`）、`expires_utc`（Chrome 微秒时间戳，需 `/ 1e6 - 11644473600` 转 Unix 秒）、`is_secure`（非 `secure`）
- site 名必须经过 `_validate_name()` 清洗，防路径遍历

### Learned Constraints

- `context.add_cookies()` 是 context 级存储、domain 级隔离——多 tab 场景不需要改 cookie 注入策略，各 page 自动只看到自己 domain 的 cookie（详见 `specs/prototype/multi-tab-findings.md`）
- HumanBehavior 和 CaptchaSolver 绑定单个 Page 实例，多 tab 必须每 tab 创建独立实例，不要复用/swap（Humanization 内部可能缓存 page 状态）
- 关闭 page 完全隔离：不影响 context 和其他 page，关闭最后一个 page 后 context 仍存活可创建新 page
- Snapshot refs 用 `data-ref` 属性注入 + `[data-ref="@eN"]` attribute selector 解析，不需要生成 CSS selector 或 XPath（详见 `specs/prototype/snapshot-refs-findings.md`）
- iframe 内元素交互：先 `frame.evaluate()` 注入 ref，再 `page.frame_locator(selector).locator('[data-ref]')` 定位。daemon 需维护 ref → frame_index 映射
- ref 编号必须跨所有 frames 使用单一计数器，避免 main page 和 iframe 的 ref 冲突
- 导航后 ref 自动失效（DOM 替换），daemon 只需在导航命令时清空内存映射
- cross-origin iframe 的 `frame.evaluate()` 会抛异常，snapshot 应标注 `[cross-origin]` 但不注入 ref
- pycookiecheat 对 `localhost` / `127.0.0.1` / `*.local` 优雅返回空 list 不抛异常——F14 gating 不需要 cookies.py 增 try/except；但 login_redirect 检测在 engine.navigate 内，必须在 cli/engine 层用 hostname 判断同时跳过 cookie 注入和 login_redirect 检测，单靠 cookies 模块返回空满足不了验收（详见 `specs/prototype/v3-qa-migration-findings.md` F14）
- Patchright `page.wait_for_url(pattern, timeout)` 直接覆盖 F15 全部 4 条验收：已在目标 URL 时立即返回（~10ms），glob 严格字面匹配（`**/index.html` 不会自动匹配 `/`），不匹配 raise `TimeoutError`，跨域跳转支持。daemon 加一个 wait_type=url 分支 + engine 一个 wrapper 即可
- F16 annotate 坐标公式：`page.screenshot(full_page=True)` 的 PNG 跨整个文档高度，但 `element.bounding_box()` 返回 **viewport-relative** CSS 像素坐标。正确映射 `pixel = (bbox + scrollOffset) * DPR`。最简策略是截图前 `scrollTo(0,0)` 让公式塌缩成 `bbox * DPR`，在 try/finally 里 restore 原 scroll。DPR 从 `PNG.width / viewport.width` 实测，不要硬编码（详见 `specs/prototype/v3-qa-migration-findings.md` F16）
