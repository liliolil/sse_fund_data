# 上交所基金公告数据获取方式调查

调查日期：2026-08-14（Asia/Shanghai）

## 结论

上交所基金公告页面存在两条真实数据链路：

1. **最新公告首屏**：页面通过 GET 请求读取一个纯 JSON 静态清单；
2. **筛选、搜索和历史分页**：页面使用 `query.sse.com.cn/commonQuery.do`，返回 JSONP 分页结果。

公告列表中的链接直接指向 PDF，没有发现独立的 HTML 公告详情页。PDF 可以使用普通 HTTP GET 直接下载，不需要 Selenium。

首屏 JSON 明确提供 `discloseId`，适合作为最新公告增量去重标识。历史搜索接口不返回 `discloseId`，因此全量历史采集应以规范化后的完整 PDF URL（或 PDF 文件名）作为稳定唯一键；下载后还可增加文件 SHA-256 作为内容级校验。

## 基金公告列表页面

- 页面名称：最新基金公告
- 页面 URL：<https://www.sse.com.cn/disclosure/fund/announcement/>
- 登录：不需要
- Selenium：不需要

页面提供以下筛选控件：

- 证券代码或扩位简称；
- 标题关键字；
- 公告类型；
- 日期范围。

公告类型选项及页面实际值：

| 显示名称 | 请求值 `BULLETIN_TYPE` |
| --- | --- |
| 全部 | `reits01,fund01,reits02,fund02,reits03,fund03,reits04,fund04,reits05,fund05,reits06,fund06` |
| 募集 | `reits01,fund01` |
| 上市 | `reits02,fund02` |
| 定期报告 | `reits03,fund03` |
| 临时报告 | `reits04,fund04` |
| 基金运作 | `reits05,fund05` |
| 基金管理人公告 | `reits06,fund06` |

这些值来自页面当前 JavaScript 配置，不推测其中枚举编码的内部定义。

---

## 一、最新公告静态 JSON

### 接口

- URL：<https://www.sse.com.cn/disclosure/fund/announcement/json/fund_bulletin_publish_order.json>
- 请求方法：`GET`
- 返回格式：纯 JSON
- 分页：无
- 参数：页面实际请求会附加随机 `v` 参数用于防缓存，例如 `?v=0.123...`；该参数不是业务筛选条件。

页面 JavaScript 使用：

```text
/disclosure/fund/announcement/json/fund_bulletin_publish_order.json?v=<随机数>
```

### 真实请求验证

2026-08-14 直接请求返回：

- HTTP 状态：`200`
- Content-Type：`application/json`
- 顶层字段：`publishData`
- 公告数量：`141`
- 结果非空

首条返回示例：

```json
{
  "discloseId": "20260814005133006L7DFUND_BULLETI",
  "discloseDate": "2026-08-14",
  "bulletinTitle": "华夏纳斯达克100交易型开放式指数证券投资基金（QDII）午间收盘二级市场交易价格溢价风险提示公告",
  "bulletinClassic": "FUND_BULLETIN",
  "bulletinUrl": "/disclosure/fund/announcement/c/new/2026-08-14/513300_20260814_6L7D.pdf",
  "securityCode": "513300",
  "securityAbbr": "纳斯达克"
}
```

### 字段对应关系

| 目标字段 | JSON 字段 | 验证结果 |
| --- | --- | --- |
| 公告 ID | `discloseId` | 已验证，显式提供。 |
| 基金代码 | `securityCode` | 已验证。 |
| 基金简称 | `securityAbbr` | 已验证；这是首屏 JSON 中的简称字段。 |
| 公告标题 | `bulletinTitle` | 已验证。 |
| 公告日期 | `discloseDate` | 已验证，格式 `YYYY-MM-DD`。 |
| 公告详情 URL | `bulletinUrl` | 已验证；该链接直接指向 PDF，没有独立 HTML 详情页。 |
| PDF URL | `bulletinUrl` | 已验证；相对 URL 需与 `https://www.sse.com.cn` 拼接。 |
| 公告类别 | `bulletinClassic` | 已验证返回值；具体枚举范围未验证。 |

