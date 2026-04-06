# Stealth Browser — Core Principles

A browser automation CLI for AI agents that makes web interaction as reliable as shell commands, even on sites with anti-bot detection.

## Problem

AI agent 在操作网页时面临三重阻力：登录态丢失需要反复人工介入、反爬系统识别自动化特征后拦截、多个工具拼凑的碎片化体验。结果是浏览器操作成了 agent 工具链中最不可靠的一环——agent 不敢接需要登录的任务，用户不敢放手让 agent 自主完成。

## Principles

### 1. 效果第一

不被检测到就行。Patchright、Cookie 注入、人类行为模拟都只是手段，能过就用，不绑定特定技术路线。评价标准是"目标站点是否通过"，不是"架构是否优雅"。

### 2. 零介入全流程

Cookie 从真实 Chrome 自动提取，登录态自动维护。只有 session 真正过期才需要人。中间不弹窗、不等确认、不要求手动配置。Agent 说"去小红书发帖"，工具自己搞定剩下的。

### 3. 一个工具，完整链路

从 Cookie 复用到反检测到人类行为模拟，一个 CLI 全包。不是"反爬用 A、Cookie 用 B、自动化用 C"的拼凑。Agent 只需要知道一个命令。

### 4. 可靠胜过通用

宁可只对 5 个站点有效但每个都稳定，也不要声称支持 100 个但各种不稳定。针对具体站点做验证和适配，不追求抽象的"通用反检测框架"。

### 5. 可观测

失败时能看到发生了什么、为什么失败、工具在做什么。但日常使用零配置、零噪音。

## Anti-Vision

- **不做配置地狱** — 不需要用户每次想"该加什么 flag"
- **不做易耗品** — 不是今天能用明天就坏的脆弱方案
- **不做黑盒子** — 出问题时可诊断
- **不做过度抽象** — 不为"通用性"牺牲对具体站点的效果

## Success

- 社交媒体发布全自动（小红书、Twitter）
- 数据采集无阻力
- 不再惧怕登录态问题
- 浏览器操作与 CLI 操作同级可靠
