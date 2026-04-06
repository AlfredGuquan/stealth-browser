# Status

## 目标

V2：从反检测专用工具升级为通用浏览器自动化 CLI，替代 agent-browser 成为唯一浏览器 skill。

## Blocker

## In Progress

## Pending

- 收集真实小红书滑块截图验证 CAPTCHA 模板匹配精度

## Backlog — V2 通用化

### P0 — 没有就不能替代 agent-browser

- [ ] Snapshot refs 系统（`@e1` `@e2` 引用，交互用 `click @e3` 而非完整 selector）
- [ ] Wait 条件（element / text / network-idle / milliseconds）
- [ ] Dialog 处理（`dialog accept/dismiss`，防 alert 卡死 session）

### P1 — 通用场景高频需要

- [ ] Back / Forward / Reload 导航原语
- [ ] Select / Check（下拉框、checkbox）
- [ ] 多 Tab 管理（create / switch / close / list）
- [ ] iframe 支持（snapshot 内联 iframe 内容）

### P2 — 效率提升

- [ ] Batch 模式（JSON pipe 批量命令）
- [ ] 网络请求读取（`network requests`，检查 API 响应）
- [ ] Session 命名（同站多 session 支持）

### P3 — 完整性补全

- [ ] 设备模拟（viewport / device 切换）
- [ ] PDF 导出
- [ ] Proxy 支持
- [ ] 视频录制 / Profiling / Diff

## Backlog — V1 遗留

- publish skill 端到端验证（用 /publish 发一篇真实帖子确认 stealth-browser 集成可用）

## Completed

- V1 实现：5 个 feature（引擎/Cookie/行为模拟/CAPTCHA/CLI），77 单元测试
- Code review：4 blocker + 4 important 全部修复
- QA 验证：Twitter 发帖 PASS，小红书发帖 PASS
- CJK 输入 bug 修复
- stealth-browser skill 创建 + 可用性验证（显式调用 PASS，Cookie 自动注入 PASS）
- publish skill 重写（agent-browser CDP → stealth-browser）
