# Stealth Browser

面向 AI agent 的反检测浏览器自动化 CLI。

## 设计原则

AI agent 操作浏览器时，登录态、反检测、行为模拟分散在不同工具里，拼凑起来不可靠。这个项目把完整链路收进一个 CLI，围绕"可靠"做了几个设计选择。

效果是唯一评价标准。Patchright、Cookie 注入、行为模拟都是手段，能过反检测就用，不绑定技术路线。某个手段失效了就换。评价一个方案看"目标站点是否放行"，不看架构是否优雅。

零人工介入。Cookie 从系统 Chrome 自动提取，登录态自动维护，只有 session 真正过期才需要人去浏览器重新登录。中间不弹窗、不等确认、不要求手动配置。Agent 说"去小红书发帖"，工具自己搞定剩下的。

一个工具覆盖完整链路。不是"Cookie 用 A、反检测用 B、自动化用 C"的拼凑方案。一个 CLI，一个命令前缀，agent 只需要知道一个工具名。

可靠胜过通用。宁可只对几个站点有效但每个都稳定，也不做声称支持一切的"通用反检测框架"。目前验证过小红书和 Twitter，针对这两个站点做了适配和回归。

可观测。失败时能看到在哪一步、发生了什么、为什么。正常运行时零噪音。

## 技术选择

反检测用 [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)，一个 Playwright fork，在引擎源码层面打了 22 个补丁移除自动化信号。相比运行时注入方案，源码级修改不存在"注入窗口"和"注入行为本身被检测"的问题。

浏览器用系统 Chrome（`channel='chrome'`）而非 bundled Chromium。实测 bundled Chromium 在 bot 检测站点的 56 项指纹检查中有 11 项不通过，系统 Chrome 全部通过。

Cookie 通过 [pycookiecheat](https://github.com/n8henrie/pycookiecheat) 从 Chrome 本地存储提取，加密缓存，过期自动刷新。Agent 直接复用用户的真实登录态，不需要走登录流程。

交互层每个动作（点击、打字、滚动）经过行为模拟：鼠标轨迹是 Bezier 曲线带随机过冲，打字有变速和偶发错字，滚动有惯性。遇到滑块 CAPTCHA 时 OpenCV 检测缺口位置，沿拟人轨迹拖拽，最多重试两次。

后台有一个 daemon 进程通过 Unix socket 保持浏览器实例存活，CLI 每次调用复用同一个浏览器上下文，避免反复启动的开销和指纹变化。

---

## 安装

macOS only。需要 Chrome 和 Python 3.11+。

```bash
git clone https://github.com/AlfredGuquan/stealth-browser.git
cd stealth-browser
uv sync
```

## 快速开始

```bash
# 打开页面（Cookie 自动从 Chrome 提取注入）
uv run stealth-browser --site twitter open https://x.com/home

# 查看可交互元素
uv run stealth-browser --site twitter snapshot -i

# 点击、填写、截图
uv run stealth-browser --site twitter click '[data-testid="tweetButton"]'
uv run stealth-browser --site twitter fill 'input[name="text"]' "Hello world"
uv run stealth-browser --site twitter screenshot /tmp/result.png

# 关闭
uv run stealth-browser --site twitter close
```

## 命令

| 命令 | 说明 |
|------|------|
| `open <url>` | 导航（自动注入 Cookie） |
| `snapshot [-i]` | 页面快照（`-i` 列出可交互元素） |
| `click <selector>` | 点击（Bezier 鼠标轨迹） |
| `fill <selector> <text>` | 填写输入框（变速打字） |
| `type <text>` | 在当前焦点位置打字 |
| `scroll <direction> [amount]` | 惯性滚动 |
| `upload <selector> <file>` | 文件上传 |
| `screenshot [path]` | 截图 |
| `eval <js>` | 执行 JavaScript |
| `get <text\|url\|title>` | 获取页面信息 |
| `close` | 关闭浏览器和 daemon |
| `cookie refresh` | 强制重新提取 Cookie |
| `status` | 查看 daemon 状态 |

全局选项：`--headed`（可见浏览器）、`--site <name>`（Cookie 按站点隔离）、`--verbose`、`--timeout <ms>`。

## License

MIT
