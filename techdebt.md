# Tech Debt

- **CAPTCHA 旋转滑块**：PRD 提及但 V1 延后。需要真实样本评估交互模式差异（旋转 vs 水平拖拽）
- **打字错字率 3-8% vs PRD 3-12%**：代码上限低于 PRD，可能是有意保守，待观察实际效果后决定
- **Daemon PID 文件崩溃恢复**：靠 `_ensure_daemon()` 检查 stale PID 间接实现，进程号复用时可能误判。CLI 工具风险低但非零
- **加密 key 与 ciphertext 同机存放**：Fernet key 在 `~/.stealth-browser/key`，加密实际安全增益有限。考虑用 macOS Keychain
- **fill 命令对富文本编辑器不可靠**：ProseMirror/contenteditable 需要用 `eval` + `execCommand`，`fill` 命令对这类编辑器可能失败
- **页面 JS 异常冒泡无兜底**：某些站点（如 Thrifty.co.nz）的页面 JS 抛异常后被 Playwright evaluate 上下文捕获冒泡，导致 `click`/`fill`/`snapshot -i`/`wait` 全部间歇性失败（报 `function takes exactly 5 arguments (1 given)`）。engine.py 的 evaluate 调用需要 try-catch 包裹 + 自动重试 1 次，并在错误信息中区分 `[page-js-error]` 和 `[daemon-error]`
- **缺少 `press` 命令**：无法按 Escape/Enter/Tab 等功能键。关 modal、提交表单、切焦点都需要。底层 `page.keyboard.press()` 已有，缺 CLI 暴露
- **`--headed` flag 未注册**：SKILL.md 文档列了 `--headed` 作为 global flag，但 cli.py argparse 未注册该参数。调试只能靠 screenshot 盲猜
- **多表单页面 @eN ref 混乱**：页面有多套重复表单（desktop + mobile + sticky）时，@eN 交叉编号且滚动后重新 snapshot 编号会变。需要 `--viewport` 模式只返回可视区域元素，或 `--form` 模式按 `<form>` 分组
