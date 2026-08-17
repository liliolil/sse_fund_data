# 上交所 ETF 申购赎回清单（PCF）数据源调研

调研日期：2026-08-14

## 结论

- 上交所 ETF PCF 总页为：<https://www.sse.com.cn/disclosure/fund/etflist/>。
- 列表和详情数据不在初始 HTML 中，页面使用 `commonQuery.do` 发起 JSONP 请求后渲染。
- “下载”不是从 HTML 表格导出，而是直接请求文件下载接口。当前验证的三只 ETF 均返回 UTF-8 XML 文件，HTTP 响应头为 `Content-Type: application/octet-stream;charset=UTF-8`，并带有 `.xml` 附件文件名。
- 最新 PCF 可用普通 HTTP 客户端直接下载，不需要 Selenium。
- 公开页面、页面真实请求和当前前端代码均只提供最新 PCF。下载接口只传 `fundCode`，未观察到日期参数或历史清单入口。因此“可按历史日期直接下载”目前未验证，不能自行构造日期参数。

## 1. 页面与真实数据流

### 1.1 PCF 列表页

页面 URL：

```text
https://www.sse.com.cn/disclosure/fund/etflist/
```

页面包含股票 ETF、债券 ETF、跨境 ETF、商品 ETF 分类，以及代码/简称/关键词搜索。初始 HTML 只有页面结构，基金列表由 JSONP 请求加载。

页面还明确提示：本栏目内容由基金公司提供；栏目披露时间统一调整为交易日上午 8:30，如与当日 8 点以后通过证通云盘发布的公告文件不一致，以证通云盘文件为准。该提示意味着网站接口适合作为公开采集来源，但存在盘前更新时点和权威性边界。

### 1.2 PCF 详情页

URL 结构：

```text
https://www.sse.com.cn/disclosure/fund/etflist/detail.shtml?fundid={ETF代码}
```

示例：

```text
https://www.sse.com.cn/disclosure/fund/etflist/detail.shtml?fundid=510050
```

详情页也不把 PCF 数据写在初始 HTML 中，而是通过两个 JSONP 接口分别取得基本信息和成分证券信息。详情页上的下载按钮仍指向“最新文件”下载接口。

另有上交所 ETF 专栏的基金档案页面：

```text
https://etf.sse.com.cn/fundlist/funddetail/index.shtml?fundid={ETF代码}
```

该页面展示同类 PCF 信息，前端配置仍引用下文相同的基本信息、成分信息和下载接口，没有观察到独立的历史 PCF 下载接口。

## 2. 已确认接口

### 2.1 ETF PCF 列表接口

- URL：`https://query.sse.com.cn/commonQuery.do`
- 浏览器实际请求方式：GET（以 `<script>` 资源加载 JSONP）
- 返回格式：JSONP；回调函数名由 `jsonCallBack` 指定，回调内部为 JSON
- `sqlId`：`COMMON_SSE_PL_ETFGGSGSHQD_L`
- 日期机制：无日期查询参数；结果字段 `TRADING_DAY` 表示最新公告日期
- 分页：支持

真实请求参数：

| 参数 | 含义/已观察值 |
| --- | --- |
| `jsonCallBack` | JSONP 回调名，例如 `jsonpCallback48228695` |
| `isPagination` | `true` |
| `pageHelp.pageSize` | 页面实际使用 `25` |
| `pageHelp.pageNo` | 页码，从 `1` 开始 |
| `pageHelp.beginPage` | 页面实际使用 `1` |
| `pageHelp.cacheSize` | 页面实际使用 `1` |
| `pageHelp.endPage` | 页面实际使用 `1` |
| `sqlId` | `COMMON_SSE_PL_ETFGGSGSHQD_L` |
| `ETF_CLASS` | ETF 分类；实际观察到股票主分类 `01`、科创板单市场 `09`、跨境 `33` 等 |
| `type` | `inParams` |
| `FUND_CODE` | 可为空或传 6 位基金代码 |
| `KEY_WORDS` | 可为空或传搜索关键词 |
| `_` | 页面生成的缓存规避时间戳，不是业务日期 |

真实请求示例：

```text
GET https://query.sse.com.cn/commonQuery.do?jsonCallBack=cb&isPagination=true&pageHelp.pageSize=25&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&sqlId=COMMON_SSE_PL_ETFGGSGSHQD_L&ETF_CLASS=01&type=inParams&FUND_CODE=510050&KEY_WORDS=
```

返回示例（从 JSONP 回调内提取的 JSON，节选）：

