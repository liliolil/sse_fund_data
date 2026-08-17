# 上交所公募 REITs 规模数据源调研

调研日期：2026-08-15（Asia/Shanghai）

## 结论

上交所“公募 REITs 规模”页面使用一个真实的公开 **GET JSONP** 接口加载数据：

```text
https://query.sse.com.cn/commonQuery.do
```

页面使用的 `sqlId` 为：

```text
COMMON_SSE_SJ_JJSJ_JJGM_REITSGM_L
```

数据不在初始 HTML 表格中，页面脚本通过跨域 `script`/JSONP 请求填充表格。接口支持分页、空日期获取最新数据以及指定历史日期查询，不需要 Selenium。基金扩位简称已包含在主接口字段 `FUND_EXPAND_ABBR` 中；页面没有为此数据源调用 `queryExpandName.do`。

## 证据来源

### 页面

- 页面名称：公募 REITs 规模
- 页面 URL：<https://www.sse.com.cn/market/funddata/volumn/reits/>
- 页面表头：交易日期、基金代码、基金扩位简称、基金规模（场内，万份）

浏览器实际渲染了 2026-08-14 的 REITs 规模数据，并捕获到 `commonQuery.do` JSONP `script` 请求。首屏显示 25 条，页面显示总数 61 条及 3 页分页。

### 页面 JavaScript

页面实际引用：

```text
https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_fundData_2021.js
```

该脚本中的 `reitsvolumn` 对象明确配置：

```javascript
reitsParam: {
    isPagination: true,
    "pageHelp.pageSize": 25,
    "pageHelp.cacheSize": 1,
    sqlId: "COMMON_SSE_SJ_JJSJ_JJGM_REITSGM_L",
    FUND_TYPE: "01",
    TRADE_DATE: "",
    MAX_DATE: 1
}
```

选择日期后，页面执行：

```javascript
reitsParam.MAX_DATE = "";
reitsParam.TRADE_DATE = dateStr.replace(/\-/g, "");
```

因此指定日期请求的真实格式是 `TRADE_DATE=YYYYMMDD`，不是 `YYYY-MM-DD`。历史查询仍使用同一个 `sqlId`，没有发现单独 historical `sqlId`。

## 数据来源类型

| 类型 | 结论 | 状态 | 依据 |
| --- | --- | --- | --- |
| 初始 HTML 数据 | 否 | verified | 初始页面提供容器，表格由脚本请求结果填充。 |
| XHR / Fetch | 否 | verified | 浏览器中业务数据表现为跨域 `script` 资源。 |
| JSON | 不是纯 JSON | verified | 响应外层带 JSONP 回调。 |
| JSONP | 是 | verified | 请求带 `jsonCallBack`，正文为 `callback({...})`。 |
| Excel / CSV / 文件 | 未发现 | verified（本页面） | 页面数据加载没有文件下载请求。 |
| Selenium | 不需要 | verified | 普通 HTTP GET 可取得相同数据。 |

## 真实接口

### URL 和方法

- URL：<https://query.sse.com.cn/commonQuery.do>
- 方法：`GET`
- 返回：JSONP
- HTTP 成功状态：`200`
- 登录：不需要

浏览器捕获的真实首屏请求形态：

```text
https://query.sse.com.cn/commonQuery.do
  ?jsonCallBack=jsonpCallback...
  &isPagination=true
  &pageHelp.pageSize=25
  &pageHelp.cacheSize=1
  &sqlId=COMMON_SSE_SJ_JJSJ_JJGM_REITSGM_L
  &FUND_TYPE=01
  &TRADE_DATE=
  &MAX_DATE=1
  &pageHelp.pageNo=1
  &pageHelp.beginPage=1
  &pageHelp.endPage=1
  &_=...
```

### 参数

