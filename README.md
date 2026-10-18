# fintech-rule：我的 Loon 分流规则

做法参考 [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Loon)：**一个服务一个 `.list` 文件，文件里只有规则，不写出口策略**；出口在 Loon 里订阅时用 `policy=` 指定。没有构建程序，改完推送，Loon 刷新订阅就生效。

```
rule/Loon/<服务>/<服务>.list     规则文件
loon/subscriptions.conf          可直接粘贴进 Loon 的订阅清单（含出口策略和顺序）
```

## 怎么用

1. 打开 [`loon/subscriptions.conf`](loon/subscriptions.conf)，把 `[Remote Rule]` 下的行加到你 Loon 配置的 `[Remote Rule]`；`[Plugin]` 同理。也可以在 Loon 里逐条添加订阅规则。
2. Loon 里要有清单里用到的策略组，名字必须一致：自己的规则用到 `AI`、`DE`、`HK`、`TW`、`UK`、`Proxy`，第三方规则还用到 `Twitter`、`Paypal`、`Google` 等。
3. 以后改规则：编辑 `.list`，推送到 GitHub，Loon 刷新订阅即可。

你 Loon 里原来写在本地 `[Rule]` 的同一批规则可以继续用；改用订阅后，删掉对应的本地行，避免重复。

## 规则列表

| 文件 | 内容 | 建议策略 |
| --- | --- | --- |
| `Grok` | grok.com，要排在 Twitter 之前 | AI |
| `Bybit_DE` | 固定走德国的 Bybit 域名，要排在 `A_bybit.list`（HK）之前 | DE |
| `Bitkeep` | bitkeep.com | HK |
| `Bonify` | bonify.de | DE |
| `Polymarket` | polymarket.com | TW |
| `CathayPacific` | cathaypacific.com | Proxy |
| `Mosavi` | mosavi.ai | Proxy |
| `AntBankHK` | 香港银行 App 的日志域名 | HK |
| `UKCarrier` | giffgaff 与两个 Wi-Fi Calling 域名 | UK |

## 新增一个 App 或网站

1. 新建 `rule/Loon/<名字>/<名字>.list`，每行一条，如 `DOMAIN-SUFFIX,example.com`。可用 `DOMAIN`、`DOMAIN-SUFFIX`、`DOMAIN-KEYWORD`、`IP-CIDR`（IP 要加 `,no-resolve`）。**不要在文件里写策略。**
2. 在 `loon/subscriptions.conf` 里自己的那一段加一行，写上 `policy=` 和 `tag=`。
3. 如果有第三方规则可能抢先匹配这个域名，就把这一行放在它前面。
4. 推送，在 Loon 里刷新订阅，用请求日志确认命中。

## 注意

- **顺序**：订阅规则从上到下，先命中先生效。`Paypal` 要排在 `A_Global` 前面，否则 PayPal 组的选择不生效。
- **优先级**：Loon 的来源优先级是本地规则 > 插件规则 > 订阅规则（[Loon 文档](https://nsloon.app/docs/Rule/)）。自己的规则改成订阅后，比原来写在本地 `[Rule]` 低了一档，如果插件里有同域名的规则，会先命中插件。某条没生效时，把它改回写进本地 `[Rule]`。
- **PayPal**：一个策略组同一时间只能选一个出口，不能按登录账户区分国家，换账户前手动切换 `Paypal` 组。
- **三条英国 IP 段**：旧配置里没有写出口，一直没决定，在 `UKCarrier.list` 里先注释掉了。
- **WeatherKit 插件**：原地址在 2026-09-26 核对时返回 404，清单里仍保留。
- **A_Global**：它排在 Google、Instagram 等服务组前面，这些服务目前走 Proxy。
- **设备验证**：还没有在 Loon 实机上逐项确认。

## 来源与许可

第三方规则只引用原作者的地址，没有复制，版权归各自作者。本仓库自己的规则暂未设置许可证。
