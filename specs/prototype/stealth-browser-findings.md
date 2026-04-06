## Tracer Bullet Report: Stealth Browser Core Path

### 选定路径
Patchright stealth launch (headless) -> Chrome cookie extraction via pycookiecheat -> cookie injection into browser context -> navigate to x.com/home as logged-in user -> all via HTTP daemon that keeps browser alive across requests.

### 集成点验证结果

| 层级 | 集成点 | 状态 | 验证方式 + 关键发现 |
|------|--------|------|---------------------|
| 引擎层 | Patchright headless 反检测 | ✅ | `uv run python tests/test_stealth.py` -- `navigator.webdriver=false`。但**必须用 `channel='chrome'`（系统 Chrome）而非 bundled Chromium**。bundled Chromium 有 11 项检测失败（HeadlessChrome UA、window.chrome 缺失、plugins 为空、WebGL 无上下文）。系统 Chrome + 自定义 UA 后 bot.sannysoft.com **56 项全部通过，0 失败**。截图：`/tmp/stealth-test-chrome.png` |
| Cookie 层 | pycookiecheat 提取 + Patchright 注入 | ✅ | `uv run python tests/test_cookie.py` -- 提取 17 个 cookie，注入后导航 x.com/home 停留在首页（title="Home / X"），未重定向到登录页。截图 `/tmp/cookie-test-twitter.png` 确认显示用户名和 compose box。关键发现：(1) `as_cookies=True` 返回的是 `pycookiecheat.common.Cookie` dataclass，不是 `http.cookiejar.Cookie`——属性名不同（`host_key`/`expires_utc`/`is_secure`）；(2) `expires_utc` 是 Chrome 内部时间戳（微秒，1601 年起），需转换为 Unix epoch 秒：`int((expires_utc / 1_000_000) - 11644473600)` |
| Daemon 层 | 浏览器实例跨请求保活 | ✅ | `uv run python tests/test_daemon.py` -- 6 个 HTTP 请求（goto/status/screenshot/eval/goto/status）全部成功，browser_connected 始终为 true，page state 在请求间保持。关键发现：**必须用 async API**（`patchright.async_api`），sync API 的 greenlet 实现无法跨线程调用——HTTP handler 线程调用 sync_playwright 会报 `cannot switch to a different thread`。daemon 需要 asyncio 事件循环统一管理浏览器和 HTTP server |
| 端到端 | Cookie + 反检测 + Daemon 联合 | ✅ | `uv run python tests/test_e2e.py` -- 完整流程：提取 cookie -> 启动 daemon -> 验证 stealth -> 注入 cookie -> 导航 x.com/home -> 截图 -> 持久性检查。7 个步骤全部通过。截图 `/tmp/e2e-stealth-cookie-daemon.png` 确认已登录状态 |

### 关键发现

1. **必须使用 `channel='chrome'`**：Patchright bundled Chromium 在 headless 模式下仍然暴露大量自动化信号。`channel='chrome'` 使用系统安装的 Chrome，反检测效果显著提升（56/56 通过 vs 45/56）。这意味着部署时**依赖用户系统已安装 Chrome**，属于合理约束（目标用户是 macOS 开发者）。

2. **pycookiecheat Cookie 对象的属性映射**：文档和常见示例假设返回 `http.cookiejar.Cookie`，实际返回 `pycookiecheat.common.Cookie` dataclass。字段映射：`domain` -> `host_key`, `expires` -> `expires_utc`（Chrome 时间戳格式，需转换）, `secure` -> `is_secure`。没有 `httpOnly` 字段。

3. **Daemon 必须用 async 架构**：Patchright sync API 基于 greenlet，无法从非创建线程调用。daemon 需要 asyncio 事件循环同时驱动 HTTP server 和浏览器操作。这不是限制而是正确的架构方向——asyncio 天然适合 I/O 密集的浏览器自动化。

4. **UA 需手动设置**：即使 `channel='chrome'`，headless 模式仍然在 UA 中包含 "HeadlessChrome"。需要在 `new_context()` 时显式设置 `user_agent` 为正常 Chrome UA 字符串。

5. **Cookie 注入时机**：cookies 必须在 `new_context()` 之后、首次 `goto()` 之前通过 `context.add_cookies()` 注入。注入到 context 而非 page 级别，所以同一 context 下新开的 page 也能共享 cookie。

### 代码变更

- `pyproject.toml`: 项目初始化，声明 patchright + pycookiecheat 依赖
- `tests/test_stealth.py`: 反检测验证——对比 bundled Chromium vs system Chrome 在 bot.sannysoft.com 的检测结果
- `tests/test_cookie.py`: Cookie 提取注入验证——从 Chrome 提取 x.com cookie，转换格式，注入 Patchright，导航验证登录态
- `tests/test_daemon.py`: Daemon 架构验证——asyncio HTTP server + Patchright async API，6 个请求证明浏览器跨请求存活
- `tests/test_e2e.py`: 端到端联合验证——三个集成点串联，7 步流程全部通过

### 对后续实现的建议

- **引擎初始化标准配置**：`launch(headless=True, channel='chrome')` + `new_context(user_agent=CHROME_UA)` 应该是引擎的默认配置，不需要用户指定。UA 字符串应从系统 Chrome 版本动态获取而非硬编码。
- **Cookie 转换模块**：pycookiecheat.common.Cookie -> Playwright cookie 的转换逻辑需要封装，包括 Chrome 时间戳到 Unix epoch 的转换。这是一个容易出错的接缝。
- **Daemon 架构选型**：已证明 asyncio + Patchright async API 可行。生产实现建议用 `aiohttp` 或 `uvicorn` 替代手写 HTTP protocol（手写版不处理 chunked encoding、keep-alive 等），但核心模式不变：单一 asyncio 事件循环管理浏览器生命周期 + HTTP 接口。
- **系统 Chrome 依赖**：启动时应检测系统 Chrome 是否存在，不存在时给出明确错误信息而非让 Patchright 报不透明的错误。
