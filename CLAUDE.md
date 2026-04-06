# Stealth Browser

Anti-detection browser automation CLI for AI agents. Python + Patchright + pycookiecheat. uv managed.

### Learned Constraints

- Patchright 启动必须用 `channel='chrome'`（系统 Chrome），不用 bundled Chromium -- bundled 版本有 11 项反检测信号暴露（验证：specs/prototype/stealth-browser-findings.md）
- headless 模式的 UA 仍含 "HeadlessChrome"，必须在 `new_context(user_agent=...)` 显式覆盖
- pycookiecheat `as_cookies=True` 返回 `pycookiecheat.common.Cookie` dataclass（不是 `http.cookiejar.Cookie`）：`host_key` 非 `domain`，`expires_utc` 非 `expires`（Chrome 微秒时间戳需 `/ 1e6 - 11644473600` 转 Unix 秒），`is_secure` 非 `secure`
- Patchright sync API 基于 greenlet，不能跨线程调用 -- daemon 必须用 `patchright.async_api` + asyncio 事件循环
- Cookie 注入用 `context.add_cookies()`，在 `new_context()` 之后、首次 `goto()` 之前
