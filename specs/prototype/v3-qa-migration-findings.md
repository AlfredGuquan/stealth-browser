# V3 QA Migration — Tracer Bullet Findings

Validates 3 integration points for V3 (F14/F15/F16) before Phase 3 worker implementation.

Experiment scripts: `scripts/tracer_f14_localhost.py`, `scripts/tracer_f15_wait_url.py`, `scripts/tracer_f16_annotate.py`, `scripts/tracer_f16_fullpage.py`. Run with `uv run python scripts/<file>.py`.

---

## F14 — Localhost Cookie/Login 跳过

### 验证结果

| 子点 | 状态 | 证据 |
|---|---|---|
| pycookiecheat 对 localhost 的行为 | ✅ 优雅返回空 list | `get_cookies("http://localhost:3000", browser=CHROME, as_cookies=True)` → `type=list len=0`，不抛异常。`127.0.0.1`、`example.local` 行为相同。 |
| hostname 分类函数 | ✅ 14/14 cases pass | localhost / 127.0.0.1 / [::1] / 0.0.0.0 / *.local 命中；192.168 / 10.x / 172.16-31 / 公网域名不命中 |

### 决定：gating 放在哪一层

pycookiecheat 不抛异常，所以**理论上**可以放在 cookies.py 的「拿到空 list 就跳过注入」分支。但 PRD F14 明确要求：「跳过 cookie 注入的同时**也要跳过 login_redirect 检测**」。login_redirect 检测在 `engine.navigate()` 内（不在 cookies.py），所以单纯靠 cookies.py 返回空无法满足验收标准 2（"open http://localhost:3000/login 不报 session expired"）。

**推荐实现位置**：在 `cli.py` 的 `cmd_open` 里在调 daemon 之前判断 hostname，命中本地或 `--no-cookie` flag 时给 daemon `open` 命令多传一个 `skip_cookies: True`。daemon 的 `handle("open")` 把这个 flag 透传给 `engine.navigate(url, skip_cookies=...)`，engine 内同时跳过 cookie 注入和 login_redirect 检测。site 推断也跟着跳过。

`cookies.py` 不需要改动——`engine.navigate` 决定要不要调用 cookies API，cookies 模块本身保持纯函数。

### 最小代码模板

```python
# stealth_browser/utils.py 或新文件
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

def is_local_dev_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".local")
```

```python
# cli.py cmd_open
skip = args.no_cookie or is_local_dev_url(args.url)
send_command(session, "open", url=args.url, skip_cookies=skip, ...)
```

```python
# engine.py navigate(...)
if not skip_cookies:
    site = self._infer_site(url)
    await self.inject_cookies(site, url)
# ... goto ...
if not skip_cookies and self._looks_like_login_redirect(self.page.url):
    raise SessionExpired(...)
```

### 注意事项

- pycookiecheat 在 `localhost` 上确实不抛——所以 `cookies.py` 的 catch 分支**不需要**为 F14 增改任何 except，cookies 模块零变更
- 内网 IP（192.168.x、10.x、172.16-31.x）已确认 _不_ 命中 localhost rule（验证组 14/14 包含这些反例）
- `--no-cookie` 全局 flag 走相同的 `skip_cookies=True` 分支，避免代码重复

---

## F15 — Wait URL Pattern (glob)

### 验证结果

| 子点 | 状态 | 证据 |
|---|---|---|
| 已在目标 URL 时立即返回 | ✅ | `wait_for_url("**example.com**")` 在已经 navigate 到 `https://example.com/` 后 **10.6 ms** 返回 |
| 跨域跳转匹配 | ✅ | `goto(iana.org)` + 并行 `wait_for_url("**iana.org**")` → 7234.8 ms 后命中 |
| 完整 URL glob (`https://**.iana.org/**`) | ✅ | 5.8 ms 立即匹配 |
| 路径 glob (`**/help/**`) | ✅ | 970 ms 命中 `https://www.iana.org/help/example-domains` |
| 不匹配时超时 | ✅ raise `TimeoutError` | `wait_for_url("**/never-matches-this", timeout=1500)` → 1508.9 ms 后 raise，msg `"Timeout 1500ms exceeded."` |
| 严格匹配 (`**/index.html` 对 `/`) | ✅ 不会匹配 | 证明 glob 是 URL 字面量匹配，不会自动补 index — 与 agent-browser 语义对齐 |

### 决定

Patchright 的 `page.wait_for_url(pattern, timeout)` 直接覆盖 PRD 验收标准全部 4 条。glob 行为符合 agent-browser `wait --url` 用户预期。不需要自己写 polling loop。

### Daemon 命令最小代码

```python
# daemon.py: 在 wait dispatch 内增加一个分支
elif wait_type == "url":
    msg = await self.engine.wait_for_url_pattern(
        body["target"], timeout=timeout
    )
```