| 参数 | 最新查询 | 指定日期查询 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| `jsonCallBack` | 动态回调名 | 动态回调名 | verified | JSONP 回调函数名。 |
| `isPagination` | `true` | `true` | verified | 启用分页。 |
| `sqlId` | `COMMON_SSE_SJ_JJSJ_JJGM_REITSGM_L` | 同左 | verified | 页面真实配置。 |
| `FUND_TYPE` | `01` | `01` | verified | 页面真实值；该枚举的正式业务定义未验证。 |
| `TRADE_DATE` | 空字符串 | `YYYYMMDD` | verified | 页面选择 `YYYY-MM-DD` 后会去除连字符。 |
| `MAX_DATE` | `1` | 空字符串 | verified | 最新查询与指定日期查询的关键差异；内部正式定义未验证。 |
| `pageHelp.pageSize` | 默认 `25` | 默认 `25` | verified | 页面还提供 50、100 条选项。 |
| `pageHelp.pageNo` | 页码 | 页码 | verified | 当前页号。 |
| `pageHelp.beginPage` | 当前页 | 当前页 | verified | 分页辅助参数。 |
| `pageHelp.endPage` | 当前页 | 当前页 | verified | 分页辅助参数。 |
| `pageHelp.cacheSize` | `1` | `1` | verified | 页面真实参数；内部语义未验证。 |
| `_` | 毫秒时间戳 | 毫秒时间戳 | verified | 缓存破坏参数。 |

直接把带连字符日期与 `MAX_DATE=1` 混用会得到空结果。正式实现必须按页面 JavaScript 的真实分支构造参数，不能照搬 ETF、LOF 或货币基金的日期处理。

## 分页

分页已真实验证。2026-08-14 在 `pageHelp.pageSize=25` 时：

| 页码 | 返回行数 | `pageHelp.total` | `pageHelp.pageCount` |
| ---: | ---: | ---: | ---: |
| 1 | 25 | 61 | 3 |
| 2 | 25 | 61 | 3 |
| 3 | 11 | 61 | 3 |

响应中的记录同时出现在顶层 `result` 和 `pageHelp.data`。页面 JavaScript读取 `result`，现有 `scale_common.fetch_paginated_scale_rows()` 读取 `pageHelp.data`；本次真实响应中两处内容数量一致。

正式实现仍应根据服务端 `pageCount`、`total` 和当前页实际行数停止，不写死 3 页或 61 条。

## 原始返回字段

近期、历史响应中的记录字段一致，已验证的完整字段为：

```text
CURRENT_SHARE_DATE
FUND_ABBR
FUND_CODE
FUND_EXPAND_ABBR
LIMIT_VOL
NEGO_VALUE
NUM
SELL_VOL
TOTAL_VALUE
TOTAL_VOL
TO_RATE
TRADE_AMT
TRADE_DATE
TRADE_VOL
UNLIMIT_VOL
```

近期真实记录示例（名称按接口真实字段返回）：

```json
{
  "FUND_CODE": "508000",
  "TRADE_DATE": "20260814",
  "CURRENT_SHARE_DATE": "20260814",
  "FUND_EXPAND_ABBR": "华安张江产业园REIT",
  "TOTAL_VOL": "90451.51"
}
```

其余原始字段虽然已确认存在，但本次未根据字段名推断正式业务含义；正式 crawler 可保留完整 `raw_record_json`，待有权威字段说明后再决定是否标准化。

### 规模字段、单位和类型

- 页面 JavaScript明确使用 `v.TOTAL_VOL` 填充“基金规模（场内，万份）”列。
- 原始字段：`TOTAL_VOL`
- 单位：万份（来自页面表头与该字段的直接映射）
- JSON 原始类型：字符串
- 页面处理：对非空值执行 `parseFloat`
- Python 建议类型：`Float64` 或 `float64`

因此可以确认 `TOTAL_VOL` 与现有规模模块中的 `shares_10k` 在单位和数量语义上可以对齐，但仍建议保留原始字段 JSON 作为证据。

