# Status

## 目标

V2：从反检测专用工具升级为通用浏览器自动化 CLI，替代 agent-browser 成为唯一浏览器 skill。

## Blocker

## In Progress

- 手动 e2e 验证待做：`open` → `snapshot -i` → `click @e1` → `tab create` → `batch`（V2 验证套件）

## Pending

### V3 follow-up（迁移收尾，下一轮 build）

- 新建 `~/.claude/agents/stealth-browser-qa-agent.md`（复制 browser-qa-agent，把 `skills:` 字段从 `[agent-browser]` 改成 `[stealth-browser]`）
- `~/.claude/skills/ui-qa-review/SKILL.md` 加 `UI_QA_REVIEW_BROWSER` 环境变量切换 agent type，默认仍走 agent-browser
- 在 data-annotation 项目跑首次双轨 dogfood，比对 stealth-browser vs agent-browser 的 verdict 截图一致性
- 验证通过后：切默认 `stealth-browser`，下线 agent-browser，移除 suppress-plugin-skills hook 中相关条目

### V2/V3 backlog

- `@eN` ref 在 `batch` 中不可用：导航后 ref 失效，但 batch 内部没机会重新 `snapshot -i` 获取新 ref。当前只能在 batch 中用 CSS selector，限制了 ref 系统的适用范围。考虑允许 batch 步骤中插入 `snapshot` 命令并把结果传递给后续步骤，或者支持"navigate 后自动重新生成 refs"
- 收集真实小红书滑块截图验证 CAPTCHA 模板匹配精度
- 更新 stealth-browser skill（SKILL.md）补充 V2 + V3 新增命令

## Backlog

### Agent 接口 polish（F5 细化）

- [ ] `_get_session()` fallback 非确定性：不指定 `--site` 且有多个活跃 session 时，遍历 `STATE_DIR.glob("*.pid")` 返回顺序不保证，可能操作到非预期 session。修复方向：多 session 时必须显式 `--site`，否则报错列出所有可选 session
- [ ] `--help` 增强：每个子命令补 EXAMPLES 段和 LIMITATIONS 段，agent 靠 `--help` 自发现用法和已知边界

### P2 — 效率提升（未实现部分）

- [x] ~~网络请求读取~~ → Completed [2026-04-09]
- [ ] Session 命名（同站多 session 支持）

### P3 — 完整性补全

- [ ] 设备模拟（viewport / device 切换）
- [ ] PDF 导出
- [ ] Proxy 支持
- [ ] 视频录制 / Profiling / Diff

### V1 遗留

- publish skill 端到端验证（用 /publish 发一篇真实帖子确认 stealth-browser 集成可用）

## Completed

- 加载 unpacked Chrome extension（`--extension` flag + `STEALTH_BROWSER_EXTENSIONS` env）：engine.launch 接 extensions 参数，自动切 `launch_persistent_context` + bundled Chrome for Testing（branded Chrome 137+ 拒绝 --load-extension），强制 headed，单独 profile 目录 `~/.stealth-browser/ext-profile`。CLI `--extension <path>`（可重复）+ env fallback（`os.pathsep` 分隔，explicit flag 覆盖 env）。fixture `tests/fixtures/minimal_extension/` + e2e `test_extension_e2e.py`（PASS 17.68s，content_script 注入 meta marker 验证）。269 单测 PASS（新增 17：6 env fallback + 3 flag + 8 engine）。CLAUDE.md 沉淀 bundled Chrome 约束。三个风险点（chrome.sidePanel API / service worker onMessage / cookie 注入冲突）撞到再 spike——personal-website 真实扩展验证留到 #6d。[2026-04-26]
- 内置断言机制（assert text/element）：engine 加 assert_text / assert_element（document.body.innerText.includes / querySelectorAll；不等待，可与 wait 组合），daemon assert dispatch + 失败映射 ASSERTION_FAILED；CLI `assert <kind> <target>` 命令；batch 自动 short-circuit。263 单测 PASS（新增 16：11 assertions + 5 cli）。多步交互测试不再需要"截图 → 目视判定"，结构化断言。[2026-04-26]
- scroll 后自动返回 visible_text：engine.visible_text() 用 TreeWalker + Range.getBoundingClientRect 抓 viewport 内文本节点，1500 字上限，slicing 在 JS 端避免 marshalling 全文回 Python。daemon scroll handler 透传到响应；cli 输出 `<message>\n---\n<text>`，空文本时不打分隔符。247 单测 PASS（新增 7：3 visible_text + 1 daemon + 3 cli）。Agent 不再需要 scroll → screenshot → Read 三回合判断 viewport 状态。[2026-04-26]
- 错误消息结构化（F5 三项）：utils.error 输出 4 行 (error/code/retryable/fix)；exit code 分档（USAGE→2、AUTH_EXPIRED→5、其他→1）；cmd_open login_redirect 走 error()，失败路径不污染 stdout。daemon 加 `_err()` helper，10 处错误响应迁移；cli 14 处 error() 调用补 code/retryable/fix；engine→daemon 异常自动判 AUTH_EXPIRED。240 单测 PASS（新增 14：6 utils + 8 daemon + 6 cli），e2e NO_SESSION 验证 4 行输出 + exit 1。[2026-04-26]
- Agent 反馈修复（4 fix）：click post-verify 检测静默失败、fill Meta+A→Delete 替换而非追加、ref 重复匹配 graceful handling、batch wait 错误消息列出合法 type。211 单元测试 PASS + code review + e2e 验证（example.com 导航 click + localhost fill 替换）[2026-04-13]
- V3 实现：3 个 feature（F14 localhost cookie/login 跳过、F15 wait url pattern、F16 screenshot annotate），32 新单元测试，202 总测试 PASS。Tracer findings + code-review 2 important issues 修复（F16 scroll-behavior:smooth 竞态、F15 异常类型过宽）。Smoke test 覆盖 F14（localhost smooth-scroll 页）+ F15（fixture 跨页导航 positive/negative）+ F16（snapshot + annotate 输出 PNG）
- V2 实现（PR#1）：8 个 feature（refs/wait/dialog/nav/select-check/tab/iframe/batch），170 单元测试
- V2 code review：2 critical + 3 important 全部修复
- V2 feature audit：31 验收标准，29 PASS + 2 PARTIAL → 修复后全 PASS
- V1 实现：5 个 feature（引擎/Cookie/行为模拟/CAPTCHA/CLI），77 单元测试
- V1 code review：4 blocker + 4 important 全部修复
- QA 验证：Twitter 发帖 PASS，小红书发帖 PASS
- CJK 输入 bug 修复
- network recording 命令（start/stop/list/clear） -- always-on request/response 录制，`--types` 按 resource type 过滤（Claude 自选），5000 条环形缓冲区。202 单元测试 PASS + Unsplash 懒加载 e2e 验证 PASS [2026-04-09]
- stealth-browser skill 创建 + 可用性验证（显式调用 PASS，Cookie 自动注入 PASS）
- publish skill 重写（agent-browser CDP → stealth-browser）
- agent-browser 加入 suppress-plugin-skills hook，不再自动路由
