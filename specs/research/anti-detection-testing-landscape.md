# 反自动化检测工具与站点全景

研究日期：2026-04-07

---

## 概述

本报告覆盖现有在线检测站点、Playwright/Patchright 专项检测、商业反爬服务维度、开源可本地化方案，以及 Patchright 的覆盖边界。目标是识别 bot.sannysoft.com 57/57 PASS 之外的严格检测盲区。

---

## 一、在线检测站点

### bot.sannysoft.com（现状基线）
- URL: https://bot.sannysoft.com
- 检测维度：navigator.webdriver、UA、plugins、canvas、WebGL、languages 等约 57 项静态指纹
- 判定标准：逐项 PASS/FAIL，纯静态属性检查
- 对 Patchright + system Chrome 的预期表现：57/57 PASS（已验证）
- 评价：检测项偏 2019 年以前，缺行为分析和 CDP 痕迹检测，**不再足以作为唯一基准**

### bot.incolumitas.com
- URL: https://bot.incolumitas.com
- 检测维度：
  - 行为分类（30+ 分类器，采集 1.5-15 秒鼠标/键盘行为，评分 0-1）
  - TCP/IP + TLS 指纹、HTTP 头分析
  - Canvas/WebGL/Audio 指纹
  - Web Worker 和 Service Worker 内 navigator 一致性（跨线程比对）
  - FingerprintJS 访客 ID
  - IP 数据中心检测（AWS/Azure/GCP）
- 判定标准：行为分 + 静态指纹综合评分，无二值结论
- 可本地化：否（服务端行为分析）
- 对 Patchright + system Chrome 预期：静态项通过，**行为分取决于实际鼠标/键盘操作是否经过 humanization**；system Chrome 在 TLS 层面通过

### pixelscan.net
- URL: https://pixelscan.net/bot-check
- 检测维度：WebGL、Canvas、AudioContext、Touch API、屏幕分辨率、时区一致性、指纹一致性（跨属性比对）
- 判定标准：检测指纹内部一致性，任何属性矛盾即标记异常
- 可本地化：否
- 对 Patchright + system Chrome 预期：**关键在一致性**——system Chrome 真实 GPU 渲染，Canvas/WebGL 应通过；若有任何属性被 patch 覆盖但与真实值不一致则失败

### browserscan.net
- URL: https://www.browserscan.net/bot-detection
- 检测维度：50+ 属性（Canvas、WebGL、WebRTC、DNS 泄漏、Audio、HTTP 头不一致、navigator 属性）
- 判定标准：检测 headless 特征、自动化框架标记、spoofed 环境
- 可本地化：否
- 对 Patchright + system Chrome 预期：应通过，system Chrome 非 headless，无 Playwright 默认 UA

### creepjs（GitHub Pages）
- URL: https://abrahamjuliot.github.io/creepjs/
- 检测维度：**检测 prototype 篡改**——专门识别 anti-fingerprinting 工具修改 browser API 默认行为留下的痕迹，例如 puppeteer-extra-plugin-stealth 修改的属性
- 判定标准：计算"信任度"评分，prototype lie 越多评分越低；不仅报告指纹，还报告指纹是否被伪造
- 可本地化：**是**——源码在 GitHub (abrahamjuliot/creepjs)，MIT，可自部署
- 对 Patchright + system Chrome 预期：Patchright 通过修改 Chrome flag 而非 JS 注入修改 API，**比 stealth 插件方式更不易被 creepjs 检测到 prototype lie**；Patchright 官方 README 声称通过 creepjs

### rebrowser-bot-detector
- URL: https://bot-detector.rebrowser.net/（在线测试）；源码：https://github.com/rebrowser/rebrowser-bot-detector
- 检测维度（10 项，专门针对 Playwright/Puppeteer）：
  1. `runtimeEnableLeak`：检测 Runtime.enable CDP 方法使用痕迹
  2. `sourceUrlLeak`：Puppeteer 在脚本中自动添加的 source URL
  3. `mainWorldExecution`：脚本是否在 isolated context 而非 main world 执行
  4. `navigatorWebdriver`：navigator.webdriver 属性
  5. `bypassCsp`：page.setBypassCSP(true) 使用痕迹
  6. `viewport`：非标准分辨率（Playwright 默认 1280x720）
  7. `window.dummyFn`：isolated context 是否能访问 main world 对象
  8. `useragent`："Chrome for Testing" UA 字符串
  9. `pwInitScripts`：Playwright 注入的 `__pwInitScripts` 全局变量
  10. `exposeFunctionLeak`：page.exposeFunction() 的 JS binding 痕迹
- 可本地化：**是**——MIT 开源，可自部署
- 对 Patchright + system Chrome 预期：
  - runtimeEnableLeak：**Patchright 已 patch**（改用 isolated ExecutionContext）
  - navigatorWebdriver：**已 patch**（--disable-blink-features=AutomationControlled）
  - useragent：**已 patch**（system Chrome UA，非 "Chrome for Testing"）
  - pwInitScripts：**需验证**，Patchright 可能仍注入 __pwInitScripts
  - exposeFunctionLeak：**需验证**，取决于 daemon 是否用 exposeFunction()