## 基金名称

主接口直接返回：

- `FUND_ABBR`
- `FUND_EXPAND_ABBR`

页面明确用 `FUND_EXPAND_ABBR` 渲染“基金扩位简称”。浏览器资源清单没有出现 `queryExpandName.do`，61 条近期记录中 `FUND_EXPAND_ABBR` 缺失数为 0。

结论：**REITs 规模 crawler 不需要调用 `queryExpandName.do`。** 可保留名称查询工具作为其他规模数据源能力，但不应为 REITs 增加无意义请求。

## 真实日期验证

所有有 Referer 的业务请求均返回 HTTP 200 和可正常解包的 JSONP。

| 场景 | 请求参数 | HTTP | 返回行数 | 实际数据日期 | 代码数 | 缺失扩位简称 | 日期回退 |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| 最新 | `TRADE_DATE=`、`MAX_DATE=1` | 200 | 61 | 2026-08-14 | 61 | 0 | 不适用 |
| 近期明确日期 | `TRADE_DATE=20260814`、`MAX_DATE=` | 200 | 61 | 2026-08-14 | 61 | 0 | 否 |
| 较早历史日 | `TRADE_DATE=20220225`、`MAX_DATE=` | 200 | 6 | 2022-02-25 | 6 | 0 | 否 |
| 更早代表日 | `TRADE_DATE=20210621`、`MAX_DATE=` | 200 | 5 | 2021-06-21 | 5 | 0 | 否 |
| 周末 | `TRADE_DATE=20260809`、`MAX_DATE=` | 200 | 0 | 无 | 0 | 0 | 否，没有回退 |
| 早期空日 | `TRADE_DATE=20210618`、`MAX_DATE=` | 200 | 0 | 无 | 0 | 0 | 否 |

### 历史能力结论

- 指定历史日期：支持，verified。
- 历史日期格式：`YYYYMMDD`，verified。
- 单独 historical `sqlId`：页面代码和真实请求中均未发现；当前接口通过清空 `MAX_DATE` 切换为指定日期查询，verified。
- 已验证历史可追溯：至少到 2021-06-21，verified。
- 最早历史边界：unverified。`2021-06-18` 为空不能单独证明接口边界；本次没有进行日期暴力扫描。
- 页面日历配置的最小值是 `1990-12-19`，但它只是前端控件限制，不能作为 REITs 数据起始日期证据。

## 请求头验证

使用常规浏览器 `User-Agent` 和页面 Referer 时，请求正常返回 JSONP。

在其余参数相同的情况下移除 Referer：

- HTTP 状态仍为 200；
- 响应变成 `({"success":"false", ...})`，没有正确的 JSONP 回调函数名；
- 错误信息为系统错误，不能作为有效数据响应。

结论：直接 HTTP 客户端正式实现应设置：

```text
Referer: https://www.sse.com.cn/market/funddata/volumn/reits/
User-Agent: 常规浏览器 User-Agent
```

已验证“带 Referer 成功、无 Referer 失败”；服务端是否还有其他隐含请求头规则为 partially_verified。实现不能只根据 HTTP 200 判断成功，还应验证 JSONP 回调和 `actionErrors`。

## 最新与增量更新可行性

### verified

1. 空 `TRADE_DATE` 加 `MAX_DATE=1` 可直接取得远程最近可用日，无需先解析 HTML 日期。
2. 返回记录携带实际 `TRADE_DATE`，可与本地最大日期比较。
3. 指定日期请求返回精确日期或空结果；已验证的周末不会回退。
4. 可以使用 `date + fund_code` 作为建议主键。
5. 可以采用“远程最新日期 vs 本地最大日期”的基础增量策略。

### partially_verified

- 本次验证了一个周末和一个早期空日，但没有穷举节假日、临时停市日等所有非交易日类型。
- 没有验证服务端长期稳定性、频率限制和多年连续回填表现。

