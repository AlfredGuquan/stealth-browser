# Architecture

反检测浏览器自动化 CLI：Cookie 自动提取 → Patchright 隐身浏览器 → 人类行为模拟 → 站点交互。

## 数据流

### CLI 命令执行

```
CLI (cli.py) → Unix socket → Daemon (daemon.py) → Engine (engine.py) → Patchright → Chrome
```

CLI 是无状态薄客户端，每次调用通过 Unix domain socket 发 HTTP 请求给 daemon。daemon 持有 Patchright 浏览器实例，跨命令保活。

### Cookie 生命周期

```
Chrome SQLite DB → pycookiecheat 解密 (cookies.py) → Fernet 加密缓存 (~/.stealth-browser/sessions/) → Patchright context.add_cookies()
```

首次访问站点时自动提取。24h TTL 后重新提取。检测到登录页跳转时清缓存重试。

### 人类行为管线

```
CLI click/fill/scroll → Engine → HumanBehavior facade (behavior.py) → humanization-playwright (Bezier 曲线) → Patchright Page API
```

所有交互命令经过 HumanBehavior 包装，注入鼠标轨迹、打字延迟、滚动惯性。

## 模块地图

### `stealth_browser/` — 核心库

| 文件 | 职责 | 外部依赖 |
|------|------|---------|
| cli.py | argparse 命令路由，Unix socket 客户端 | — |
| daemon.py | asyncio 双 fork 守护进程，HTTP-over-Unix-socket server | — |
| engine.py | Patchright 浏览器生命周期，导航/交互/截图 | patchright |
| cookies.py | Chrome Cookie 提取、格式转换、加密缓存 | pycookiecheat, cryptography |
| behavior.py | 鼠标/打字/滚动/拖拽的人类行为 facade | humanization-playwright |
| captcha.py | 滑块 CAPTCHA 检测 + OpenCV 缺口定位 + 拖拽 | opencv-python-headless, numpy |
| utils.py | 路径管理、Chrome 版本检测、错误输出 | — |

### `tests/unit/` — 单元测试

Mock-based，不需要真实浏览器。覆盖所有模块。

### `tests/test_*.py` — Tracer 验证脚本

需要真实 Chrome 和网络。验证反检测效果、Cookie 提取、端到端流程。

## 层级规则

```
cli.py → daemon.py → engine.py → { cookies.py, behavior.py, captcha.py }
                                          ↑
                                      utils.py（所有模块可引用）
```

- cli.py 只和 daemon.py 通信（通过 socket），不直接导入 engine/cookies/behavior
- daemon.py 是唯一持有 engine 实例的模块
- behavior.py 和 captcha.py 不互相导入，由 engine.py 协调

## 架构不变量

- **不用 bundled Chromium** — 必须用系统 Chrome（`channel='chrome'`），反检测效果差距 11 项
- **不用 sync API** — Patchright greenlet 不能跨线程，daemon 必须全 async
- **不用 MCP 协议** — CLI 纯文本 I/O，零协议开销

## 跨切面

### Cookie 安全

Session 文件用 Fernet 对称加密。密钥来源优先级：`AGENT_BROWSER_ENCRYPTION_KEY` 环境变量 > 自动生成存储在 `~/.stealth-browser/key`。site 名经 `_validate_name()` 清洗防路径遍历。

### 进程管理

Daemon 通过双 fork 脱离终端。PID 文件 `~/.stealth-browser/{session}.pid`。SIGTERM/SIGINT 优雅关闭（`loop.stop()`）。30 分钟空闲自动退出。