本次对 141 条首屏记录检查：

- `discloseId` 共 141 个不同值，无重复；
- `bulletinUrl` 共 141 个不同值，无重复。

该 JSON 是“最新发布清单”，不提供搜索参数和分页元数据，不能替代历史搜索接口。

---

## 二、公告搜索与历史分页接口

### 接口

- URL：<https://query.sse.com.cn/commonQuery.do>
- 页面前端配置的方法：`POST`
- 实际验证：`POST` 和 `GET` 均返回成功 JSONP；为贴近页面实现可使用 POST，若统一底层框架也可使用已验证的 GET。
- 返回格式：JSONP
- `sqlId`：`COMMON_PL_JJXX_JJGG_NEW_L`
- 分页：支持

页面前端调用配置为 `type: 'post'`、`dataType: 'jsonp'`。本次分别直接发送 GET 和 POST，二者均返回 HTTP 200、相同结构及同一真实公告。由于跨域 JSONP 库可能对底层传输进行适配，本文不声称浏览器最终一定使用哪种传输；可以确认服务端公开接受两种方法。

### 参数

| 参数 | 示例 | 说明 |
| --- | --- | --- |
| `jsonCallBack` | `jsonpCallbackResearch20260814` | JSONP 回调函数名。 |
| `isPagination` | `true` | 启用分页。 |
| `pageHelp.pageSize` | `25` | 每页条数。 |
| `pageHelp.pageNo` | `1` | 当前页码。 |
| `pageHelp.beginPage` | `1` | 分页辅助参数；翻到第 N 页时页面逻辑会相应更新。 |
| `pageHelp.cacheSize` | `1` | 分页辅助参数。 |
| `pageHelp.endPage` | `1` | 分页辅助参数；翻到第 N 页时页面逻辑会相应更新。 |
| `type` | `inParams` | 页面固定传入值；内部语义未验证。 |
| `sqlId` | `COMMON_PL_JJXX_JJGG_NEW_L` | 基金公告搜索标识。 |
| `TITLE` | 空或标题关键字 | 公告标题关键字筛选。 |
| `SECURITY_CODE` | `513030` | 六位基金代码筛选。页面也支持通过智能提示选择扩位简称，最终请求仍使用代码。 |
| `BULLETIN_TYPE` | `reits04,fund04` 等 | 公告类型筛选。 |
| `OTHER_TYPE` | 空 | 页面代码预留的其他类型参数；当前基金公告选项未触发，业务含义未验证。 |
| `START_DATE` | `2026-08-14` | 开始日期，格式 `YYYY-MM-DD`。 |
| `END_DATE` | `2026-08-14` | 结束日期，格式 `YYYY-MM-DD`。 |
| `DATE_DESC` | `1` | 日期降序。 |
| `DATE_ASC` | 空 | 日期升序开关。 |
| `CODE_DESC` | 空 | 代码降序开关。 |
| `CODE_ASC` | 空 | 代码升序开关。 |

### 页面日期限制机制

页面 JavaScript 中已确认以下客户端规则：

- 日期控件格式为 `yyyy-MM-dd`；
- 日期控件最小值配置为 `1990-12-19`，但这不等于服务端一定有从该日开始的数据；
- 未指定代码和关键字时，页面把查询区间限制为最多 3 个月；
- 指定代码或关键字时，页面把查询区间限制为最多 3 年；
- 只填代码或关键字、不填日期时，页面自动取结束日并向前推 3 年；
- 没有代码、关键字和日期时，页面拒绝查询。

服务端是否强制执行相同区间限制未验证，正式实现不应绕过页面限制进行高负载查询。

### 单条真实响应验证

查询条件：

```text
SECURITY_CODE=513030
START_DATE=2026-08-14
END_DATE=2026-08-14
pageHelp.pageSize=25
pageHelp.pageNo=1
```

GET 与 POST 均返回 HTTP 200。JSONP 解包后的真实结果：

