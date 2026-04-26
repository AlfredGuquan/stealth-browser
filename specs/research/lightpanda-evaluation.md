# Lightpanda 评估

> 触发：Chris Tate（X @slatedev）的帖子讨论 agent-browser + Lightpanda + webreel 组合，调研其是否适合替代 Patchright。
> 结论：**不能替代**，定位正交。stealth-browser 继续用 Patchright。

## 1. Lightpanda 是什么

为机器写的无头浏览器，Zig 从零实现。官方定位："fast, lightweight browser engine for automation, crawling and AI agents."

**核心取舍**：砍掉图形渲染层
- 不跑 CSS layout、不渲染图像、不用 GPU 合成、没有 Canvas / WebGL
- 保留 JS（走 V8）和 DOM，动态页面能跑
- 兼容 CDP，Puppeteer/Playwright 代码改三行 endpoint 就能接

**性能（官方 benchmark）**
- ~9× 快于 Chrome headless（5s vs 46s 完成同一页面）
- ~16× 更省内存（123MB vs 2GB）
- HN 讨论帖有复现数据

**状态**：Beta，覆盖度还在补，许多页面会崩。

## 2. 和 Patchright 的本质差异

| 维度 | Patchright | Lightpanda |
|---|---|---|
| 目标 | 让 Playwright 驱动的 Chrome 看起来像真人 | 让机器用最少资源爬最多页面 |
| 底层 | 真实 Chrome + 补丁 | 全新浏览器（非 Chromium） |
| 解决的问题 | CDP 泄露、`navigator.webdriver`、Runtime.enable 可探测 | 资源消耗、冷启动、并发密度 |
| 对抗 Cloudflare/DataDome | 部分有效（从 100% 检出降到 ~67%） | **无能力**，比 headless Chrome 还惨 |
| 成熟度 | 稳定，drop-in 替换 | Beta |

**关键洞察**：两者不在一个维度。Patchright 解决"**看起来像人**"，Lightpanda 解决"**不像人也没关系，我够快**"。

## 3. 问题回答

### Q1: 用 Lightpanda 还需要 Patchright 这类补丁吗？

**不需要、也用不了。**

- Patchright 修的是 Playwright/Chrome 组合里的具体泄露点（Runtime.enable、webdriver flag、headless UA、某些 CDP 命令的副作用）。这些漏洞**只存在于 Chrome**。
- Lightpanda 不是 Chrome，上述泄露根本没有——但**也没有 Chrome 的指纹基底**。它不是"伪装的 Chrome"，它是"一个明显不是 Chrome 的东西"。
- 目前 Lightpanda 生态**没有**对应的 stealth 补丁层，也没有能让它伪装成普通浏览器的方案。

### Q2: Lightpanda 怎么解决被站点视为爬虫？

**它没解决，也没打算解决。**"当前能过一些检测"是 obscurity advantage（小众副作用），不是技术能力。

**事实核查（一手 + 二手源，结论一致）**

| 源 | 结论 |
|---|---|
| 官方 README | 零提 stealth / anti-detection / fingerprint |
| 官方 docs | 零提 stealth，只提 `--obey-robots`（让你**遵守**爬虫礼仪，不是绕过） |
| 官方博客 `CDP Under the Hood` | 在吐槽 CDP 架构缺陷，不涉及反检测 |
| DataDome（反爬厂商） | 有专门页面 `/anti-detect-tools/lightpanda/` 把 Lightpanda 作为已识别的 anti-detect 工具分类 |
| Supacrawler（用 Lightpanda 做后端的 Go 爬虫） | 实现里的 stealth 模式**被禁用了**，原话："LightPanda's obscurity already provides some natural bot avoidance" |

最后一条是正在使用 Lightpanda 做爬虫的项目自己的话。翻译：现在不被抓的唯一原因是**没人专门给它写检测规则**。

**Obscurity advantage 的脆弱性**

| 维度 | 状态 |
|---|---|
| 积极面 | 弱检测站点、老式 WAF 的规则库里没 Lightpanda 签名，默认通过 |
| 脆弱性 | DataDome 已经把它编入分类库（页面存在本身就是信号），CF / FingerprintJS 跟上只是时间问题 |
| 指纹空洞 | 真到对抗 fingerprint 那一天，它比 headless Chrome **更容易抓**——Canvas / WebGL / 字体 / 真实 screen 维度**根本拿不出值**，一查全是 `undefined` 或 0，比 Chrome headless 的小泄露更显眼 |

**结论**：押 Lightpanda 的反检测能力等于押"对手没升级规则"。这是一个会失效的窗口，不是稳定资产。

Lightpanda 适合的场景：
1. 自己的网站 / 自己可控的系统
2. API-like 页面（JSON、半结构化 HTML）
3. 对爬虫友好或压根不检测的站点
4. 大规模批量跑、在意机器成本

### Q3: 常见误读——"CDP 模式"≠ 反检测

一个会反复踩的坑：看到 Lightpanda 支持 "CDP" 容易误以为等同"Chrome 兼容"或"Chrome 伪装"。不是。

- **CDP = Chrome DevTools Protocol**，是一个 websocket + JSON-RPC 的**通信协议**，原本给 Chrome 调试器用
- Lightpanda 实现了 CDP server（`./lightpanda serve --port 9222`），意思是 Puppeteer / Playwright 的**客户端**能连进来，用原本的 API
- 这是**协议层兼容**，相当于某个数据库说"我支持 PostgreSQL wire protocol"——协议能通，不代表它就是 PostgreSQL
- CDP 只管"外部怎么发指令进来"，不管"页面上的 JS 看到的 navigator 长什么样"——反检测是后者的事

官方博客 `CDP Under the Hood` 做的事恰恰相反：在**吐槽 CDP 本身的设计缺陷**（"not designed for automation"），他们在想怎么**绕过 CDP 的问题**，不是用 CDP 来伪装 Chrome。

## 4. 对 stealth-browser 的影响

**不替换 Patchright。** stealth-browser 的使命域（小红书、Twitter 这类登录 + 强检测社交站点）正好是 Lightpanda 最弱的场景。Patchright + Chrome + humanization 的组合是正解。

**可能的补充用途（未来）**：如果出现"需要批量爬大量弱检测页面"的子任务（比如预取一批静态页面做 RAG 索引），可以考虑 Lightpanda 做专用后端。但这是另一个产品、另一个场景，不是 stealth-browser 的范围。

## 5. Sources

- [lightpanda.io](https://lightpanda.io)
- [GitHub: lightpanda-io/browser](https://github.com/lightpanda-io/browser)
- [Lightpanda Blog: CDP Under the Hood](https://lightpanda.io/blog/posts/cdp-under-the-hood)
- [HN discussion: Show HN: Lightpanda](https://news.ycombinator.com/item?id=42817439)
- [DataDome: Lightpanda anti-detect tool 分类](https://datadome.co/anti-detect-tools/lightpanda/)（页面存在本身就是"DataDome 已识别 Lightpanda"的信号）
- [Supacrawler with Lightpanda](https://www.antoineross.com/projects/supacrawler)
- [Patchright 原理与对比](https://www.zenrows.com/blog/patchright)
- [roundproxies: How to use Lightpanda in 2026](https://roundproxies.com/blog/lightpanda/)
- [Castle: From Puppeteer stealth to Nodriver](https://blog.castle.io/from-puppeteer-stealth-to-nodriver-how-anti-detect-frameworks-evolved-to-evade-bot-detection/)