```json
{
  "result": [
    {
      "ETF_TYPE": "001",
      "NAV": "￥3.0358",
      "ETF_VERSION": "XML",
      "TRADING_DAY": "20260814",
      "ETF_CLASS": "01",
      "FUNDID2": "510050",
      "ETF_FULLNAME": "上证50交易型开放式指数证券投资基金",
      "FUND_COMP_NAME": "华夏基金管理有限公司"
    }
  ],
  "pageHelp": {
    "pageNo": 1,
    "pageSize": 25,
    "pageCount": 1,
    "total": 1
  }
}
```

### 2.2 PCF 基本信息接口

- URL：`https://query.sse.com.cn/commonQuery.do`
- 页面代码调用方式：JSONP；实际使用 GET 可正常返回
- `sqlId`：`COMMON_SSE_CP_JJLB_ETFJJGK_GGSGSHQD_JBXX_C`
- 参数：`isPagination=false`、`FUNDID2={ETF代码}`、`sqlId`、`jsonCallBack={回调名}`
- 分页：不分页
- 日期参数：无；返回最新 `TRADING_DAY` 和 `PRE_TRADING_DAY`
- 返回格式：JSONP

真实请求示例：

```text
GET https://query.sse.com.cn/commonQuery.do?isPagination=false&FUNDID2=510050&sqlId=COMMON_SSE_CP_JJLB_ETFJJGK_GGSGSHQD_JBXX_C&jsonCallBack=cb
```

返回示例（节选）：

```json
{
  "result": [
    {
      "TRADE_CODE": "510050",
      "TRADING_DAY": "20260814",
      "PRE_TRADING_DAY": "20260813",
      "CREATION_REDEMPTION_UNIT": "900000",
      "NAVPERCU": "￥2732243.64",
      "NAV": "￥3.0358",
      "PRE_CASH_COMPONENT": "￥59.64",
      "ESTIMATED_CASH_COMPONENT": "￥0.64",
      "RECORD_NUM": "50",
      "FILE_ID": "1461953"
    }
  ]
}
```

`FILE_ID` 确实存在于返回值中，但当前页面下载代码没有使用它；是否能用于历史文件定位未验证，不能据此猜测接口。

### 2.3 PCF 成分证券接口

- URL：`https://query.sse.com.cn/commonQuery.do`
- 页面代码调用方式：JSONP；实际使用 GET 可正常返回
- `sqlId`：`COMMON_SSE_CP_JJLB_ETFJJGK_GGSGSHQD_COMPONENT_C`
- 参数：`isPagination=false`、`FUNDID2={ETF代码}`、`sqlId`、`jsonCallBack={回调名}`
- 分页：不分页
- 日期参数：无，只返回该基金最新 PCF 的成分
- 返回格式：JSONP

真实请求示例：

```text
GET https://query.sse.com.cn/commonQuery.do?isPagination=false&FUNDID2=510050&sqlId=COMMON_SSE_CP_JJLB_ETFJJGK_GGSGSHQD_COMPONENT_C&jsonCallBack=cb
```

返回示例（节选）：

```json
{
  "result": [
    {
      "INSTRUMENT_ID": "600028",
      "INSTRUMENT_NAME": "中国石化",
      "QUANTITY": "4100",
      "SUBSTITUTION_FLAG": "1",
      "CREATION_PREMIUM_RATE": "34%",
      "REDEMPTION_DISCOUNT_RATE": "0%",
      "SUBSTITUTION_CASH_AMOUNT": "-",
      "UNDERLYION_SECURITY_ID": "101",
      "ETF_VERSION": "XML"
    }
  ]
}
```

注意：接口字段名实际拼写为 `UNDERLYION_SECURITY_ID`，本文原样记录，不擅自改名。

### 2.4 最新 PCF 文件下载接口

- URL：`https://query.sse.com.cn/etfDownload/downloadETF2Bulletin.do`
- 请求方式：GET
- 参数：仅观察到 `fundCode={6位ETF代码}`
- `sqlId`：无
- 日期参数：无
- 分页参数：无
- 返回格式：文件下载；三个样本均为 UTF-8 XML

URL 示例：

```text
https://query.sse.com.cn/etfDownload/downloadETF2Bulletin.do?fundCode=510050
```

510050 的实际响应：

```text
HTTP 200
Content-Type: application/octet-stream;charset=UTF-8
Content-Disposition: attachment;filename="ssepcf_510050_20260814.xml"
```