```json
{
  "SSEDATE": "2026-08-14",
  "ORG_BULLETIN_TYPE_DESC": "提示性公告",
  "BULLETIN_TYPE_DESC": "临时报告(基金)",
  "NUM": "1",
  "TITLE": "华安基金管理有限公司关于华安国际龙头(DAX)交易型开放式指数证券投资基金二级市场交易价格溢价风险提示公告",
  "FUND_EXPANSION_ABBR": "德国ETF华安",
  "SECURITY_CODE": "513030",
  "URL": "/disclosure/fund/announcement/c/new/2026-08-14/513030_20260814_Q1Y3.pdf"
}
```

响应同时包含：

```json
{
  "pageHelp": {
    "pageNo": 1,
    "pageSize": 25,
    "pageCount": 1,
    "total": 1,
    "data": ["同 result 中的记录"]
  },
  "result": ["公告记录"]
}
```

### 搜索接口字段对应关系

| 目标字段 | 搜索接口字段 | 验证结果 |
| --- | --- | --- |
| 公告 ID | 无显式字段 | 未提供；`NUM` 是当前排序下的序号，不能作为稳定公告 ID。 |
| 基金代码 | `SECURITY_CODE` | 已验证。 |
| 基金简称 | `FUND_EXPANSION_ABBR` | 已验证，为扩位简称。 |
| 公告标题 | `TITLE` | 已验证。 |
| 公告日期 | `SSEDATE` | 已验证，格式 `YYYY-MM-DD`。 |
| 公告详情 URL | `URL` | 已验证；直接指向 PDF，不是 HTML 详情页。 |
| PDF URL | `URL` | 已验证；拼接主站域名后可直接下载。 |
| 公告类型 | `BULLETIN_TYPE_DESC` | 已验证。 |
| 原始公告类型 | `ORG_BULLETIN_TYPE_DESC` | 已验证。 |

### 历史分页验证

查询日期范围 `2026-08-01` 至 `2026-08-14`、每页 25 条时，接口返回：

```text
total = 1296
pageCount = 52
pageNo = 1
result 条数 = 25
```

随后将以下分页参数全部更新为第 2 页：

```text
pageHelp.pageNo=2
pageHelp.beginPage=2
pageHelp.endPage=2
```

接口返回 `pageNo=2`、25 条记录，首条 `NUM=26` 且 PDF URL 与第 1 页首条不同，证明历史分页真实可用。只改变 `pageHelp.pageNo` 而不更新 `beginPage/endPage` 会得到错误的重复页，因此正式实现不能只设置页码一个参数。

---

## 三、PDF 直接下载验证

验证 URL：

```text
https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-08-14/513030_20260814_Q1Y3.pdf
```

使用普通 GET 并发送 `Range: bytes=0-31`，结果：

```text
HTTP 206 Partial Content
Content-Type: application/pdf
Content-Range: bytes 0-31/121107
响应开头: %PDF-1.5
```

结论：PDF 无需登录、无需临时下载令牌，可以直接下载；服务器还支持字节范围请求。此次只读取前 32 字节进行验证，没有保存文件。

## 公告详情 URL 与 PDF URL 的关系

基金公告列表和搜索结果中的标题链接都直接指向 `.pdf`。本次未发现独立的 HTML 详情 URL，因此：

- “公告详情 URL”实际就是 `bulletinUrl` / `URL`；
- “PDF URL”也是同一地址；
- 相对路径应通过 `new URL(relativePath, 'https://www.sse.com.cn')` 或等价 URL 拼接生成绝对地址，不要手工字符串猜测路径。

## 唯一标识与增量更新

### 可用标识

1. **首选：`discloseId`**
   - 最新静态 JSON 明确返回；
   - 本次 141 条中全部非重复；
   - 适合最新公告轮询去重。

2. **跨最新与历史查询的统一键：规范化完整 PDF URL**
   - 最新 JSON 和历史搜索接口都返回 PDF 路径；
   - 本次 141 条最新公告 URL 全部非重复；
   - 搜索接口不返回 `discloseId`，因此 URL 是两条链路都具备的最佳候选唯一键。