```python
# engine.py
async def wait_for_url_pattern(self, pattern: str, *, timeout: int = 30000) -> str:
    if self.page is None:
        raise RuntimeError("browser not launched")
    try:
        await self.page.wait_for_url(pattern, timeout=timeout)
    except Exception as e:
        # PlaywrightTimeoutError -> 让 daemon 透传成 status=error
        raise TimeoutError(f"timeout waiting for url pattern: {pattern}") from e
    return self.page.url
```

CLI 侧：在 `cmd_wait` 的 subparser 加 `url` 子命令，把 pattern 当 `target` 透传，daemon body 设 `type="url"`。

### 注意事项

- Playwright glob 用 `**` 通配多段、`*` 通配单段；`?` 是单字符，不是 regex。pattern 是 URL 字面量匹配，**不**会做 URL normalization（trailing slash、case 都敏感）
- timeout 走全局 `--timeout`（默认 30s），跟其他 wait 子命令一致
- 失败时 stderr 输出 "timeout waiting for url pattern: …" + exit 1

---

## F16 — Screenshot Annotate (坐标 + Pillow 叠加)

### 验证结果

| 实验 | 状态 | 关键发现 |
|---|---|---|
| A: viewport 1280x720, DPR=1, scroll=0 | ✅ | PNG=(1280,720), bbox 与 PNG 像素 1:1 |
| B: viewport 1280x720, DPR=2 (retina) | ✅ | PNG=(2560,1440), bbox **保持 CSS 像素**（不随 DPR 缩放）→ 必须乘 dpr |
| C: viewport screenshot + scrolled to y=1200 | ✅ | bbox 是 **viewport-relative** — `#far` 文档 y=1877，scroll=1200 后 bbox.y=677 (= 1877-1200) |
| D: full_page=True screenshot | ✅ | PNG=(1280,1778) 整个文档高度，但 bbox 仍是 viewport-relative — scrollY=800 时 `#top.bbox.y=-760` |
| E: Pillow overlay 视觉验证 | ✅ | 在 `scripts/_tracer_f16_out/fullpage_overlay.png` 中 [1] 落在 TOP 元素上、[2] 落在 FAR 元素上 — 视觉确认坐标公式正确 |
| F: ref 复用路径 | ✅ | `engine.py:69` `self._ref_map: dict[str, dict[str, Any]] = {}`；`_resolve_selector()`(line 285) 已支持把 `@eN` 转 `[data-ref="@eN"]` selector — annotate handler 直接复用 `_ref_map` 拿 ref，复用 `_resolve_selector + _get_locator` 拿 Locator → `bounding_box()` |

### 关键约束（worker 必读）

1. **现有 `engine.screenshot()` 用 `full_page=True`**（line 526）。full_page PNG 跨整个文档高度，但 `bounding_box()` 返回 **viewport-relative** 坐标 — 直接画会落在错误位置。

2. **正确的坐标公式**（DPR + scroll 都要考虑）：
   ```
   pixel_x = (bbox.x + scrollX) * dpr
   pixel_y = (bbox.y + scrollY) * dpr
   ```

3. **最简可靠策略：截图前 scroll 到 (0, 0)**。这样 scrollX=scrollY=0，公式塌缩成 `(bbox.x * dpr, bbox.y * dpr)`，不需要任何同步状态读取。截图后可以 restore 原 scroll。这是 F16 推荐路径。

4. **PNG 尺寸 ≠ viewport 尺寸**。dpr 必须从 PNG 尺寸 / viewport 尺寸算出来，**不要硬编码**。retina 下 viewport 1280×720 → PNG 2560×1440。stealth-browser 默认 viewport 1920×1080，配 channel='chrome'，DPR 取决于运行机器；用 PNG 实测是最稳的。

5. **viewport 之外的元素**：scroll=0 + full_page 时，bbox.y 可能 > viewport_height（仍在文档内、可见）。这些元素**仍要画 label**，因为 full_page screenshot 包含它们。判断条件是 `bbox.y + bbox.height < png_height_in_css_px` 而不是 `< viewport_height`。

6. **iframe 内的 ref**：`_ref_map[ref]["frame_index"] != 0` 时要走 `_get_locator(ref)` 拿 frame locator。`bounding_box()` 在 iframe locator 上**自动转换到 main page 坐标系**（Playwright 文档承诺）—— 无需手工偏移 iframe origin。

### Pillow 模板（已验证可用，跑过 `scripts/tracer_f16_fullpage.py`）