XML 示例（真实响应节选）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<SSEPortfolioCompositionFile>
  <FundInstrumentID>510050</FundInstrumentID>
  <CreationRedemptionUnit>900000</CreationRedemptionUnit>
  <TradingDay>20260814</TradingDay>
  <PreTradingDay>20260813</PreTradingDay>
  <NAVperCU>2732243.64</NAVperCU>
  <NAV>3.0358</NAV>
  <PreCashComponent>59.64</PreCashComponent>
  <EstimatedCashComponent>0.64</EstimatedCashComponent>
  <RecordNumber>50</RecordNumber>
  <ComponentList>
    <Component>
      <InstrumentID>600028</InstrumentID>
      <InstrumentName>中国石化</InstrumentName>
      <Quantity>4100</Quantity>
      <SubstitutionFlag>1</SubstitutionFlag>
      <CreationPremiumRate>0.34</CreationPremiumRate>
      <RedemptionDiscountRate>0</RedemptionDiscountRate>
      <UnderlyingSecurityID>101</UnderlyingSecurityID>
    </Component>
  </ComponentList>
</SSEPortfolioCompositionFile>
```

以上 XML 只保留一条成分作为示例；实际文件含 50 条。JSONP 接口把比率格式化为百分数字符串，而 XML 保存原始小数值，正式采集应优先保留 XML 原值。

## 3. 三只 ETF 的真实下载验证

所有请求均为直接 GET 文件下载接口，没有执行浏览器脚本，也没有使用 Selenium。

| ETF | 类型依据 | HTTP | 附件文件名 | 字节数 | XML 根节点 | `RecordNumber`/实际成分节点数 |
| --- | --- | ---: | --- | ---: | --- | ---: |
| 510050 上证50ETF | 列表 `ETF_CLASS=01`，单市场股票 ETF | 200 | `ssepcf_510050_20260814.xml` | 19,224 | `SSEPortfolioCompositionFile` | 50 / 50 |
| 588200 科创芯片ETF | 列表 `ETF_CLASS=09`，科创板单市场 ETF | 200 | `ssepcf_588200_20260814.xml` | 19,077 | `SSEPortfolioCompositionFile` | 50 / 50 |
| 513500 标普500ETF | 列表 `ETF_CLASS=33`，跨境 ETF | 200 | `ssepcf_513500_20260814.xml` | 204,878 | `SSEPortfolioCompositionFile` | 503 / 503 |

三个文件均非空、XML 可解析，`FundInstrumentID` 与请求代码一致，`TradingDay` 均为 20260814。三只样本中 `Component` 数量与 `RecordNumber` 一致，未发现成分证券代码的明显重复。

跨境样本 513500 的成分代码可为英文字母（例如 `YUM`、`ZBH`），证券名称在该文件中也可能仅给出英文代码；因此正式实现不能把成分证券代码写死为 6 位数字，也不能假定证券名称一定是中文。

## 4. 文件格式和字段对应

当前三只样本共用同一下载接口、文件命名规则、XML 根节点和主要层次结构。各 ETF 的可选字段不完全相同：例如 `SubstitutionCashAmount` 只在适用的成分节点出现，跨境样本还存在 `CreationLimit`。解析器应允许可选节点缺失，不能要求所有 ETF 节点集合完全一致。

可确认字段如下：

| 业务含义 | XML 字段 | JSONP 字段 | 验证情况 |
| --- | --- | --- | --- |
| ETF 代码 | `FundInstrumentID` | `TRADE_CODE` / `FUNDID2` | 已验证 |
| PCF 日期 | `TradingDay` | `TRADING_DAY` | 已验证，格式 `YYYYMMDD` |
| 前一交易日 | `PreTradingDay` | `PRE_TRADING_DAY` | 已验证 |
| 成分证券代码 | `Component/InstrumentID` | `INSTRUMENT_ID` | 已验证 |
| 成分证券名称 | `Component/InstrumentName` | `INSTRUMENT_NAME` | 已验证 |
| 数量 | `Component/Quantity` | `QUANTITY` | 已验证 |
| 现金替代标志 | `Component/SubstitutionFlag` | `SUBSTITUTION_FLAG` | 已验证；样本出现 `1`、`2`，其业务含义应结合基金文件/规则解释 |
| 替代金额 | `Component/SubstitutionCashAmount` | `SUBSTITUTION_CASH_AMOUNT` | 已验证为可选字段 |
| 最小申购赎回单位 | `CreationRedemptionUnit` | `CREATION_REDEMPTION_UNIT` | 已验证 |
| 现金差额 | `PreCashComponent` | `PRE_CASH_COMPONENT` | 已验证；详情页明确将其显示为“现金差额” |
| 预估现金部分 | `EstimatedCashComponent` | `ESTIMATED_CASH_COMPONENT` | 已验证，不应与现金差额混用 |
| 成分记录数 | `RecordNumber` | `RECORD_NUM` | 已验证 |
| 挂牌市场/市场 ID | `Component/UnderlyingSecurityID` | `UNDERLYION_SECURITY_ID` | 字段存在已验证；代码值到市场名称的完整映射未验证 |

本次验证没有发现 TXT、CSV 或普通 HTML 作为当前下载文件格式。上交所 2025 年基金管理人公告说明 PCF 曾进行 XML 版本切换；这能解释当前 `ETF_VERSION=XML`，但不能据此断言所有历史时期或所有 ETF 永远只有 XML 格式。

## 5. 历史 PCF 支持情况

### 已确认

- 列表接口返回每只基金的最新 `TRADING_DAY`。
- 详情基本信息与成分接口没有日期参数，只返回当前最新数据。
- 下载按钮和前端源代码实际生成的 URL 只有 `fundCode` 参数。
- 下载附件名包含服务端返回的 PCF 日期，例如 `ssepcf_510050_20260814.xml`。

### 未验证

- 未发现公开页面上的历史日期选择器或历史 PCF 文件列表。
- 未发现经过页面真实请求或官方前端代码确认的历史下载日期参数。
- 未验证 `FILE_ID` 是否关联可下载的历史文件，页面没有用它下载。
- 未验证基金管理人网站或“证通云盘”是否提供长期历史归档；它们不属于本次确认的上交所匿名公开接口。
- 未验证 XML 切换之前的历史 PCF 文件格式和下载可用性。

因此，当前结论应表述为：**上交所公开网页接口已验证支持最新 PCF；历史 PCF 的匿名公开下载能力未验证，不能通过猜测参数实现。** 如果项目必须历史回填，需要另行研究上交所历史归档、基金管理人网站或获得授权的数据渠道。

## 6. 是否需要 Selenium

不需要。

- 列表和详情为可直接请求的 JSONP。
- 最新 PCF 为可直接 GET 的 XML 附件。
- 页面没有登录、验证码或必须执行浏览器脚本才能生成的下载令牌。

使用 Selenium 只会增加浏览器驱动、等待和稳定性成本，不能解决当前尚未发现历史接口的问题。

## 7. 推荐正式实现方式

本阶段不编写正式爬虫。后续实现建议如下：

1. 使用 `requests` 或 `httpx` 请求列表 JSONP，按实际分页遍历，不写死基金数量或页数；从列表取得基金代码、类型、最新 `TRADING_DAY` 和 `ETF_VERSION`。
2. 以 `(基金代码, TRADING_DAY)` 作为最新文件采集批次键；本地已存在相同键时可跳过，实现每日增量检查。
3. 使用已验证的 `downloadETF2Bulletin.do?fundCode=...` 下载文件，保存原始响应；以响应头文件名和 XML 内 `FundInstrumentID`、`TradingDay` 交叉校验，防止更新时点错配。
4. 使用标准 XML 解析器解析，不用正则；允许可选字段缺失，并保留未识别节点，便于应对格式升级。
5. 原始 XML 与清洗后的表结构分开保存。数值字段保留 XML 原值，展示层百分比格式不要反向当作原始数据。
6. 下载后检查 HTTP 状态、内容非空、XML 可解析、根节点、基金代码、日期、`RecordNumber` 与 `Component` 数量；对成分代码重复只报警并保留原始证据，不静默去重。
7. 控制为低频顺序请求，并在 8:30 之后采集；如业务要求盘前绝对权威版本，需要另外评估公告所述证通云盘渠道。
8. 历史回填模块与“最新 PCF 增量模块”分开设计；在真实历史来源确认前，不构造或猜测日期 URL。

## 8. 已验证与未验证汇总

### 已验证

- PCF 总页、详情页和 ETF 专栏基金档案页真实存在。
- 列表 JSONP 接口、基本信息 JSONP 接口、成分 JSONP 接口可直接返回非空真实数据。
- 三只不同类别 ETF 的最新文件下载接口均返回 HTTP 200 XML 附件。
- 三只样本共用下载 URL 结构、文件命名结构、XML 根节点和主要字段结构。
- ETF 代码、日期、成分代码/名称/数量、现金替代标志、替代金额、最小申购赎回单位、现金差额等字段已在真实返回中确认。
- 普通 HTTP 客户端即可获取，不需要 Selenium。

### 未验证

- 上交所匿名公开接口是否保存并允许下载历史日期 PCF。
- `FILE_ID` 是否存在未公开的历史下载用途。
- XML 版本切换前的历史 TXT/其他格式及其可访问性。
- 所有 ETF 分类、所有基金管理人和所有可选字段的完整兼容性；本次结论基于三只不同类型样本。

