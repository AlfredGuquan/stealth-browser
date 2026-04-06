## Tracer Bullet Report: Snapshot Refs + iframe Interaction

### 选定路径
JS `evaluate()` 批量注入 `data-ref` 属性 → `page.locator('[data-ref="@eN"]')` 解析并交互 → `page.frame_locator().locator()` 跨 iframe 交互 → 导航后 ref 自动失效

### 集成点验证结果

| 层级 | 集成点 | 状态 | 验证方式 + 关键发现 |
|------|--------|------|---------------------|
| DOM 层 | JS `evaluate()` 批量设置 `data-ref` 属性并返回映射 | ✅ | `page.evaluate(ASSIGN_REFS_JS)` 返回 8 个元素的映射，包含 button/input/a/select/textarea/div[role=button]。querySelectorAll 正确匹配所有交互元素类型。 |
| Patchright API 层 | `page.locator('[data-ref="@eN"]')` 解析并交互 | ✅ | attribute selector 精确匹配，count=1。click 触发 onclick handler（验证：`#click-result` 文本变为 "clicked"）。fill 正确写入值（验证：`input_value()` = "tracer-test-value"）。role="button" 的 div 同样可通过 ref click。 |
| 跨 frame 层 | `page.frames` 枚举 + `frame_locator().locator('[data-ref]')` 交互 | ✅ | `page.frames` 返回 2 个 frame（main + iframe）。`frame.evaluate()` 可在 iframe 内独立运行 JS 注入 ref。`page.frame_locator('#test-iframe').locator('[data-ref="@e1"]')` 成功 click 和 fill iframe 内元素。 |
| 生命周期层 | 导航后 data-ref 自动失效 | ✅ | `page.goto('about:blank')` 后，`querySelectorAll('[data-ref]').length` = 0。`page.locator('[data-ref="@e1"]').count()` = 0。浏览器原生 DOM 替换机制天然保证 ref 失效。 |

### 关键发现

1. **data-ref 方案完全可行**：JS 注入 attribute + Patchright attribute selector locator 是最简单可靠的 ref 实现。无需 CSS selector 生成或 XPath。
2. **iframe 交互需要两步**：先 `frame.evaluate()` 在 iframe DOM 内注入 ref，再用 `page.frame_locator(selector).locator('[data-ref]')` 定位。daemon 实现时需维护 ref → frame 的映射，使 agent 无需感知 iframe 边界。
3. **ref 编号需全局统一**：当前实验中 main page 和 iframe 各自从 @e1 开始编号（独立 evaluate 调用）。生产实现必须用单一计数器跨 frame 编号，避免冲突。daemon 应先遍历所有 frames，统一编号。
4. **srcdoc iframe 的 onclick 编码陷阱**：`srcdoc` 属性中的 `&quot;` 经两层 HTML 解析后变成裸引号，破坏 onclick 属性。实际站点使用 `src` 加载的 iframe 不会有此问题，但测试 fixture 需注意。这不影响生产实现。
5. **frame 识别**：srcdoc iframe 的 URL 是 `about:srcdoc`，src iframe 是正常 file:// URL。`page.frames` 按 DOM 顺序返回。iframe 的 `frame.name` 等于 iframe 元素的 `id` 属性（当设置了 `id` 时）。
6. **ref 失效是免费的**：导航后浏览器替换整个 DOM，data-ref 属性自然消失。daemon 只需在收到 `open`/`back`/`forward`/`reload` 命令时清空内存中的 ref 映射即可。

### 代码变更
- `tests/fixtures/refs_test.html`: 测试页面，含 button/input/link/select/textarea/form + same-origin iframe
- `tests/fixtures/refs_iframe.html`: iframe 内容页面
- `tests/tracer_refs.py`: 自包含实验脚本，3 个实验全 PASS

### 对后续实现的建议
- **snapshot -i 实现**：遍历 `page.frames`，对每个 frame 调用 `evaluate(ASSIGN_REFS_JS)` 并传入当前计数器偏移。返回合并后的映射存入 daemon 内存。
- **ref → locator 解析**：daemon 的 ref 映射应存储 `{ref: {frame_index, selector: '[data-ref="@eN"]'}}`。交互命令解析 ref 时，根据 frame_index 选择 `page.locator()` 或 `page.frame_locator().locator()`。
- **cross-origin iframe**：`frame.evaluate()` 对 cross-origin iframe 会抛异常。snapshot 应 try/except 并标注 `[cross-origin]`，不尝试注入 ref。
- **stale ref 处理**：交互命令执行时，先检查 `locator.count()` == 1，为 0 则返回 "ref stale, re-run snapshot" 错误。
