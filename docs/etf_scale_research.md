# 上交所 ETF 规模数据源调查

调查日期：2026-08-14（Asia/Shanghai）

## 结论

上交所“ETF规模”页面的数据不是直接写在初始 HTML 中，也不是通过 Excel、CSV 等文件下载提供。页面加载后以 `<script>` 资源方式发起跨域 **JSONP GET** 请求，主请求返回 ETF 份额及分页信息；页面随后按本页基金代码发起另一个 JSONP 请求，补充基金扩位简称。

因此，正式实现时应直接请求 JSONP 接口并解析回调参数中的 JSON，不需要 Selenium。本文仅记录调查结果，不包含正式爬虫。

## 页面 URL

- 页面名称：ETF规模
- URL：<https://www.sse.com.cn/market/funddata/volumn/etfvolumn/>
- 页面说明：统计数据为当日清算后数据。
- 页面字段：日期、基金代码、基金扩位简称、总份额（万份）。

调查时页面显示最近日期为 `2026-08-13`，共 `893` 条，每页默认 `25` 条。

## 数据来自哪里

| 候选来源 | 结论 | 证据 |
| --- | --- | --- |
| 初始 HTML | 否 | 页面骨架先加载，数据由后续动态请求填入。 |
| XHR / Fetch | 严格说不是 | 浏览器资源类型为 `script`，不是 `xhr` 或 `fetch`。 |
| JSON API | 是（JSONP） | 实际请求带 `jsonCallBack=jsonpCallback...`，响应作为脚本执行。 |
| 文件下载 | 否 | 页面无数据导出或下载入口，实际数据请求指向 `commonQuery.do`。 |

## 主数据接口

### URL 与请求方式

- 基础 URL：<https://query.sse.com.cn/commonQuery.do>
- 请求方式：`GET`
- 返回格式：JSONP（JavaScript 回调包裹的 JSON）
- 是否分页：是
- 登录：页面正常访问时未要求登录

浏览器于 2026-08-14 捕获到的真实请求如下（回调随机数和 `_` 时间戳每次都会变化）：

```text
https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback39066650&isPagination=true&pageHelp.pageSize=25&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE=&_=1786678097406
```

### 参数

| 参数 | 捕获值 | 作用 |
| --- | --- | --- |
| `jsonCallBack` | `jsonpCallback39066650` | JSONP 回调函数名；随机数字会变化。 |
| `isPagination` | `true` | 启用分页。 |
| `pageHelp.pageSize` | `25` | 每页条数；页面还提供 50、100。 |
| `pageHelp.pageNo` | `1` | 当前页码。 |
| `pageHelp.beginPage` | `1` | 分页辅助参数；首屏真实请求值为 1。 |
| `pageHelp.cacheSize` | `1` | 分页辅助参数；首屏真实请求值为 1。 |
| `pageHelp.endPage` | `1` | 分页辅助参数；首屏真实请求值为 1。 |
| `sqlId` | `COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L` | ETF 规模查询标识；来自真实请求。 |
| `STAT_DATE` | 空字符串 | 查询日期；空值表示页面默认的最近可用日期。 |
| `_` | `1786678097406` | 毫秒时间戳/缓存破坏参数，不是业务筛选条件。 |

### 返回数据示例

网络响应格式是 JSONP，即外层为请求指定的回调函数，函数参数为分页 JSON。可按如下方式理解其结构：

```javascript
jsonpCallback39066650({
  "pageHelp": {
    "pageNo": 1,
    "pageSize": 25,
    "data": [
      {
        "日期": "2026-08-13",
        "基金代码": "510010",
        "总份额（万份）": "13052.44"
      }
    ]
  }
})
```

上例中的中文键是为了准确表达已验证的业务字段，而不是声称它们是接口的原始字段名。浏览器中该条记录实际渲染为：

```text
2026-08-13 | 510010 | 180治理ETF交银 | 13052.44
```

主接口负责日期、基金代码、总份额和分页；扩位简称由下面的名称接口按本页代码补齐。由于该站采用 JSONP，解析时应去掉 `jsonCallBack(...)` 外壳后再按 JSON 处理，不应把响应当作纯 JSON 直接解析。

## 基金扩位简称接口

### URL 与请求方式

- 基础 URL：<https://query.sse.com.cn/security/stock/queryExpandName.do>
- 请求方式：`GET`
- 返回格式：JSONP

首屏加载时捕获到的真实请求：

```text
https://query.sse.com.cn/security/stock/queryExpandName.do?jsonCallBack=jsonpCallback89096242&secCodes=510010%2C510020%2C510030%2C510040%2C510050%2C510060%2C510090%2C510100%2C510130%2C510140%2C510150%2C510160%2C510170%2C510180%2C510190%2C510200%2C510210%2C510230%2C510270%2C510290%2C510300%2C510310%2C510320%2C510330%2C510350&_=1786678097407
```

### 参数

| 参数 | 作用 |
| --- | --- |
| `jsonCallBack` | JSONP 回调函数名。 |
| `secCodes` | 逗号分隔的证券代码列表；URL 编码后逗号为 `%2C`。 |
| `_` | 毫秒时间戳/缓存破坏参数。 |

返回值把证券代码映射到扩位简称。经页面合并后的首条示例为 `510010 -> 180治理ETF交银`。

## 是否需要 Selenium

**不需要。** 数据接口为公开页面实际使用的 GET JSONP 请求，没有必须通过浏览器执行的交互、登录或验证码。Selenium 只会增加浏览器启动、等待与故障恢复成本。

需要注意，上交所接口可能检查 `Referer`、`User-Agent` 或访问频率。实现阶段应使用普通 HTTP 客户端，带上页面来源的 `Referer: https://www.sse.com.cn/` 和合理的浏览器 `User-Agent`，控制请求频率，并对非交易日、空日期结果和临时拒绝访问做显式处理。这些请求头是否为硬性要求应在实现阶段单独验证，不在本次调查中猜测。

## 推荐实现方式

1. 用 `requests`/`httpx` 等 HTTP 客户端请求 `commonQuery.do`，保留捕获到的真实参数名与 `sqlId`。
2. `STAT_DATE` 为空可取得页面默认最近日期；历史日期应传页面日期控件实际采用的格式，并在实现前用单次请求验证。
3. 遍历 `pageHelp.pageNo`，以响应分页元数据为终止条件，不把当前共 893 条或 36 页写死。
4. 去除 JSONP 回调外壳后用标准 JSON 解析器解析，禁止用 `eval`。
5. 若需要扩位简称，按每页代码批量调用 `queryExpandName.do` 后以基金代码关联；若主响应未来已包含可用简称，则可省略第二次请求，但应以实际响应字段为准。
6. 保存时保留“总份额（万份）”的原始单位。该页面名为“ETF规模”，但其表格提供的是份额，不是按市价计算的资产净值或亿元规模。

## 调查边界与证据说明

- 接口 URL、请求方式、参数名、`sqlId`、分页值和名称接口均来自页面在浏览器中实际产生的资源请求，不是根据命名猜测。
- 页面实际渲染出了 2026-08-13 的 893 条记录，证明请求成功并被页面消费。
- 当前调查工具能列出已加载 JSONP 脚本 URL和最终 DOM，但没有导出该跨域脚本的原始响应正文。因此，上面的返回示例明确区分了“已确认的 JSONP 分页外形/页面业务值”和“未宣称的原始字段名”。正式实现前应保存一次原始响应作为接口契约样本。
- 本次未编写爬虫，也未测试批量抓取。
