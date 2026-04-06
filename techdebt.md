# Tech Debt

- **CAPTCHA 旋转滑块**：PRD 提及但 V1 延后。需要真实样本评估交互模式差异（旋转 vs 水平拖拽）
- **打字错字率 3-8% vs PRD 3-12%**：代码上限低于 PRD，可能是有意保守，待观察实际效果后决定
- **Daemon PID 文件崩溃恢复**：靠 `_ensure_daemon()` 检查 stale PID 间接实现，进程号复用时可能误判。CLI 工具风险低但非零
- **加密 key 与 ciphertext 同机存放**：Fernet key 在 `~/.stealth-browser/key`，加密实际安全增益有限。考虑用 macOS Keychain
- **fill 命令对富文本编辑器不可靠**：ProseMirror/contenteditable 需要用 `eval` + `execCommand`，`fill` 命令对这类编辑器可能失败
