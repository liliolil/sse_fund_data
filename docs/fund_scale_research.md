# 上交所 LOF 与交易型货币基金规模数据源调查

调查日期：2026-08-14（Asia/Shanghai）

## 调查结论

上交所“LOF规模统计”和“交易型货币基金规模”页面均存在页面实际调用的公开数据接口。两个页面都在页面加载后通过 `<script>` 资源发起跨域 **JSONP GET** 请求：

1. `commonQuery.do` 返回规模/份额数据及分页信息；
2. `queryExpandName.do` 根据当前页证券代码补充基金扩位简称。

数据不是直接写在初始 HTML 中，不是 XHR/Fetch，也不是 Excel、CSV 或其他数据文件下载。两个页面均不需要 Selenium。

## 数据来源类型汇总

| 页面 | 初始 HTML | XHR / Fetch | JSON / JSONP | Excel / CSV | 其他文件 | 需要 Selenium |
| --- | --- | --- | --- | --- | --- | --- |
| LOF规模统计 | 否，初始页面主要是结构 | 否 | 是，JSONP | 未发现 | 未发现 | 否 |
| 交易型货币基金规模 | 否，初始页面主要是结构 | 否 | 是，JSONP | 未发现 | 未发现 | 否 |

判断依据：浏览器实际加载资源中，两个业务接口的资源类型均为 `script`，请求都带有 `jsonCallBack=jsonpCallback...`；页面最终表格有非空真实记录。页面未显示 Excel、CSV、导出或数据文件下载入口。

---

## 一、LOF 规模

### 页面

- 页面名称：LOF规模统计
- 页面 URL：<https://www.sse.com.cn/market/funddata/volumn/lofvolumn/>
- 页面字段：交易日期、基金代码、基金扩位简称、基金规模（万份）

### 主数据接口

- 基础 URL：<https://query.sse.com.cn/commonQuery.do>
- 请求方法：`GET`
- 返回格式：JSONP（JavaScript 回调包裹分页 JSON）
- `sqlId`：`COMMON_SSE_SJ_JJSJ_JJGM_LOFGMTJ_L`
- 日期参数：`SEARCH_DATE`
- 分页：是

2026-08-14 在浏览器中捕获并成功执行的首屏真实请求：

```text
https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback31877328&isPagination=true&sqlId=COMMON_SSE_SJ_JJSJ_JJGM_LOFGMTJ_L&PRODUCT_TYPE=11%2C14%2C15&SEARCH_DATE=&type=inParams&pageHelp.pageSize=25&pageHelp.pageCount=50&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&_=1786679374511
```

#### 参数

| 参数 | 捕获值 | 说明 |
| --- | --- | --- |
| `jsonCallBack` | `jsonpCallback31877328` | JSONP 回调名；数字每次可能变化。 |
| `isPagination` | `true` | 启用分页。 |
| `sqlId` | `COMMON_SSE_SJ_JJSJ_JJGM_LOFGMTJ_L` | LOF 规模查询标识，来自真实请求。 |
| `PRODUCT_TYPE` | `11,14,15` | 页面真实请求传入的产品类型集合；各数字的业务含义本次**未验证**，不根据名称猜测。 |
| `SEARCH_DATE` | 空字符串 | 日期查询参数；空值时页面返回最近可用数据。历史查询的具体输入格式本次**未验证**。 |
| `type` | `inParams` | 页面真实请求中的参数。其内部语义本次**未验证**。 |
| `pageHelp.pageSize` | `25` | 每页条数。 |
| `pageHelp.pageCount` | `50` | 页面请求携带的分页辅助值；不能将其视为实际总页数，具体语义**未验证**。 |
| `pageHelp.pageNo` | `1` | 当前页码。 |
| `pageHelp.beginPage` | `1` | 分页辅助参数。 |
| `pageHelp.cacheSize` | `1` | 分页辅助参数。 |
| `pageHelp.endPage` | `1` | 分页辅助参数。 |
| `_` | `1786679374511` | 毫秒时间戳/缓存破坏参数，不是业务筛选条件。 |

### 扩位简称接口

- 基础 URL：<https://query.sse.com.cn/security/stock/queryExpandName.do>
- 请求方法：`GET`
- 返回格式：JSONP
- `sqlId`：无

首屏真实请求：