```python
# stealth_browser/annotate.py (新文件)
import io
from PIL import Image, ImageDraw, ImageFont

_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

def overlay_labels(
    png_bytes: bytes,
    boxes: list[dict],   # [{ref: "@e1", bbox: {x,y,w,h}, tag, text}, ...]
    *,
    viewport_css_width: int,
) -> bytes:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    dpr = img.size[0] / viewport_css_width  # robust DPR detection
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype(_FONT_PATH, int(18 * dpr))
    except Exception:
        font = ImageFont.load_default()

    for i, b in enumerate(boxes, start=1):
        bb = b["bbox"]
        x, y = bb["x"] * dpr, bb["y"] * dpr
        w, h = bb["width"] * dpr, bb["height"] * dpr
        draw.rectangle([x, y, x + w, y + h],
                       outline=(255, 200, 0, 255), width=max(2, int(2 * dpr)))
        label = f"[{i}]"
        l, t, r, btm = draw.textbbox((0, 0), label, font=font)
        tw, th = r - l, btm - t
        pad = int(4 * dpr)
        # Place label just above the element if room, otherwise top-left inside
        ly = y - th - 2 * pad if y > th + 2 * pad else y
        draw.rectangle([x, ly, x + tw + 2 * pad, ly + th + 2 * pad],
                       fill=(255, 230, 0, 230))
        draw.text((x + pad, ly + pad - 2), label,
                  fill=(0, 0, 0, 255), font=font)

    out = io.BytesIO()
    Image.alpha_composite(img, overlay).save(out, "PNG")
    return out.getvalue()
```

### Daemon handler 草图

```python
# daemon.py 内 screenshot 分支
elif command == "screenshot":
    annotate = body.get("annotate", False)
    if annotate:
        result = await self.engine.screenshot_annotated(body.get("path"))
        # result = {path, legend: [{ref, tag, text}, ...]}
        return {"status": "ok", **result}
    path = await self.engine.screenshot(body.get("path"))
    return {"status": "ok", "path": path}
```

```python
# engine.py
async def screenshot_annotated(self, path: str | None = None) -> dict:
    if not self._ref_map:
        raise RuntimeError("no refs cached, run snapshot -i first")

    # Save scroll, scroll to (0,0) for clean coordinate mapping
    saved = await self.page.evaluate("[window.scrollX, window.scrollY]")
    await self.page.evaluate("window.scrollTo(0, 0)")
    try:
        png_bytes = await self.page.screenshot(full_page=True)
        viewport_w = self.page.viewport_size["width"]

        boxes = []
        for ref, info in self._ref_map.items():
            try:
                locator = await self._get_locator(ref)
                bb = await locator.bounding_box()
            except Exception:
                continue
            if bb is None:
                continue
            boxes.append({
                "ref": ref, "bbox": bb,
                "tag": info["tag"], "text": info["text"],
            })

        from .annotate import overlay_labels
        out_bytes = overlay_labels(png_bytes, boxes, viewport_css_width=viewport_w)
    finally:
        await self.page.evaluate(f"window.scrollTo({saved[0]}, {saved[1]})")

    if path is None:
        import tempfile
        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        f.close()
        path = f.name
    Path(path).write_bytes(out_bytes)

    legend = [
        {"ref": b["ref"], "tag": b["tag"], "text": b["text"]}
        for b in boxes
    ]
    return {"path": path, "legend": legend}
```

CLI 侧：`cmd_screenshot` 输出第一行 `path`，后续行 `[N] @eN <tag> "text"`。

### 边界与已知坑

- **不需要**改 `data-ref` 注入逻辑——`_ref_map` 已经包含 frame_index、tag、text，annotate 只读不写
- **scroll-restore** 必须在 try/finally 里，避免 screenshot 异常时永久跳页
- 元素 hidden / display:none → `bounding_box()` 返回 `None`（实测过），代码里 `continue` 跳过
- **不**修改页面 DOM（满足 PRD 约束「不通过 page.evaluate 注入 overlay」）— Pillow 在 PNG 上画，DOM 完全不动
- 字体 fallback：`Arial Bold.ttf` 在 macOS 上一定存在，没必要做更多 fallback
- 视觉效果上，label 当前会"压"在元素文字上。如果 worker 想完美一点，把 label 放在元素**上方** `ly = y - th - 2*pad`，模板里已经写成「元素顶部有空间就放上方，否则放内部左上角」

---

## 总体结论

| Feature | 可行性 | 主要风险 | 备注 |
|---|---|---|---|
| F14 | ✅ | 无 | gating 必须放 cli + engine（不能只放 cookies.py），login_redirect 检测必须同步跳过 |
| F15 | ✅ | 无 | Patchright 原生支持，daemon 一个 dispatch 分支 + engine 一个 wrapper 即可 |
| F16 | ✅ | 中（坐标公式易写错） | 必须 scroll-to-0 + DPR 从 PNG/viewport 算、不要 viewport-relative 直接画。Pillow 模板已视觉验证 |

无任何阻塞性问题。Phase 3 worker 可直接基于本文档 + 4 个 tracer 脚本展开实现。

---

## Tracer 实验文件清单

- `scripts/tracer_f14_localhost.py` — pycookiecheat 行为 + hostname 分类
- `scripts/tracer_f15_wait_url.py` — wait_for_url glob 6 个 case
- `scripts/tracer_f16_annotate.py` — bbox vs PNG 在 3 种 viewport 状态
- `scripts/tracer_f16_fullpage.py` — full_page screenshot + 视觉验证 overlay
- `scripts/_tracer_f16_out/` — 4 张验证截图
