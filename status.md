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

- **加载 unpacked Chrome extension（`--load-extension <path>`）**：当前 stealth-browser 的 Patchright launch 不支持加载本地未打包扩展，导致无法测试任何依赖浏览器扩展的端到端流程。触发场景：personal-website F28 视频批注链路要验证 Web Clipper 扩展的 sidepanel.js → background.js → browser-companion WS server 的完整链路，stealth-browser 没法加载 `extension/` 目录就完全无能为力，最后只能退回让用户手动 toggle extension + 看 console。这是 V2 替代 agent-browser 的 hard blocker——agent-browser 有 `--extension <path>`（可重复）和 `AGENT_BROWSER_EXTENSIONS` 环境变量，stealth-browser 缺这块就 cover 不了"测自家扩展"的场景。
  - 实现方向：Patchright 的 `chromium.launch_persistent_context()` 接受 `args=['--load-extension=/abs/path1,/abs/path2', '--disable-extensions-except=...']`，daemon 启动时若设置了 extension paths 就走 persistent context 路径而不是普通 `launch()`。CLI 支持 `--load-extension <path>` 可重复 + `STEALTH_BROWSER_EXTENSIONS` 环境变量。注意：扩展加载强制 headed 模式（Chromium 限制，headless 不加载扩展），文档要明示这个约束
  - 技术风险点（spike 必须先做）：1）Patchright/Playwright Chromium build 是否完整支持 `chrome.sidePanel` API——历史上 Playwright Chromium 的 sidePanel 实现有缺失，启 spike 验证 `chrome.sidePanel.open()` 在 Patchright headed 下能不能 work；2）扩展通过 service worker 的 `chrome.runtime.onMessage` 路径在 Patchright 反检测 patch 下是否被破坏；3）Patchright `launch_persistent_context` 与现有 daemon 的 cookie 注入策略冲突（persistent context 自带 profile 目录，cookie 走 profile 不是 `add_cookies()`）——cookie 注入逻辑可能要分支
  - 验收：能加载 personal-website 的 `extension/` 目录，open 到 alfredgu.com 视频页，能触发 chrome.sidePanel 打开，sidepanel.js 能完整跑起来连上本地 ws server
- `batch` 命令缺少条件断言：现有 batch 只是顺序执行命令，无法在步骤之间做"等待状态满足"的检查。多步交互测试（翻卡→评分→验证→重复）只能拆成多次独立 Bash 调用，每次 ~6s 进程启动开销累加。建议加入 `wait text/element` 在 batch 中作为隐式断言（超时报错退出），让多步流程一次调用完成
- `@eN` ref 在 `batch` 中不可用：导航后 ref 失效，但 batch 内部没机会重新 `snapshot -i` 获取新 ref。当前只能在 batch 中用 CSS selector，限制了 ref 系统的适用范围。考虑允许 batch 步骤中插入 `snapshot` 命令并把结果传递给后续步骤，或者支持"navigate 后自动重新生成 refs"
- 收集真实小红书滑块截图验证 CAPTCHA 模板匹配精度
- 更新 stealth-browser skill（SKILL.md）补充 V2 + V3 新增命令

## Backlog

### Agent 接口 polish（F5 细化）

- [ ] `_get_session()` fallback 非确定性：不指定 `--site` 且有多个活跃 session 时，遍历 `STATE_DIR.glob("*.pid")` 返回顺序不保证，可能操作到非预期 session。修复方向：多 session 时必须显式 `--site`，否则报错列出所有可选 session
- [ ] `cmd_open` 登录重定向时混合输出：检测到 login_redirect 后 stdout 已经打印了 URL/Title 再 stderr 报错 exit 1，agent 可能基于 stdout 内容误判成功。修复方向：失败路径只写 stderr，stdout 不输出任何字段
- [ ] Exit code 分档：参数错误用 exit 2，认证过期/cookie 失效用 exit 5，其他运行时错误统一 exit 1。不强行细分网络/超时/元素未找到——Patchright 层错误难以可靠分类，误分类会诱导 agent 走错分支
- [ ] 错误消息结构化（保持纯文本，F5 明确排除 JSON）：在 `error:` 后追加 `code:` `retryable:` `fix:` 三行，agent 靠 key 解析。例：`error: page.goto timed out\ncode: TIMEOUT\nretryable: true\nfix: retry with longer --timeout`
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