```text
https://query.sse.com.cn/security/stock/queryExpandName.do?jsonCallBack=jsonpCallback3650705&secCodes=501001%2C501005%2C501006%2C501007%2C501008%2C501009%2C501010%2C501011%2C501012%2C501015%2C501016%2C501017%2C501018%2C501019%2C501021%2C501022%2C501023%2C501025%2C501026%2C501028%2C501029%2C501030%2C501031%2C501032%2C501036&_=1786679374512
```

| 参数 | 说明 |
| --- | --- |
| `jsonCallBack` | JSONP 回调名。 |
| `secCodes` | 当前页基金代码，以逗号分隔；URL 编码后逗号为 `%2C`。 |
| `_` | 毫秒时间戳/缓存破坏参数。 |

### 真实返回验证

主接口和扩位简称接口执行后，页面成功渲染非空数据。首条真实记录为：

```text
交易日期：20260813
基金代码：501001
基金扩位简称：财通精选混合LOF
基金规模（万份）：582.32
```

返回传输格式已确认是 JSONP。其概念结构如下：

```javascript
jsonpCallback31877328({
  "pageHelp": {
    "data": [
      { /* LOF 规模原始记录 */ }
    ]
  }
})
```

本次工具能确认真实请求 URL、JSONP 外层、分页结构和页面解码后的业务值，但未导出跨域脚本的原始响应正文。因此，接口原始字段名仍为**未验证**，本文不使用中文页面列名冒充原始字段名。

---

## 二、交易型货币基金规模

### 页面

- 页面名称：交易型货币基金规模
- 页面 URL：<https://www.sse.com.cn/market/funddata/volumn/tcuvolumn/>
- 页面字段：日期、基金代码、基金扩位简称、总份额（万份）

### 主数据接口

- 基础 URL：<https://query.sse.com.cn/commonQuery.do>
- 请求方法：`GET`
- 返回格式：JSONP（JavaScript 回调包裹分页 JSON）
- `sqlId`：`COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_JYXJJ_SEARCH_L`
- 日期参数：`STAT_DATE`
- 分页：是

2026-08-14 在浏览器中捕获并成功执行的首屏真实请求：

```text
https://query.sse.com.cn/commonQuery.do?jsonCallBack=jsonpCallback4193545&isPagination=true&pageHelp.pageSize=25&pageHelp.pageCount=50&pageHelp.pageNo=1&pageHelp.beginPage=1&pageHelp.cacheSize=1&pageHelp.endPage=1&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_JYXJJ_SEARCH_L&STAT_DATE=&_=1786679446037
```

#### 参数

| 参数 | 捕获值 | 说明 |
| --- | --- | --- |
| `jsonCallBack` | `jsonpCallback4193545` | JSONP 回调名；数字每次可能变化。 |
| `isPagination` | `true` | 启用分页。 |
| `sqlId` | `COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_JYXJJ_SEARCH_L` | 交易型货币基金规模查询标识，来自真实请求。 |
| `STAT_DATE` | 空字符串 | 日期查询参数；空值时页面返回最近可用数据。历史查询的具体输入格式本次**未验证**。 |
| `pageHelp.pageSize` | `25` | 每页条数。 |
| `pageHelp.pageCount` | `50` | 页面请求携带的分页辅助值；不能将其视为实际总页数，具体语义**未验证**。 |
| `pageHelp.pageNo` | `1` | 当前页码。 |
| `pageHelp.beginPage` | `1` | 分页辅助参数。 |
| `pageHelp.cacheSize` | `1` | 分页辅助参数。 |
| `pageHelp.endPage` | `1` | 分页辅助参数。 |
| `_` | `1786679446037` | 毫秒时间戳/缓存破坏参数。 |

### 扩位简称接口

- 基础 URL：<https://query.sse.com.cn/security/stock/queryExpandName.do>
- 请求方法：`GET`
- 返回格式：JSONP
- `sqlId`：无

首屏真实请求：

```text
https://query.sse.com.cn/security/stock/queryExpandName.do?jsonCallBack=jsonpCallback30996588&secCodes=511600%2C511620%2C511650%2C511660%2C511670%2C511690%2C511700%2C511770%2C511800%2C511810%2C511820%2C511830%2C511850%2C511860%2C511880%2C511900%2C511910%2C511920%2C511930%2C511950%2C511960%2C511970%2C511980%2C511990&_=1786679446038
```

