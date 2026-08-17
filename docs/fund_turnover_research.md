# 上交所基金成交数据源调查

调查日期：2026-08-14（Asia/Shanghai）

## 结论

上交所基金成交概况包含每日、每周、月度和年度四类页面。页面使用 `query.sse.com.cn/commonQuery.do` 的 **GET JSONP** 接口获取数据，请求在浏览器中表现为跨域 `script` 资源，不是 XHR/Fetch，也不是 Excel、CSV 或其他数据文件下载。

每日和每周的当前页面接口已返回并渲染 2026 年真实非空数据。另有“更多历史数据”页面及一组旧版历史查询 `sqlId`：每日历史接口已返回非空数据；每周、月度、年度历史接口和参数已通过真实请求确认，但本次页面默认查询结果为空，具体历史覆盖范围仍需后续验证。

不需要 Selenium。底层可以与 ETF/LOF 规模数据共用 HTTP GET、JSONP 解包、请求头、限速和原始响应保存框架，但成交概况是非分页聚合查询，参数和解析模型不能照搬规模接口。

## 页面清单

| 周期 | 当前页面 | 历史页面 |
| --- | --- | --- |
| 每日 | <https://www.sse.com.cn/market/funddata/overview/day/> | <https://www.sse.com.cn/market/funddata/overview/day/index_his.shtml> |
| 每周 | <https://www.sse.com.cn/market/funddata/overview/weekly/> | <https://www.sse.com.cn/market/funddata/overview/weekly/index_his.shtml> |
| 月度 | <https://www.sse.com.cn/market/funddata/overview/monthly/> | <https://www.sse.com.cn/market/funddata/overview/monthly/index_his.shtml> |
| 年度 | <https://www.sse.com.cn/market/funddata/overview/yearly/> | <https://www.sse.com.cn/market/funddata/overview/yearly/index_his.shtml> |

## 数据来源类型

| 类型 | 判断 | 依据 |
| --- | --- | --- |
| 初始 HTML | 否 | 初始页面提供结构，最终统计表由后续接口结果填充。 |
| XHR / Fetch | 否 | 真实业务请求的浏览器资源类型为 `script`。 |
| JSON | 不是纯 JSON | 响应外层存在回调函数。 |
| JSONP | 是 | 请求带 `jsonCallBack=jsonpCallback...`。 |
| Excel / CSV | 否 | 上交所这些页面未发现成交数据导出请求或下载入口。 |
| 其他文件 | 否 | 未发现承载页面成交统计的其他文件。 |
| Selenium | 不需要 | 普通 GET 接口已经返回页面所需数据。 |

所有已捕获业务请求均为：

- 基础 URL：<https://query.sse.com.cn/commonQuery.do>
- 请求方法：`GET`
- 返回格式：JSONP
- 分页：未发现分页参数；成交概况是指定期间的聚合结果，不是明细列表分页。
- 登录：页面访问及数据加载未要求登录。

---

## 一、每日基金成交概况

### 当前页面接口

2026-08-14 捕获并成功执行的真实请求：

```text
https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback62872462&sqlId=COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C&SEARCH_DATE=&PRODUCT_CODE=05%2C13%2C16%2C14%2C15%2C12&type=inParams&_=1786680069891
```

| 参数 | 捕获值 | 说明 |
| --- | --- | --- |
| `jsonCallBack` | `jsonpCallback62872462` | JSONP 回调名；数字会变化。 |
| `sqlId` | `COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C` | 当前每日成交概况查询标识。 |
| `SEARCH_DATE` | 空字符串 | 日期参数；空值返回当前页面最近可用交易日。历史值格式本次未通过当前接口单独提交验证。 |
| `PRODUCT_CODE` | `05,13,16,14,15,12` | 页面实际传入的产品代码集合；各代码正式含义**未验证**。 |
| `type` | `inParams` | 页面实际参数；内部语义**未验证**。 |
| `_` | `1786680069891` | 毫秒时间戳/缓存破坏参数。 |

### 非空验证

接口执行后，页面显示数据日期 `2026-08-13`，并渲染：

| 单日情况 | 基金 | ETF | 公募REITs | LOF | 基金回购 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 挂牌数 | 1097 | 917 | 61 | 119 | - |
| 成交量（亿份） | 1256.86 | 1251.15 | 0.87 | 4.84 | - |
| 成交金额（亿元） | 3254.29 | 3242.31 | 2.88 | 9.1 | - |

页面注明：自 2022-09-05 起，交易型货币基金纳入 ETF 统计。

### 每日历史接口

历史页面真实请求：

```text
https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback57481&searchDate=&sqlId=COMMON_SSE_SJ_GPSJ_CJGK_DAYCJGK_C&fundType=47&_=1786680489691
```

| 参数 | 捕获值 | 说明 |
| --- | --- | --- |
| `jsonCallBack` | `jsonpCallback57481` | JSONP 回调名。 |
| `searchDate` | 空字符串 | 历史查询日期参数，注意大小写与当前接口的 `SEARCH_DATE` 不同。 |
| `sqlId` | `COMMON_SSE_SJ_GPSJ_CJGK_DAYCJGK_C` | 每日历史查询标识。 |
| `fundType` | `47` | 页面实际参数；正式枚举含义**未验证**。 |
| `_` | `1786680489691` | 缓存破坏时间戳。 |

