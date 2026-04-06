# Status

## Blocker

## In Progress

## Pending

- 写 stealth-browser skill，让 agent 在新 session 中可用
- 重写 publish skill 基于 stealth-browser（替换 agent-browser CDP 模式）
- 用新 session 做可用性验证（agent 只看 skill 文档能否自主完成任务）
- 收集真实小红书滑块截图验证 CAPTCHA 模板匹配精度

## Completed

- V1 实现：5 个 feature（引擎/Cookie/行为模拟/CAPTCHA/CLI），77 单元测试
- Code review：4 blocker + 4 important 全部修复
- QA 验证：Twitter 发帖 PASS，小红书发帖 PASS
- CJK 输入 bug 修复
