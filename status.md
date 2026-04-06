# Status

## 目标

V2：从反检测专用工具升级为通用浏览器自动化 CLI，替代 agent-browser 成为唯一浏览器 skill。

## Blocker

## In Progress

- V2 PR 待合并：AlfredGuquan/stealth-browser#1
- 手动 e2e 验证待做：`open` → `snapshot -i` → `click @e1` → `tab create` → `batch`

## Pending

- 收集真实小红书滑块截图验证 CAPTCHA 模板匹配精度
- 更新 stealth-browser skill（SKILL.md）补充 V2 新增命令

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