## 标准化字段建议

建议正式 crawler 输出：

| 标准字段 | 原始字段 | 建议类型 | 状态 |
| --- | --- | --- | --- |
| `date` | `TRADE_DATE` | `datetime64[ns]` | verified |
| `fund_code` | `FUND_CODE` | pandas `string` | verified |
| `fund_name` | `FUND_EXPAND_ABBR` | pandas `string` | verified |
| `shares_10k` | `TOTAL_VOL` | `Float64` | verified |
| `raw_record_json` | 完整原始记录 | pandas `string` | recommended |

`CURRENT_SHARE_DATE` 可能是有价值的额外日期字段，但其与 `TRADE_DATE` 的正式业务关系没有权威说明，本次样本中二者相同。建议先保留在原始记录中，含义标记为 unverified，不要仅凭名称推断。

## 与现有规模模块的复用关系

### 可以直接复用

- `scale_common.py` 的 JSONP transport、重试、超时和错误检查；
- `fetch_paginated_scale_rows()` 的 `pageHelp` 分页循环；
- 数值字符串转换前去除千位逗号的处理方式；
- `scale_service_common.py` 的日期区间、backfill、incremental、Parquet 原子保存和 state/checkpoint；
- `date + fund_code` 去重和空结果不覆盖历史文件的质量策略；
- 基于 `src/config/paths.py` 的 cwd 无关默认路径。

### 不应复用或必须独立配置

- 不应复用 ETF、LOF、货币基金的 `sqlId`；
- REITs 使用 `TRADE_DATE`，且指定日期格式为 `YYYYMMDD`；
- 最新查询需要 `MAX_DATE=1`，指定日期需要清空 `MAX_DATE`；
- 需要 `FUND_TYPE=01`；
- 原始字段是 `FUND_CODE`、`FUND_EXPAND_ABBR`、`TOTAL_VOL`；
- 不需要调用 `queryExpandName.do`。

最小实现建议：下一阶段新增独立 `reits_scale.py` 和 `reits_scale_service.py`，复用现有公共 transport、分页和 service 流程，仅独立实现 REITs 请求参数与字段映射。不要为此重构现有 ETF/LOF/货币基金模块。

## 验证状态汇总

### verified

- 页面 URL、页面表头和页面真实 JavaScript。
- GET JSONP 主接口 URL、`sqlId` 和分页参数。
- `FUND_TYPE=01`、`TRADE_DATE`、`MAX_DATE` 的页面真实使用方式。
- 最新、近期明确日期、2022-02-25、2021-06-21 和周末请求结果。
- 25 条分页下的 3 页完整分页行为。
- 完整原始字段集合。
- `TOTAL_VOL` 对应“基金规模（场内，万份）”，原始类型为字符串。
- 主响应已包含扩位简称，不需要 `queryExpandName.do`。
- 普通 HTTP 请求可获取数据，不需要 Selenium。
- 空日期可获取最新数据，适合基础增量更新。

### partially_verified

- Referer 在本次直接请求中是成功与失败的关键差异，但其他请求头硬性规则未穷举。
- 非交易日行为只验证了代表性周末和早期空日。
- 当前接口已验证到 2021-06-21，但完整历史覆盖连续性未检查。
- 访问频率限制与长期稳定性未测试。

### unverified

- 最早可查询历史日期。
- `FUND_TYPE=01` 的完整官方枚举定义。
- `MAX_DATE`、`pageHelp.cacheSize` 等参数的服务端内部定义。
- 除页面明确使用的四个字段之外，其余原始字段的正式业务含义。
- 所有节假日或特殊交易日的返回行为。

## 调研边界

本阶段只调查页面、JavaScript、真实 JSONP 请求、分页、字段和代表性历史日期。未编写 crawler/service，未写入 Parquet，未执行 backfill 或 incremental，也未修改任何现有业务代码。