该请求实际返回并渲染数据日期 `2022-02-25` 的非空数据，例如基金成交量 `292.0121644` 亿份、成交金额 `770.90336177` 亿元。这证明每日历史接口真实可用，但空日期为何默认到该日期、历史覆盖边界以及显式日期格式仍为**未验证**。

---

## 二、每周基金成交概况

### 当前页面接口

真实请求：

```text
https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback53781575&sqlId=COMMON_SSE_SJ_GPSJ_CJGK_MZGK_C&PRODUCT_CODE=05%2C13%2C16%2C14%2C15%2C12&START_DATE=&END_DATE=&type=inParams&_=1786680141928
```

| 参数 | 捕获值 | 说明 |
| --- | --- | --- |
| `jsonCallBack` | `jsonpCallback53781575` | JSONP 回调名。 |
| `sqlId` | `COMMON_SSE_SJ_GPSJ_CJGK_MZGK_C` | 当前每周成交概况查询标识。 |
| `PRODUCT_CODE` | `05,13,16,14,15,12` | 页面实际产品代码集合；枚举含义**未验证**。 |
| `START_DATE` | 空字符串 | 开始日期参数；空值使用页面默认最近统计周。 |
| `END_DATE` | 空字符串 | 结束日期参数；空值使用页面默认最近统计周。 |
| `type` | `inParams` | 页面实际参数；内部语义**未验证**。 |
| `_` | `1786680141928` | 缓存破坏时间戳。 |

### 非空验证

接口执行后，页面显示统计期间 `2026-08-03` 至 `2026-08-07`，并渲染非空汇总：基金成交金额 `18264.5326` 亿元、成交量 `7439.1088` 亿份、累计交易天数 5 天。页面还提供最高/最低成交金额、最高/最低成交量及对应日期。

页面注明：自 2022-08-29 起，交易型货币基金纳入 ETF 统计。

### 每周历史接口

历史页面真实请求：

```text
https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback64655&startDate=2026-08-03&endDate=2026-08-09&sqlId=COMMON_SSE_SJ_GPSJ_CJGK_WEEKCJGK_C&fundType=47&_=1786680561790
```

| 参数 | 捕获值 | 说明 |
| --- | --- | --- |
| `jsonCallBack` | `jsonpCallback64655` | JSONP 回调名。 |
| `startDate` | `2026-08-03` | 历史周开始日期，已确认格式为 `YYYY-MM-DD`。 |
| `endDate` | `2026-08-09` | 历史周结束日期，已确认格式为 `YYYY-MM-DD`。 |
| `sqlId` | `COMMON_SSE_SJ_GPSJ_CJGK_WEEKCJGK_C` | 每周历史查询标识。 |
| `fundType` | `47` | 页面实际参数；枚举含义**未验证**。 |
| `_` | `1786680561790` | 缓存破坏时间戳。 |

请求已真实执行，但该历史接口在上述区间显示“暂无数据”。因此只能确认接口、参数和日期格式，不能据此次结果断言它覆盖 2026 年；当前每周接口则已在相近期间返回非空数据。

---

## 三、月度基金成交概况

### 页面行为

当前月度页面本次未自动发出业务查询，也没有渲染统计值。点击“更多历史数据”可进入月度历史页面；历史页面提供年份、月份和查询按钮。

### 月度历史接口

历史页面加载时实际发出的请求：

```text
https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback37070&inYear=2024-11&sqlId=COMMON_SSE_SJ_GPSJ_CJGK_MONTHCJGK_C&fundType=47&_=1786680338849
```

| 参数 | 捕获值 | 说明 |
| --- | --- | --- |
| `jsonCallBack` | `jsonpCallback37070` | JSONP 回调名。 |
| `inYear` | `2024-11` | 年月参数，已确认页面请求格式为 `YYYY-MM`。参数名虽为 `inYear`，实际值含月份。 |
| `sqlId` | `COMMON_SSE_SJ_GPSJ_CJGK_MONTHCJGK_C` | 月度成交概况查询标识。 |
| `fundType` | `47` | 页面实际参数；枚举含义**未验证**。 |
| `_` | `1786680338849` | 缓存破坏时间戳。 |

该请求已真实执行，但 `2024-11` 条件下页面显示“没有数据”。月度接口存在、请求方式、`sqlId` 和日期参数均已验证；哪些月份实际有数据、覆盖范围和返回记录内容仍为**未验证**。

---

## 四、年度基金成交概况

### 页面行为

年度当前页面存在，并提供“更多历史数据”。年度历史页面提供年份选择和查询按钮。

### 年度历史接口

真实请求：

```text
https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback42990&inYear=2024&sqlId=COMMON_SSE_SJ_GPSJ_CJGK_YEARCJGK_C&fundType=47&_=1786680414922
```

