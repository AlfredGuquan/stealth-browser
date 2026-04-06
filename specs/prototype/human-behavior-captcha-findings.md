## Tracer Bullet Report: Human Behavior Simulation & CAPTCHA Vision

### 选定路径

humanization-playwright + Patchright 鼠标轨迹模拟 --> 打字行为模拟 --> OpenCV 滑块缺口检测 --> Bezier 曲线拖拽模拟

### 集成点验证结果

| 层级 | 集成点 | 状态 | 验证方式 + 关键发现 |
|------|--------|------|---------------------|
| 行为模拟层 | humanization-playwright + Patchright 鼠标轨迹 | ✅ | `uv run python tests/test_human_behavior.py` -- 195 个鼠标位置，86.5% 方向变化率证明非直线。步长 0~8.25px，方差 8.23，确认 Bezier 曲线 + Gaussian 抖动生效 |
| 行为模拟层 | 打字模拟（变速 + 空格停顿） | ✅ | 同上脚本 -- 11 字符 10.34s，间隔 std_dev=42.4ms。空格后停顿 476ms vs 平均 340ms，`humanize=True` 时自动加入 0.05~0.1s 额外延迟 |
| 视觉识别层 | OpenCV 滑块 CAPTCHA 缺口检测 | ✅ | `uv run python tests/test_captcha_vision.py` -- 模板匹配 1px 误差（confidence=0.76），边缘检测 6px 误差。4 组不同位置测试 3/4 通过（75%），失败案例 confidence=0.72 仍高于阈值但位置偏移 174px |
| 交互层 | Bezier 曲线拖拽模拟 | ✅ | `uv run python tests/test_drag_simulation.py` -- 滑块从 0px 拖拽到目标 280px，实际落点 279px（1px 误差），60 步 Bezier 路径 + Y 轴抖动 |

### 关键发现

1. **PRD 中的 `human-cursor` 库名有误。** PyPI 上的包名是 `HumanCursor`（注意大写），但它是 Selenium-only 的，不兼容 Playwright/Patchright。正确的替代方案是 `humanization-playwright`（PyPI 包名），import 路径是 `from humanization import Humanization, HumanizationConfig`。PRD 需要更新技术栈描述。

2. **`humanization-playwright` 的 `undetected_launch()` 强制 `headless=False`。** 该方法内部硬编码 `headless=False` 和 `channel="chrome"`，无法用于 headless 模式。实际使用时需要绕过 `undetected_launch()`，自己创建 Patchright browser/page 后直接构造 `Humanization(page, config)`。这是合法的用法，库源码支持。

3. **`humanization-playwright` 会写日志文件。** `__init__.py` 中 `logger.add("humanization.log", rotation="100 MB")` 会在工作目录下创建日志文件。生产环境需要在 import 后禁用或重定向这个 handler。

4. **拖拽操作不能用库的 `drag_to()` 方法。** `drag_to(source, target)` 接受两个 Locator 参数，但滑块 CAPTCHA 的目标是一个像素偏移量（从 OpenCV 检测得到），没有对应的 DOM 元素。需要手动实现：`mouse.down()` -> `generate_bezier_points()` -> 逐点 `mouse.move()` -> `mouse.up()`。库的 `generate_bezier_points()` 方法可以直接复用。

5. **模板匹配在合成数据上 75% 准确率。** 4 组测试有 1 组偏移 174px，原因是合成背景纹理在某些位置产生了 confidence 相近的假阳性（0.72 vs 正确位置 0.75）。实际小红书 CAPTCHA 的拼图块形状更独特（非正方形），模板匹配精度应该更高。但需要用真实截图验证。

6. **`move_to()` 的落点有 Bezier 随机偏移。** `move_to()` 返回的坐标不是元素中心，而是经过 Bezier 曲线 + 随机偏移后的实际落点。对于需要精确定位的操作（如拖拽起点），需要在 `move_to()` 后用 `page.mouse.move(exact_x, exact_y)` 修正到精确位置。

### 代码变更

- `tests/test_human_behavior.py`: 鼠标轨迹 + 打字模拟验证（集成点 1, 2）
- `tests/test_captcha_vision.py`: OpenCV 模板匹配 + 边缘检测验证（集成点 3）
- `tests/test_drag_simulation.py`: Bezier 拖拽模拟验证（集成点 4）
- `pyproject.toml`: 新增 humanization-playwright, opencv-python-headless, numpy 依赖

### 对后续实现的建议

1. **F3（人类行为模拟）应该封装一个 `HumanBehavior` facade 类**，内部持有 `Humanization` 实例，但 `__init__` 接受 Patchright page 而非依赖 `undetected_launch()`。这个 facade 提供 F1 引擎层需要的接口：`move_to_element()`, `type_text()`, `drag_slider()`, `scroll_page()`。

2. **CAPTCHA 拖拽应该实现为两步：** (a) OpenCV 检测缺口 x 坐标，(b) 用 `generate_bezier_points()` 生成从滑块到缺口的路径，手动逐点 `mouse.move()`。不要用 `drag_to()` 方法。拖拽路径需要人为约束 Y 轴变化量（少量抖动但不大幅偏移），模拟人类"尽量水平拖"的行为。

3. **打字模拟不需要 humanization-playwright 的 `type_at()`。** `type_at()` 的逐字符延迟基于 `characters_per_minute` 配置，但没有实现 PRD 要求的"偶发错字 + 退格修正"。这个需要自己实现。但 `type_at()` 的 click-to-focus 和基础延迟逻辑可以参考。

4. **模板匹配可靠性需要用真实 CAPTCHA 截图验证。** 建议收集 5-10 张小红书滑块截图，在这些图片上跑 `detect_gap_template_matching` 确认精度，然后再进入 F4 实现。如果模板匹配不够准确，备选方案是 Canny 边缘检测 + 轮廓面积过滤。

5. **`humanization.log` 文件需要在项目初始化时处理。** 加入 `.gitignore`，并在引擎启动时重定向 loguru handler 到项目的日志系统。
