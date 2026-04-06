## Tracer Bullet Report: Multi-Tab Architecture (F11)

### 选定路径
Patchright context 多 page 创建 → Cookie domain 作用域验证 → HumanBehavior page 绑定策略 → Page 关闭隔离

### 集成点验证结果

| 层级 | 集成点 | 状态 | 验证方式 + 关键发现 |
|------|--------|------|---------------------|
| Patchright 底层 | 单 context 多 page | ✅ | `context.new_page()` × 2，各自导航到不同 URL，`context.pages` 返回 2，两个 page 独立操作互不干扰 |
| Cookie 数据层 | `context.add_cookies()` domain 作用域 | ✅ | cookies 存储在 context 级别但按 domain 隔离。page1 (example.com) 只看到 `.example.com` 的 cookie，page2 (httpbin.org) 只看到 `.httpbin.org` 的 cookie。`context.cookies()` 返回所有 domain 的 cookie |
| 行为模拟层 | HumanBehavior page 绑定 | ✅ | **两种策略都可行**：(A) 直接赋值 `hb.page = page2; hb._h.page = page2` 后 scroll 正常执行；(B) 每个 page 创建独立 `HumanBehavior` 实例也正常工作。推荐 B（新实例/page），避免 Humanization 内部状态泄漏风险 |
| 生命周期层 | Page 关闭隔离 | ✅ | 关闭 page2 后：page1 仍然存活且可操作，context 仍可创建新 page，已关闭的 page2 访问时抛异常 |

### 关键发现

1. **Cookie 是 context 级存储、domain 级隔离**：`context.add_cookies()` 添加到 context 的 cookie jar，浏览器按标准 cookie 规则按 domain 分发。这意味着 daemon 的 `inject_cookies(site, url)` 现有逻辑可以直接复用——不同 tab 打开不同站点，各自只看到自己 domain 的 cookie。**不需要改 cookie 注入策略**。
2. **`context.add_cookies()` domain 格式差异**：注入 `.example.com`（带前导点）和 `httpbin.org`（不带点）都能正确工作。`context.cookies()` 返回时 domain 格式与注入时一致。pycookiecheat 返回的 `host_key` 带前导点，可直接使用。
3. **HumanBehavior 应该每 tab 一个实例**：虽然直接替换 `page` 属性也能工作，但 `Humanization` 内部可能缓存 page 相关状态（如 viewport 尺寸），创建新实例更安全。成本可忽略（纯 Python 对象创建）。
4. **Page 关闭完全隔离**：关闭一个 page 不影响 context 和其他 page。关闭最后一个 page 后 context 仍然存活，可以继续创建新 page。这意味着 F11 的"关闭最后一个 tab 不关闭 daemon"约束可以直接实现。
5. **`context.pages` 实时反映当前活跃 page 列表**：可用于实现 `tab list`。

### 代码变更
- `tests/tracer_tabs.py`: 4 个实验的自包含脚本

### 对后续实现的建议

1. **daemon 数据结构**：`StealthEngine` 从单 `self.page` 改为 `self.pages: dict[int, Page]` + `self.active_tab_id: int`。Tab ID 从 1 自增。
2. **HumanBehavior 管理**：每个 tab 维护独立的 `HumanBehavior` 实例，存在 `self.behaviors: dict[int, HumanBehavior]` 中。切换 tab 时切换 active behavior。
3. **CaptchaSolver 同理**：它持有 page + behavior 引用，也需要 per-tab 实例。
4. **Cookie 注入无需改动**：现有 `context.add_cookies()` 已经是 domain 级隔离，多 tab 自动受益。`inject_cookies` 方法只需确保在 `goto()` 之前为目标 URL 的 domain 注入即可。
5. **现有命令路由**：`DaemonHandler.handle()` 中所有 `self.engine.xxx()` 调用需要意识到"当前活跃 tab"。最小改动是让 `StealthEngine` 的属性（`page`, `behavior`, `captcha`）变成指向 active tab 的动态属性。
6. **Tab 切换需要 ref 失效**：切换 tab 后当前 snapshot refs 必须清空（PRD 已注明此约束）。