| 参数 | 捕获值 | 说明 |
| --- | --- | --- |
| `jsonCallBack` | `jsonpCallback42990` | JSONP 回调名。 |
| `inYear` | `2024` | 年份参数，格式 `YYYY`。 |
| `sqlId` | `COMMON_SSE_SJ_GPSJ_CJGK_YEARCJGK_C` | 年度成交概况查询标识。 |
| `fundType` | `47` | 页面实际参数；枚举含义**未验证**。 |
| `_` | `1786680414922` | 缓存破坏时间戳。 |

请求已真实执行，但 `2024` 条件下页面显示“没有数据”。年度接口及参数已验证，实际可用年份和响应业务值仍为**未验证**。

---

## 返回格式

所有真实业务请求均以 `script` 形式加载，并带 `jsonCallBack`，因此返回是 JSONP：

```javascript
jsonpCallback62872462({
  /* 接口返回的成交概况数据 */
})
```

当前调查工具已确认 JSONP 外层、请求 URL、参数以及页面解码后的业务值，但未导出跨域脚本的原始正文。原始字段名和精确嵌套结构为**未验证**；本文不以页面中文列名冒充接口字段名。正式开发前应保存一份原始响应并建立真实字段映射，解析时去除 JSONP 外壳后使用标准 JSON 解析器，禁止 `eval`。

## 是否支持历史日期查询

**支持，但分为当前接口和旧版历史接口两组。**

- 每日当前接口有 `SEARCH_DATE`；历史接口有 `searchDate`。
- 每周当前接口有 `START_DATE`、`END_DATE`；历史接口有 `startDate`、`endDate`。
- 月度历史接口使用 `inYear=YYYY-MM`。
- 年度历史接口使用 `inYear=YYYY`。

每日历史接口已返回非空旧数据，说明至少部分历史日期确实可查。每周/月度/年度历史请求已执行但本次条件返回空值，因此各自数据覆盖边界仍需验证。不能仅凭年份/月份下拉选项存在就认定每个期间都有数据。

## 能否直接做增量更新

### 每日

**适合增量更新。** 可按最后成功交易日之后的日期逐日请求，并以响应中的实际数据日期去重。非交易日可能为空或回退到其他日期，不能只根据 HTTP 成功判断写入。

### 每周

**可以增量更新，但应按完整统计周处理。** 当前接口以日期区间查询。建议仅在一周结束后写入，并使用开始日期、结束日期组成唯一键，避免未完成周和重复周。

### 月度、年度

**接口形态支持按月/按年查询，但目前不能确认可直接稳定增量。** 本次真实请求返回空表，需要先验证实际可用期间和原始响应，再决定自动增量策略。

## 是否需要 Selenium

**不需要。** 所有已发现接口均为无需登录的 GET JSONP 请求。页面选择日期只是构造请求参数，没有必须依赖浏览器的能力。应优先使用 `requests` 或 `httpx`。

## 与 ETF/LOF 规模数据能否共用底层框架

### 可以共用

- HTTP GET 会话、超时和有限重试；
- `Referer`、`User-Agent` 等请求头配置；
- JSONP 回调名生成与安全解包；
- 原始响应落盘、日志、限速和错误处理；
- 日期驱动的历史回填与增量调度基础设施。

### 不能直接共用

- 规模接口是带 `pageHelp.*` 的分页明细；成交概况接口未发现分页，是期间聚合结果；
- `sqlId`、日期参数和产品筛选参数完全不同；
- 成交概况无需调用 `queryExpandName.do`；
- 成交概况按周期存在多套当前/历史接口，解析结构也尚未验证；
- 规模数据按基金代码形成明细，成交概况按基金类型形成汇总。

结论：**可以共用底层传输和 JSONP 工具层，但应建立独立的基金成交数据源模块和独立配置，不能复用规模页面的分页及字段映射逻辑。**

## 已验证与未验证

### 已验证

- 每日、每周、月度、年度当前及历史页面 URL。
- 每日和每周当前接口的真实请求、`sqlId`、日期参数和非空业务结果。
- 每日历史接口的真实请求和非空旧数据。
- 每周、月度、年度历史接口的真实请求、`sqlId` 及日期参数格式。
- 请求方法为 GET、返回形态为 JSONP、没有分页和文件下载依赖。
- 不需要 Selenium，并可复用规模采集的底层 HTTP/JSONP 框架。

### 未验证

- 所有接口原始响应的确切字段名、字段类型和完整嵌套结构。
- `PRODUCT_CODE` 各枚举值及 `fundType=47` 的正式业务定义。
- 当前每日接口显式 `SEARCH_DATE` 值的准确格式。
- 当前每周接口显式日期值与统计周边界的服务端校验规则。
- 每周旧版历史接口可用的日期范围。
- 月度、年度接口实际有数据的期间及长期可用性。
- 交易日/非交易日请求是空结果、报错还是自动回退的完整规则。
- 服务端对请求头和访问频率的硬性限制。

## 调查边界

本次只进行页面和接口调查，未编写正式爬虫、未修改现有爬虫代码、未进行批量历史回填或高并发测试。调查到此结束。
