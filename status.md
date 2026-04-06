# Status

## 目标

V2：从反检测专用工具升级为通用浏览器自动化 CLI，替代 agent-browser 成为唯一浏览器 skill。

## Blocker

## In Progress

## Pending

- 收集真实小红书滑块截图验证 CAPTCHA 模板匹配精度

## Backlog

### P2 — 效率提升（未实现部分）

- [ ] 网络请求读取（`network requests`，检查 API 响应）
- [ ] Session 命名（同站多 session 支持）

### P3 — 完整性补全

- [ ] 设备模拟（viewport / device 切换）
- [ ] PDF 导出
- [ ] Proxy 支持
- [ ] 视频录制 / Profiling / Diff

### V1 遗留

- publish skill 端到端验证（用 /publish 发一篇真实帖子确认 stealth-browser 集成可用）

## Completed

- V2 实现（PR#1）：8 个 feature（refs/wait/dialog/nav/select-check/tab/iframe/batch），170 单元测试
- V2 code review：2 critical + 3 important 全部修复
- V2 feature audit：31 验收标准，29 PASS + 2 PARTIAL → 修复后全 PASS
- V1 实现：5 个 feature（引擎/Cookie/行为模拟/CAPTCHA/CLI），77 单元测试
- V1 code review：4 blocker + 4 important 全部修复
- QA 验证：Twitter 发帖 PASS，小红书发帖 PASS
- CJK 输入 bug 修复
- stealth-browser skill 创建 + 可用性验证（显式调用 PASS，Cookie 自动注入 PASS）
- publish skill 重写（agent-browser CDP → stealth-browser）
- agent-browser 加入 suppress-plugin-skills hook，不再自动路由
- V2 PR merged：AlfredGuquan/stealth-browser#1 — 8 feature, 170 unit tests, e2e 7/7, anti-detection 57/57 [2026-04-07]
- stealth-browser skill 更新：SKILL.md 补充 V2 命令（refs/tab/wait/dialog/batch/nav/select/check）[2026-04-07]
- E2E fixture 创建 + fresh agent 验证：本地 fixture（表单/dialog/iframe/延迟元素/多页面导航）+ 独立 agent 驱动 7 个验收场景 [2026-04-07]
- 反检测独立验证：bot.sannysoft.com 57/57 PASS，V2 新增行为（ref 注入/dialog listener/多 tab）未暴露自动化信号 [2026-04-07]
- E2E 发现并修复 2 个 bug：back/forward bfcache 超时（wait_until commit）、batch get 结果丢失（formatter fallback）[2026-04-07]
- 反检测深度验证：rebrowser-bot-detector 6/6 PASS + bot.incolumitas.com 9/9 new tests OK。发现 Service Worker UA 泄漏 HeadlessChrome，用 --user-agent 启动参数修复 [2026-04-07]