3. **辅助内容校验：PDF SHA-256**
   - 下载后计算，可检测同 URL 内容变化；
   - 不应为了发现新公告而预先下载全部历史 PDF。

### 不应作为唯一键

- `NUM`：只是查询结果中的排序序号，分页后继续为 26、27……，会随条件和排序变化；
- 基金代码 + 日期：同一基金同一天可以发布多份公告；
- 标题：不同基金可能出现相同标题，同一公告标题也可能后续重复发布；
- PDF 文件名中的四位尾码：看起来具有区分作用，但官方未说明其语义，不单独作为已验证 ID。

### 推荐增量策略（仅调研结论）

- 高频轻量检查可轮询最新静态 JSON，以 `discloseId` 和完整 PDF URL 去重；
- 每日补偿任务使用搜索接口查询最近若干日，按完整 PDF URL 补漏；
- 使用 `SSEDATE/discloseDate` 作为分区和游标辅助，不单独作为唯一键；
- 分页终止以响应 `pageHelp.pageCount` / `total` 为准，不写死页数；
- 原始 JSON/JSONP 元数据与 PDF 文件分开保存；
- 保持低请求频率，不批量重复下载已存在的 PDF。

## 是否支持所需筛选能力

| 能力 | 结论 | 证据 |
| --- | --- | --- |
| 日期筛选 | 支持 | `START_DATE`、`END_DATE`，格式 `YYYY-MM-DD`；真实单日及跨日请求均成功。 |
| 基金代码筛选 | 支持 | `SECURITY_CODE=513030` 真实请求返回对应基金公告。 |
| 基金简称筛选 | 页面支持选择 | 输入框支持扩位简称智能提示，页面最终把选择结果转为 `SECURITY_CODE`；是否存在独立简称 API 参数未验证。 |
| 标题关键字筛选 | 支持 | 参数 `TITLE`，来自页面当前实现；本次未单独提交关键字样本。 |
| 公告类型筛选 | 支持 | `BULLETIN_TYPE` 及六组页面选项来自当前实现；返回中包含类型描述字段。 |
| 历史分页 | 支持 | 真实跨日期请求返回 52 页，并验证第 2 页首条序号为 26。 |

## 是否需要 Selenium

**不需要。** 最新公告是普通 JSON 文件，历史搜索是公开 JSONP 接口，PDF 是可直接 GET 的静态文件。所有核心数据均可由 `requests` 或 `httpx` 获取。

## 已验证与未验证

### 已验证

- 基金公告列表页面及筛选控件。
- 最新公告 JSON URL、GET 方法、真实非空响应及字段。
- 搜索接口 URL、`sqlId`、全部页面参数和分页机制。
- 搜索接口 GET、POST 均返回 HTTP 200 和相同真实公告。
- 日期与基金代码筛选的真实请求。
- 跨日期历史分页及第 2 页数据。
- 公告代码、扩位简称、标题、日期、类型和 PDF URL 原始字段。
- 最新 JSON 的 `discloseId` 与 PDF URL 在 141 条样本中无重复。
- PDF 直链支持 GET、Range 和 `application/pdf`，文件头有效。
- 页面没有独立 HTML 公告详情，标题链接直接打开 PDF。

### 未验证

- 服务端可查询公告的最早历史日期；日期控件最小值不等于数据覆盖起点。
- `BULLETIN_TYPE` 各内部编码的官方数据字典，仅验证了页面显示名称与当前请求值。
- `TITLE` 关键字的匹配方式（精确、模糊、是否分词）及大小写规则。
- 服务端是否强制页面的 3 个月/3 年查询区间限制。
- PDF URL 或内容是否存在事后更正、替换机制。
- `discloseId` 的官方生成规则及其在全部历史数据中的唯一性；目前仅在最新 141 条样本中验证无重复。
- 搜索接口没有显式公告 ID，PDF URL 作为历史唯一键属于基于已验证唯一链接的实现建议，不是官方字段定义。

## 调查边界

本次未编写正式爬虫，未进行大规模历史回填，只执行少量真实列表、分页和 PDF 字节范围请求。调查到此结束。