---

## 二、Playwright/Patchright 专项检测

rebrowser-bot-detector 是目前最针对 Playwright 的开源检测工具，10 项测试覆盖了 Playwright 独有的运行时特征（__pwInitScripts、source URL、Runtime.enable）而非通用的 headless 特征。

Patchright 的 patch 列表：
- 避免 Runtime.enable（改用 isolated ExecutionContext）
- 禁用 Console API（防 Console.enable 检测）
- 修改 Chrome 启动 flag 6 项（见上文）
- 支持 closed shadow root 交互

**Patchright 明确不覆盖的维度：**
- `__pwInitScripts` 全局变量注入（rebrowser-bot-detector 第 9 项）
- `exposeFunctionLeak`（若 daemon 调用了 page.exposeFunction）
- Init script 注入的**时序攻击**（文档承认理论漏洞）
- Firefox/WebKit 浏览器支持

---

## 三、商业反爬服务检测维度

### Cloudflare Bot Management
- **TLS 指纹（JA3/JA4）**：检查 TLS 握手中的 cipher suite 顺序、扩展，system Chrome 应产生真实 Chrome JA3，可通过
- **HTTP/2 Akamai 指纹**：header 顺序、SETTINGS frame、WINDOW_UPDATE 参数；system Chrome 产生真实 HTTP/2 指纹
- **行为分析**：鼠标轨迹、加速度、微动作；Patchright 本身不提供，需依赖 humanization-playwright
- **机器学习模型**：基于 26M 网站流量训练的异常检测
- 对 Patchright + system Chrome 预期：TLS/HTTP2 层通过（真实 Chrome），行为层取决于 humanization 质量

### Akamai Bot Manager
- JA4 指纹（比 JA3 更难绕过，已升级）
- 行为时序分析（反应时间、滚动模式）
- JavaScript sensor 收集：WebGL、Canvas、Audio context、字体列表、插件、分辨率
- 对 Patchright + system Chrome 预期：fingerprint 层通过，行为层同上

### HUMAN（前 PerimeterX）
- TLS + IP + JavaScript 客户端三维指纹
- JS sensor：WebGL、Canvas、Audio、字体、插件、分辨率
- 鼠标轨迹分析（直线移动为 bot 信号）
- 对 Patchright + system Chrome 预期：静态指纹通过，行为层是核心风险点

**结论：商业反爬的核心区分维度是 TLS/HTTP2 指纹 + 行为时序分析。System Chrome 解决了前者，humanization-playwright 覆盖后者，但 humanization 的质量（轨迹自然度）是关键变量。**

---

## 四、开源可本地化检测库

| 工具 | 仓库 | License | 可本地化 | 主要检测维度 |
|------|------|---------|---------|------------|
| rebrowser-bot-detector | github.com/rebrowser/rebrowser-bot-detector | MIT | 是 | Playwright/Puppeteer 专项 10 项 |
| creepjs | github.com/abrahamjuliot/creepjs | MIT | 是 | prototype 篡改检测、指纹一致性 |
| fingerprintjs/BotD | github.com/fingerprintjs/BotD | MIT | 是 | 客户端自动化框架检测，无需服务端 |
| fingerproxy | github.com/wi1dcard/fingerproxy | MIT | 是 | JA3/JA4/Akamai HTTP2 指纹代理（需拦截流量） |

BotD 特点：纯客户端，无服务端依赖，MIT 无限制，最易本地集成。

---

## 五、已知空白

1. **pwInitScripts 是否被 Patchright 清除**：需要实际运行 rebrowser-bot-detector 验证第 9 项
2. **exposeFunctionLeak**：我们的 daemon 是否调用了 page.exposeFunction() 需要审查代码
3. **Cloudflare Turnstile 具体评分逻辑**：行为维度权重未公开
4. **humanization-playwright 实际行为评分**：未在 incolumitas 行为分类器上测试过

---

Sources:
- [rebrowser-bot-detector](https://github.com/rebrowser/rebrowser-bot-detector)
- [Patchright Python](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python)
- [bot.incolumitas.com](https://bot.incolumitas.com/)
- [pixelscan.net](https://pixelscan.net/bot-check)
- [browserscan.net](https://www.browserscan.net/bot-detection)
- [creepjs](https://github.com/abrahamjuliot/creepjs)
- [fingerprintjs/BotD](https://github.com/fingerprintjs/BotD)
- [fingerproxy](https://github.com/wi1dcard/fingerproxy)
- [patchright anti-detect comparison](https://github.com/pim97/anti-detect-browser-tools-tech-comparison/blob/master/patchright.md)
- [How to Scrape with Patchright - ZenRows](https://www.zenrows.com/blog/patchright)
- [Bypassing PerimeterX and Akamai - ProxyCove](https://proxycove.com/en/blog/bypass-perimeterx-akamai-detection)
