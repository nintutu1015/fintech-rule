# 服务清单

每个常用 App 或网站的当前出口、规则位置和已知问题。"出口"是 Loon 策略组名；规则是否命中以 `tests/expectations.json` 的回归预期为准。

**验证状态**：`预期` 表示生成配置的规则顺序由 `python3 tools/project.py check` 检查；`设备` 一栏需要你在 Loon 请求日志里确认后填写日期，目前全部未做。

## AI

| 项目 | 内容 |
| --- | --- |
| 出口 | `AI` 组：Proxy / Auto / Fallback / 自建节点 / US DE UK KR JP TW HK SG。不固定地区，在组内手动选 |
| 本地规则 | `rules/local/ai-overrides.list`：`grok.com → AI`，写在本地以免被后面的 Twitter 远程规则抢先 |
| 远程来源 | `A_AI.list`、`Openai`、`Claude`、`AppleIntelligence`、`Perplexity`、`Cursor`、`Ai_other`，全部 → `AI` |
| 预期 | 已登记（`grok.com`；上述远程来源的策略） |
| 设备 | 未验证 |

## PayPal

| 项目 | 内容 |
| --- | --- |
| 出口 | `Paypal` 组：DIRECT / Proxy / Auto / Fallback / 自建节点 / 八个地区。手动选 `US / DE / UK` |
| 本地规则 | 无 |
| 远程来源 | `Paypal` → `Paypal`，排在通用 `A_Global` 之前，否则组的选择不会生效（有顺序预期保护） |
| 已知限制 | 一个组同一时间只有一个当前策略，不能按登录账户区分国家；切换账户前手动切换该组 |
| 设备 | 未验证 |

## Bybit

| 项目 | 内容 |
| --- | --- |
| 出口 | `DE`（本地例外）；其余域名 `HK`（远程来源） |
| 本地规则 | `rules/local/personal.list`：`bybit.nl`、`bybit.eu`、`bybit.biz`、`bycsi.com`、`byd3c3.com` → `DE` |
| 远程来源 | `A_bybit.list` → `HK`。本地规则先于远程规则生效，所以上面五个域名走 DE，其余走 HK |
| 预期 | 五个本地域名与 `A_bybit.list` 均已登记 |
| 设备 | 未验证 |

同文件里的 `bitkeep.com → HK`、`polymarket.com → TW`、`bonify.de → DE`，以及远程来源 `A_Binance.list → TW`，目前记录的是现状，没有额外说明；需要补充原因时写在这里。

## 英国运营商

| 项目 | 内容 |
| --- | --- |
| 出口 | `UK` |
| 本地规则 | `rules/local/carriers.list`：`giffgaff.com`，以及两个 Wi-Fi Calling 的 ePDG 域名（MCC 234 的 MNC 010、033）→ `UK` |
| 缺策略的 IP | `31.94.0.0/16`、`87.194.0.0/16`、`148.252.160.0/19` 三条按旧配置原样保留，没有出口策略；`check` 每次发出三条警告，新增缺策略规则会报错 |
| 待你决定 | 把三条 IP 明确指向 UK 或其他出口，或停用；决定前不由工具代改 |
| 设备 | 未验证 |

## 其它个人站点

| 站点 | 出口 | 位置 |
| --- | --- | --- |
| `mosavi.ai`、`cathaypacific.com` | Proxy | `personal.list` |
| 香港银行 App 日志域名 `ant-hkbank-linkd.cn-hongkong.log.aliyuncs.com` | HK | `personal.list` |
| `em.mesl.cloud` | DIRECT | `network.list` |
| `meslcloud.com`、`githubusercontent.com` | Proxy | `network.list` |

## 新增一个 App 或网站

1. 在 Loon 请求日志里找到实际域名，记下它现在命中的规则。不要保存带令牌的完整 URL。
2. 在 `rules/local/` 对应片段里加一行，如 `DOMAIN-SUFFIX,example.com,AI`，策略必须是已有的策略组或 DIRECT / REJECT。Loon 的规则来源优先级是本地规则 > 插件规则 > 订阅（远程）规则，同一来源内按顺序，先命中先生效（[Loon 文档](https://nsloon.app/docs/Rule/)）。
3. 在 `tests/expectations.json` 的 `local_domains` 登记同一个域名和出口。漏掉这一步 `check` 会报错。
4. 如果这个服务由远程规则覆盖，改 `config/upstreams.json`，并确认它在 `A_Global` 之前。
5. 运行 `python3 tools/project.py check` 和 `python3 -m unittest discover -s tests -v`，再 `build` 导入 Loon，用请求日志确认，最后回到本页填写设备验证日期。