参数含义与 LOF 页面名称接口相同：`jsonCallBack` 为回调名，`secCodes` 为当前页代码集合，`_` 为缓存破坏时间戳。

### 真实返回验证

两个接口执行后，页面成功渲染 24 条非空记录。首条真实记录为：

```text
日期：2026-08-13
基金代码：511600
基金扩位简称：华安日日鑫ETF
总份额（万份）：82.82
```

返回传输格式已确认是 JSONP，概念结构为 `jsonpCallback4193545({"pageHelp":{"data":[...]}})`。原始响应字段名本次**未验证**，不根据页面列名猜测。

---

## 三、能否复用 ETF 规模抓取逻辑

### 可以复用的部分

三类页面（ETF、LOF、交易型货币基金）可以共享以下基础逻辑：

- 使用普通 HTTP `GET` 请求；
- 调用 `https://query.sse.com.cn/commonQuery.do`；
- 生成 JSONP 回调名并移除回调外壳，再用标准 JSON 解析器解析；
- 按 `pageHelp.pageNo` 和响应分页元数据遍历，不写死页数；
- 按每页基金代码批量调用 `queryExpandName.do` 补充扩位简称；
- 设置合理的 `Referer`、`User-Agent`、超时、重试和低请求频率；
- 分开保存原始响应和清洗结果。

### 不能直接照搬的部分

应为不同数据源保留独立配置和字段映射：

| 项目 | ETF规模 | LOF规模 | 交易型货币基金规模 |
| --- | --- | --- | --- |
| `sqlId` | `COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L` | `COMMON_SSE_SJ_JJSJ_JJGM_LOFGMTJ_L` | `COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_JYXJJ_SEARCH_L` |
| 日期参数 | `STAT_DATE` | `SEARCH_DATE` | `STAT_DATE` |
| 额外参数 | 无已确认业务参数 | `PRODUCT_TYPE=11,14,15`、`type=inParams` | 无已确认业务参数 |
| 页面日期显示 | `YYYY-MM-DD` | `YYYYMMDD` | `YYYY-MM-DD` |
| 规模列 | 总份额（万份） | 基金规模（万份） | 总份额（万份） |

结论：**可以复用传输、JSONP 解析、分页和名称补充的公共框架，但不能复用同一套请求参数或未经验证的字段映射。** LOF 尤其需要独立处理 `SEARCH_DATE`、`PRODUCT_TYPE` 和 `type`。

## 是否需要 Selenium

**LOF 和交易型货币基金都不需要 Selenium。** 页面已经暴露并实际使用公开 GET JSONP 接口，没有登录、验证码或必须由浏览器完成的交互。正式实现应优先使用 `requests` 或 `httpx`。

## 已验证与未验证

### 已验证

- 两个页面 URL、页面标题和最终表格列。
- 两个主接口和两个扩位简称接口均为页面真实网络请求，不是猜测。
- 请求方法为 GET，资源形态为 JSONP `script`，不是 XHR/Fetch。
- 两个 `sqlId`、日期参数名、分页参数名及首屏捕获值。
- 两个页面均返回并渲染了最近交易日的非空真实数据。
- 页面未依赖 Excel、CSV 或其他数据文件下载，也不需要 Selenium。
- 两类数据可以复用 ETF 抓取框架的范围及必须独立配置的差异。

### 仍未验证

- 两个主接口原始响应中的确切字段名和字段类型；当前只验证了页面解码后的业务值。
- 历史日期参数的确切输入格式及可查询的最早日期。
- `PRODUCT_TYPE=11,14,15` 各枚举值的正式业务定义。
- `type=inParams` 和请求中的 `pageHelp.pageCount=50` 的内部语义。
- 直接 HTTP 客户端调用时，`Referer`、`User-Agent` 等请求头中哪些是服务端硬性要求。
- 高频限制、长期稳定性和批量历史回填表现；本次按要求未做批量抓取或正式开发。

## 推荐实现方向（仅调研结论）

正式开发时可建立一个轻量的 JSONP 分页请求公共模块，并为 ETF、LOF、交易型货币基金分别提供 `sqlId`、日期参数、额外参数和字段映射配置。解析原始字段前应先保存并检查一次接口原始响应，未验证字段不得进入正式映射。本次调查到此结束，不进入爬虫开发。
