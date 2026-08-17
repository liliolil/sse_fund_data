# 上交所基金基础信息 / 产品列表数据源调研

## 1. 调研范围与结论

- 调研日期：2026-08-15（Asia/Shanghai）。
- 范围：上交所公开的 ETF、LOF、交易型货币基金、实时申赎货币基金、公募 REITs、基金管理公司以及基金做市商信息。
- 方法：检查上交所页面及其实际加载的 JavaScript，并对脚本中出现的接口进行少量真实 HTTP 请求。没有根据接口名猜测 URL 或字段。
- 本阶段只形成调研文档，没有实现 crawler、service 或 Parquet。

核心结论：**可以建立统一的上交所 `fund_master`**。新版基金网站的统一产品列表接口 `COMMON_JJZWZ_JJLB_L` 配合官方分类树 `COMMON_JJZWZ_JJLB_JJLX_C`，在一次当前快照中覆盖 ETF、LOF、交易型货币基金、实时申赎货币基金和公募 REITs。产品详情接口可以补充成立日期、基金法定全称和托管人；基金管理公司和做市商另有结构化接口。

不过，现有接口没有提供可靠的上市状态、退市日期、历史有效区间、币种和业绩比较基准。当前列表中 `fund_code` 唯一，不等于已经证明证券代码永远不会被历史复用。

状态标记含义：

- `verified`：本次已从官方脚本确认，并完成真实请求验证。
- `partially_verified`：接口或字段已验证，但覆盖范围、历史边界或业务语义仍有限制。
- `unverified`：本次没有得到真实接口字段支持。

## 2. 页面数据加载方式

| 页面 | 页面 URL | 数据来源 | 初始 HTML | Selenium |
|---|---|---|---|---|
| 新版基金产品列表 | https://etf.sse.com.cn/fundlist/ | XHR/JSONP：分类树和统一产品列表 | 只有表头/容器，无产品行 | 不需要 |
| 新版基金详情 | https://etf.sse.com.cn/fundlist/funddetail/index.shtml?fundid=510050 | XHR/JSONP：基金基本信息 | 只有字段占位 | 不需要 |
| 上交所基金列表 | https://www.sse.com.cn/assortment/fund/list/ | XHR/JSONP：`FUND_LIST`，不同页签传不同类型参数 | 无实际产品行 | 不需要 |
| ETF 列表 | https://www.sse.com.cn/assortment/fund/etf/list/ | 与上交所基金列表共用 `FUND_LIST` | 无实际产品行 | 不需要 |
| 基金管理公司列表 | https://www.sse.com.cn/assortment/fund/fundcompany/list/ | XHR/JSONP | 无实际公司行 | 不需要 |
| 基金做市商列表 | https://www.sse.com.cn/assortment/fund/jjzss/jjzsslb/ | XHR/JSONP，另有 Excel 下载 | 无实际做市商行 | 不需要 |
| 基金产品做市商列表 | https://www.sse.com.cn/assortment/fund/jjzss/jjcpzsslb/ | XHR/JSONP，另有 Excel 下载 | 无实际关系行 | 不需要 |

这些数据都可以用普通 HTTP 客户端获取，没有发现必须由 Selenium 执行浏览器脚本的环节。

## 3. 推荐主来源：新版统一基金产品列表

### 3.1 官方分类树

**状态：verified**

- 页面 URL：`https://etf.sse.com.cn/fundlist/`
- 接口 URL：`https://query.sse.com.cn/commonQuery.do`
- 请求方法：GET
- `sqlId`：`COMMON_JJZWZ_JJLB_JJLX_C`
- 参数：`CATEGORY_PARENT_CODE`；首层传 `F000`
- 分页：无；返回指定父节点的直接子节点
- 返回格式：JSONP（响应 `Content-Type` 为 `application/json;charset=UTF-8`）
- Referer：应使用新版基金列表页；本次不带 Referer 的真实请求得到 HTTP 200，但正文为 `success=false`、`ExceptionInterceptor` 系统错误
- Selenium：不需要
- 返回字段：`CATEGORY_CODE`、`CATEGORY_PARENT_CODE`、`CATEGORY_NAME`

本次验证到的官方分类树：

```text
F000
├─ F100 ETF
│  ├─ F110 股票ETF
│  │  ├─ F111 单市场股票（沪）ETF
│  │  ├─ F112 跨市场股票（沪深京）ETF
│  │  ├─ F113 跨市场股票（沪港深京）ETF
│  │  ├─ F114 单市场股票（科创板）ETF
│  │  └─ F115 跨市场股票（含科创板）ETF
│  ├─ F120 债券ETF
│  │  ├─ F121 单市场债券（沪）ETF
│  │  ├─ F122 跨市场债券（沪深）ETF
│  │  └─ F123 现金申赎类债券ETF
│  ├─ F130 跨境ETF
│  │  └─ F131 跨境ETF
│  ├─ F140 商品ETF
│  │  └─ F141 黄金ETF
│  └─ F150 交易型货币基金
├─ F200 上证LOF
│  ├─ F210 普通LOF
│  │  ├─ F211 股票型LOF
│  │  ├─ F212 债券型LOF
│  │  ├─ F213 混合型LOF
│  │  └─ F214 跨境型LOF
│  └─ F220 科创板相关LOF
├─ F400 实时申赎货币市场基金
└─ F600 REITs
```

这棵树是比基金代码前缀更可靠的官方产品类型来源。`F150` 在官方树中是 `F100 ETF` 的子类，但建立主数据时仍应保留“交易型货币基金”这一细分类型，不能只保存顶层 ETF。

### 3.2 统一产品列表

**状态：verified；推荐作为 `fund_master` 核心来源**

- 页面 URL：`https://etf.sse.com.cn/fundlist/`
- 接口 URL：`https://query.sse.com.cn/commonQuery.do`
- 请求方法：GET
- `sqlId`：`COMMON_JJZWZ_JJLB_L`
- 固定参数：`isPagination=true`、`type=inParams`
- 查询参数：
  - `FUND_CODE`
  - `COMPANY_NAME`
  - `INDEX_NAME`
  - `START_DATE`、`END_DATE`（页面按上市日期筛选，格式 `YYYYMMDD`）
  - `CATEGORY`（全量为 `F000`）
  - `SUBCLASS`
  - `SWING_TRADE`
  - 排序参数，如 `CATEGORY_ASC=1`、`FUND_CODE_ASC=1`
- 分页参数：`pageHelp.pageSize`、`pageHelp.pageNo`、`pageHelp.beginPage`、`pageHelp.cacheSize`、`pageHelp.endPage`
- 分页信息：`pageHelp.total`、`pageHelp.pageCount`
- 返回格式：JSONP
- Referer：需要；使用 `https://etf.sse.com.cn/fundlist/`
- Selenium：不需要
- 真实返回字段：
  - `FUND_CODE`
  - `FUND_ABBR`
  - `FUND_EXPANSION_ABBR`
  - `CATEGORY`
  - `COMPANY_CODE`
  - `COMPANY_NAME`
  - `INDEX_NAME`
  - `LISTING_DATE`
  - `SCALE`
  - `NUM`

实际响应结构示意（字段和值来自 510050 的真实响应）：

```json
{
  "pageHelp": {"total": 1, "pageCount": 1},
  "result": [{
    "FUND_CODE": "510050",
    "FUND_ABBR": "50ETF",
    "FUND_EXPANSION_ABBR": "上证50ETF华夏",
    "CATEGORY": "F111",
    "COMPANY_CODE": "900030",
    "COMPANY_NAME": "华夏基金管理有限公司",
    "INDEX_NAME": "上证50指数",
    "LISTING_DATE": "2005-02-23",
    "SCALE": "213.9432",
    "NUM": "1"
  }]
}
```

`SCALE` 的页面表头为“最新规模(亿元)”，但它属于随时间变化的快照值，建议作为来源特有字段或留在规模事实表，不作为静态主数据核心字段。

#### 当前快照覆盖和质量

用 `CATEGORY=F000` 真实查询得到 1,107 条，接口报告总数与实际返回数一致，1,107 个不同 `FUND_CODE`，当前快照没有重复代码。分类分布如下：

| 分类 | 数量 |
|---|---:|
| ETF（不含 F150 交易型货币基金） | 893 |
| 交易型货币基金 F150 | 24 |
| 上证 LOF | 119 |
| 实时申赎货币市场基金 F400 | 10 |
| REITs F600 | 61 |
| 合计 | 1,107 |

当前快照字段缺失情况：`FUND_CODE`、`FUND_ABBR`、`CATEGORY`、`COMPANY_CODE`、`COMPANY_NAME` 和 `SCALE` 均无空值；`FUND_EXPANSION_ABBR` 有 10 条为空或 `-`，`LISTING_DATE` 有 9 条为空或 `-`，`INDEX_NAME` 有 222 条为空或 `-`。缺失主要说明字段不适用于所有类型或来源未提供，不能用猜测值补齐。

### 3.3 产品列表 Excel

**状态：verified；适合作为人工核对或原始快照备份，不建议替代 JSONP 主采集**

- URL：`https://query.sse.com.cn/commonExcelDd.do`
- 请求方法：GET
- `sqlId`：`COMMON_JJZWZ_JJLB_L`
- 参数：与统一产品列表的筛选参数相同，另传 `isPagination=false`
- 返回：旧版二进制 Excel `.xls`，本次响应为 `application/vnd.ms-excel`，文件头 `D0 CF 11 E0 A1 B1 1A E1`
- 510050 筛选请求真实下载 4,608 字节，文件名 `fundDataList.xls`
- Referer：使用新版基金列表页
- Selenium：不需要

## 4. 产品详情来源

**状态：verified；用于按基金代码补充静态字段**

- 页面 URL：`https://etf.sse.com.cn/fundlist/funddetail/index.shtml?fundid={fund_code}`
- 接口 URL：`https://query.sse.com.cn/commonQuery.do`
- 请求方法：GET
- `sqlId`：`COMMON_JJZWZ_JJLB_JJXQ_JBXX_C`
- 参数：`FUND_CODE={fund_code}`；空代码请求真实返回系统错误，因此不能作为批量全量接口
- 分页：无，每次一个基金代码
- 返回格式：JSONP
- Referer：需要，建议使用基金详情页或新版基金列表页
- Selenium：不需要
- 真实返回字段：
  - `FUND_CODE`
  - `FUND_NAME`（基金法定全称，不是扩位简称）
  - `FUND_TYPE`
  - `COMPANY_NAME`
  - `FUND_MANAGER`（基金经理个人姓名；REIT 样本返回管理公司名）
  - `TRUSTEE_NAME`
  - `ESTABLISH_DATE`
  - `LISTING_DATE`
  - `INDEX_NAME`
  - `SCALE`
  - `MANAGEMENT_RATE`
  - `TRUSTEESHIP_RATE`

该详情接口虽然位于 ETF 网站，但本次真实验证对 ETF、LOF、REITs、交易型货币基金和实时申赎货币基金样本均返回数据。它适合作为按代码补充字段的来源，但全量 1,107 只基金意味着约 1,107 次请求；正式实现应缓存且只为新基金/缺失字段调用，不应每天全量重查。

## 5. 上交所主站的产品列表（第二官方来源）

**状态：verified；适合作为补充字段及交叉核对来源**

- 页面 URL：`https://www.sse.com.cn/assortment/fund/list/`
- 接口 URL：`https://query.sse.com.cn/commonSoaQuery.do`
- 请求方法：GET（页面的个别代码路径会声明 POST/JSONP，但本次 GET 已真实返回数据）
- `sqlId`：`FUND_LIST`
- 分页参数：`isPagination=true` 及标准 `pageHelp.*` 参数
- 分页信息：`pageHelp.total`、`pageHelp.pageCount`
- 返回格式：JSONP
- Referer：需要；使用上交所基金列表页
- Selenium：不需要
- 真实返回字段：
  - `fundCode`
  - `fundAbbr`
  - `secNameFull`（扩位简称）
  - `fundType`
  - `subClass`
  - `companyName`
  - `fundManager`
  - `listingDate`
  - `INDEX_CODE`
  - `INDEX_NAME`
  - `TRUSTEE_NAME`
  - `LAW_FIRM`
  - `CONTACT_MOBILE`

官方前端使用的类型参数及本次结果：

| 页面类型 | 参数 | 本次总数 | 状态 |
|---|---|---:|---|
| ETF（不含交易型货币基金） | `fundType=00`，`subClass=01,02,03,04,06,08,09,31,32,33,34,35,36,37,38` | 893 | verified |
| 公募 REITs | `fundType=50` | 61 | verified |
| 交易型货币基金 | `fundType=00`，`subClass=05,07` | 24 | verified |
| LOF | `fundType=10`，`subClass=11,14,15` | 119 | verified |
| 封闭式基金 | `fundType=40` | 0 | partially_verified：接口和参数已验证，当前无记录，未证明历史覆盖 |
| 分级 LOF | `fundType=10`，`subClass=12,13` | 0 | partially_verified：当前无记录 |
| 20% 涨跌幅比例基金 | `subClass=09,15,31` | 153 | verified；这是跨 ETF/LOF 的筛选属性，不是互斥主类型 |
| 当日回转交易基金 | `swingTrade=是` | 206 | verified；这是筛选属性，不是互斥主类型 |

这一接口比新版统一列表多出 `INDEX_CODE`、`TRUSTEE_NAME`、律师事务所、联系电话和基金经理等字段；但缺少 `COMPANY_CODE` 和 `ESTABLISH_DATE`，产品类型仍是旧的 `fundType/subClass` 编码。因此建议把它作为补充证据，不要与新版 `CATEGORY` 编码互相覆盖。

## 6. 实时申赎货币基金专用来源

**状态：verified；属于“其他上交所基金产品”的补充来源**

- 页面 URL：`https://www.sse.com.cn/assortment/fund/list/?tabActive=2`
- 接口 URL：`https://query.sse.com.cn/commonQuery.do`
- 请求方法：GET
- `sqlId`：`COMMON_SSE_ZQPZ_JJLB_SSSSHBJJLB_CPJBXX_L`
- 参数：`isPagination=false`、`FUND_TYPE=30`
- 分页：无
- 返回格式：JSONP
- Referer：使用上交所基金列表页
- Selenium：不需要
- 本次真实结果：5 条业务记录
- 真实返回字段：`FUND_CODE`、`FUND_ABBREVIATION`、`COMPANY_NAME`、`FILE_DATE`、`TRADEDATE`、`BUY_LIMIT`、`BUY_LIMIT_SUM`、`SELL_LIMIT`、`SELL_LIMIT_SUM`、`ONEBUY_LIMIT`、`ONEBUY_LIMIT_SUM`、`ONESELL_LIMIT`、`ONESELL_LIMIT_SUM`、`OTHERS`、`NUM`

样本 519800 返回简称“保证金A”、管理公司“华夏基金管理有限公司”、`FILE_DATE=20260814`、`TRADEDATE=2026/08/14`。该接口偏向当日交易/申赎参数，不提供上市日期和扩位简称。统一产品列表同一时点有 10 个 F400 代码，不能把专用接口的 5 条当作完整主数据全集。

## 7. 基金管理公司来源

**状态：verified；管理人代码关系为 partially_verified**

- 页面 URL：`https://www.sse.com.cn/assortment/fund/fundcompany/list/`
- 接口 URL：`https://query.sse.com.cn/commonQuery.do`
- 请求方法：GET
- `sqlId`：`COMMON_SSE_SJ_HYTJSJ_HYLB_HYXX_L`
- 参数：
  - `isPagination=true`
  - 标准 `pageHelp.*`
  - `FULL_NAME`（名称筛选）
  - `CMP_TYPE=2`
  - `FULL_NAME_ASC=1`
- 分页：有；本次总数 115，`pageSize=5` 时 `pageCount=23`
- 返回格式：JSONP
- Referer：需要；使用基金管理公司列表页
- Selenium：不需要
- 真实返回字段：
  - `COMPANY_CODE`
  - `FULL_NAME`
  - `FULL_NAME_EN`
  - `PRESIDENT_NAME`
  - `REGISTER_CAPITAL`
  - `ADDRESS`
  - `ZIP_CODE`
  - `COMP_TEL`
  - `COMP_FAX`
  - `HOMEPAGE`
  - `LINKMAN_NAME`
  - `LINKMAN_TEL`
  - `NUM`

华夏基金真实样本：`COMPANY_CODE=900030`、`FULL_NAME=华夏基金管理有限公司`、`HOMEPAGE=www.chinaamc.com`。页面注明该公司列表只针对在上交所挂牌交易的基金进行统计，不应视为中国全部公募基金管理人名录。

管理人到产品的关系可以从统一产品列表的 `COMPANY_CODE`、`COMPANY_NAME` 获得；但不能假定代码始终可直接连接：115 家公司中 41 家的 `COMPANY_CODE` 为 `-`，产品列表出现的 69 个有效管理公司代码中有 7 个未出现在该公司列表的有效代码集合。正式实现应同时保留代码和原始名称，不能只依赖代码外键。

此外，`COMPANY_NAME` 是管理公司；`FUND_MANAGER` 通常是基金经理个人。两者不应都映射成含糊的 `manager_name`。

## 8. 基金做市商 / 产品做市关系

### 8.1 做市商机构列表

**状态：verified**

- 页面 URL：`https://www.sse.com.cn/assortment/fund/jjzss/jjzsslb/`
- 接口 URL：`https://query.sse.com.cn/commonQuery.do`
- 请求方法：GET
- `sqlId`：`COMMON_SSE_CP_JJ_JJZSSLB_JJZSSLB`
- 参数：`isPagination=true` 及标准 `pageHelp.*`
- 分页：有；本次总数 34
- 返回格式：JSONP
- Referer：需要
- Selenium：不需要
- 真实返回字段：`FIRM_CODE`、`FIRM_NAME`、`FIRM_TYPE`、`PRODUCT_TYPE`、`QUALIFY_TYPE`、`ZS_TYPE`、`ORDER_NUM`、`NUM`

### 8.2 基金产品做市商关系

**状态：verified；有效日期 unsupported**

- 页面 URL：`https://www.sse.com.cn/assortment/fund/jjzss/jjcpzsslb/`
- 接口 URL：`https://query.sse.com.cn/commonQuery.do`
- 请求方法：GET
- `sqlId`：`COMMON_SSE_CP_JJ_JJZSSLB_JJCPZSSLB`
- 参数：
  - `securityCode`
  - `firmName`
  - `isPagination=true`
  - 标准 `pageHelp.*`
- 分页：有；不能写死页数
- 返回格式：JSONP
- Referer：需要
- Selenium：不需要
- 真实返回字段：`SECURITY_CODE`、`SEC_NAME_CN`、`SEC_NAME_FULL`、`FIRM_NAME`、`SERVICE_TYPE`、`NUM`

510050 真实返回 19 条关系，其中 `SERVICE_TYPE=主` 17 条、`一般` 2 条。其他样本：510300 为 22 条、513500 为 4 条、588200 为 12 条、508000 为 8 条、511600 为 4 条；LOF 样本 501047 返回 0 条。说明接口并不只覆盖普通股票 ETF，但不能据此推断所有基金类型都有做市商。

接口没有返回 `effective_date`、终止日期或关系历史，因此只能形成“当前公开关系快照”。`effective_date` 应标记为 `unsupported`，不能用抓取日期伪装成生效日期。做市关系是一对多表，建议未来单独保存为 `fund_market_maker`，而不是把多个做市商塞进 `fund_master` 的单个字段。

### 8.3 做市商 Excel

- 做市商列表：`https://query.sse.com.cn/commonExcelDd.do?sqlId=COMMON_SSE_CP_JJ_JJZSSLB_JJZSSLB`
- 产品做市商：`https://query.sse.com.cn/commonExcelDd.do?sqlId=COMMON_SSE_CP_JJ_JJZSSLB_JJCPZSSLB`
- 本次按 510050 下载产品做市关系成功：HTTP 200，`.xls`，6,144 字节，文件名 `jjcpzss.xls`
- 状态：verified；适合作为人工核对或原始快照备份

## 9. 必选真实样本验证

| 类型 | 代码 | 分类/类型 | 简称 | 扩位简称 | 上市日期 | 管理公司 | 详情接口 |
|---|---|---|---|---|---|---|---|
| ETF | 510050 | F111 单市场股票（沪）ETF | 50ETF | 上证50ETF华夏 | 2005-02-23 | 华夏基金管理有限公司 | 成功 |
| ETF | 510300 | F112 跨市场股票（沪深京）ETF | 300ETF | 沪深300ETF华泰柏瑞 | 2012-05-28 | 华泰柏瑞基金管理有限公司 | 成功 |
| 跨境 ETF | 513500 | F131 跨境ETF | 标普500 | 标普500ETF博时 | 2014-01-15 | 博时基金管理有限公司 | 成功 |
| 科创板 ETF | 588200 | F114 单市场股票（科创板）ETF | 科创芯片 | 科创芯片ETF嘉实 | 2022-10-26 | 嘉实基金管理有限公司 | 成功 |
| LOF | 501047 | F211 股票型LOF | 全指证券 | 证券公司LOF | 2018-01-18 | 汇添富基金管理股份有限公司 | 成功 |
| REITs | 508000 | F600 REITs | 张江REIT | 华安张江产业园REIT | 2021-06-21 | 华安基金管理有限公司 | 成功 |
| 交易型货币基金 | 511600 | F150 交易型货币基金 | 货币ETF | 华安日日鑫ETF | 2016-09-27 | 华安基金管理有限公司 | 成功 |
| 实时申赎货币基金 | 519800 | F400 实时申赎货币市场基金 | 保证金A | `-` | `-` | 华夏基金管理有限公司 | 成功 |

详情接口还验证了成立日期，例如：510050 为 2004-12-30、501047 为 2017-12-04、508000 为 2021-06-07、511600 为 2016-08-30。519800 的成立日期和上市日期返回 `-`，不可自行补值。

## 10. 字段可得性与建议映射

| 目标字段 | 状态 | 推荐来源与原始字段 | 说明 |
|---|---|---|---|
| `fund_code` | verified | 统一列表 `FUND_CODE` | 必须保持字符串 |
| `fund_name` | verified | 统一列表 `FUND_ABBR` | 页面“基金简称” |
| `fund_expand_name` | verified | 统一列表 `FUND_EXPANSION_ABBR` | 10 条当前为空/`-` |
| `fund_legal_name` | verified | 详情 `FUND_NAME` | 法定全称，和扩位简称不同 |
| `fund_type_code` | verified | 统一列表 `CATEGORY` | 保存官方原始代码 |
| `fund_type_name` | verified | 分类树 `CATEGORY_NAME` | 通过分类树解析，不按代码前缀猜 |
| `product_type` | verified | 分类树层级 | 建议保留顶层和叶子层级 |
| `market` | partially_verified | 来源上下文常量 `SSE` | 接口没有显式 `market` 字段，应标记为来源派生 |
| `list_date` | verified | 统一列表 `LISTING_DATE` / 详情 `LISTING_DATE` | 当前 9 条为空或 `-` |
| `establish_date` | verified | 详情 `ESTABLISH_DATE` | 需要逐基金查询，部分为 `-` |
| `management_company_code` | verified | 统一列表 `COMPANY_CODE` | 与公司列表连接不完全 |
| `management_company_name` | verified | 统一列表 `COMPANY_NAME` | 建议保留原始名称 |
| `fund_manager_person` | verified | 详情/旧列表 `FUND_MANAGER` | REIT 样本返回公司名，语义有类型差异 |
| `underlying_index_name` | verified | 统一列表 `INDEX_NAME` | 非指数产品可为空/`-` |
| `underlying_index_code` | verified | 旧列表 `INDEX_CODE` | 新版统一列表没有该字段 |
| `custodian` | verified | 详情 `TRUSTEE_NAME` 或旧列表 `TRUSTEE_NAME` | 部分产品可能为 `-` |
| `benchmark` | unverified | 无 | 不能用标的指数替代业绩比较基准 |
| `status` | unverified | 无 | 当前列表存在性不等于正式上市状态字段 |
| `delist_date` | unverified | 无 | 未发现历史/退市字段 |
| `currency` | unverified | 无 | 未发现币种字段 |
| `market_maker` | verified | 产品做市商 `FIRM_NAME` | 应存一对多关系表 |
| `service_type` | verified | 产品做市商 `SERVICE_TYPE` | 当前值含“主”“一般” |
| `market_maker_effective_date` | unsupported | 无 | 不可用采集日期替代 |

### 建议的 `fund_master` 字段分层

**必填核心字段**

- `market`（来源派生为 `SSE`）
- `fund_code`
- `fund_name`
- `fund_type_code`
- `fund_type_name`
- `management_company_name`
- `source`
- `source_updated_at` 或 `observed_at`

**可选字段**

- `fund_expand_name`
- `fund_legal_name`
- `list_date`
- `establish_date`
- `management_company_code`
- `fund_manager_person`
- `underlying_index_code`
- `underlying_index_name`
- `custodian`

**来源特有字段**

- 新版列表：`CATEGORY`、`SCALE`
- 旧列表：`fundType`、`subClass`、`LAW_FIRM`、`CONTACT_MOBILE`
- 详情：`MANAGEMENT_RATE`、`TRUSTEESHIP_RATE`
- 实时申赎货币专用接口：交易/申赎限额和 `FILE_DATE`、`TRADEDATE`

所有接口原始代码和原始字段应保留，标准化字段不能覆盖来源证据。

## 11. 主键与历史风险

本次 1,107 条当前快照中，`FUND_CODE` 全部非空且没有重复，因此在“仅上交所当前产品”范围内，`fund_code` 可作为自然键。

但有以下未验证风险：

1. 接口没有退市产品历史和有效期，不能证明代码从未或永不复用。
2. 如果未来纳入深交所或其他市场，仅使用 `fund_code` 不能表达市场归属。
3. 产品类型可能随官方分类维护发生变化，不能把分类名称硬编码为永恒属性。

因此正式表建议采用 `(market, fund_code)` 作为业务唯一键，同时保留内部稳定的 `fund_id`（可由系统生成）和快照/版本字段。若只实现 SSE 第一阶段，可以对 `fund_code` 建唯一约束，但应在设计中保留未来迁移到复合键的空间。

## 12. Referer、错误页和请求安全

本次分别对统一产品列表、产品详情、基金管理公司、产品做市商接口做了无 Referer 请求。它们均返回 HTTP 200，但正文只有约 128 字节，并报告：

```json
{"success":"false","error":"System Error, Please try again later...","errorType":"ExceptionInterceptor"}
```

因此正式实现不能只检查 HTTP 200；必须：

1. 设置对应官方页面 Referer；
2. 验证 JSONP 外壳；
3. 验证 `success`/`error`；
4. 验证 `result` 和分页信息；
5. 对错误页或系统错误明确抛错，不能当作空结果。

## 13. 历史能力和上市状态边界

- 统一产品列表的 `START_DATE`/`END_DATE` 是页面上的上市日期筛选参数，**不是历史时点查询**。
- 当前产品列表可用于发现新上市产品和更新当前基础信息，但没有验证到“按某个过去日期恢复当时全量产品状态”的能力。
- 旧 `FUND_LIST` 当前对封闭式基金、分级 LOF 返回 0，不能据此断言历史上不存在，也不能把它当作退市历史接口。
- 做市商关系同样只有当前快照，没有生效/终止日期。
- 因而未来的历史主数据需要从首次采集起自行保存快照/变更记录；现有官方接口不足以完整回填历史状态。

## 14. 推荐下一阶段实现方案

1. 以 `COMMON_JJZWZ_JJLB_L` 的 `CATEGORY=F000` 做统一核心全量分页，按 `pageHelp.total/pageCount` 停止，不写死 1,107 条。
2. 同步抓取 `COMMON_JJZWZ_JJLB_JJLX_C` 分类树，保存官方代码和名称；类型映射由树生成，不按六位代码前缀判断。
3. 用 `(market='SSE', fund_code)` 做业务键，保留原始记录 JSON；先完成当前快照和增量发现。
4. 只对新增基金或关键字段缺失的基金调用 `COMMON_JJZWZ_JJLB_JJXQ_JBXX_C`，补充法定全称、成立日期、托管人等，避免每日 1,107 次详情请求。
5. 用旧 `FUND_LIST` 批量补充/交叉核对 `INDEX_CODE`、`TRUSTEE_NAME`、`fundType/subClass`；不要让旧分类覆盖新版 `CATEGORY`。
6. 基金管理公司建立独立维表。连接时优先保留 `COMPANY_CODE`，同时以原始公司名作核对和后备，不能假定代码全集完整。
7. 做市商建立独立的一对多关系表，例如 `fund_market_maker`，字段至少为 `fund_code`、`firm_name`、`service_type`、`observed_at`；不要制造 `effective_date`。
8. 每次采集保留抓取时间和数据质量报告。通过新旧快照差异发现新增、名称/类型/管理人变化；接口没有明确状态时，不要自动把“本轮未出现”立即解释为退市。
9. 初版 `fund_master` 对 `status`、`currency`、`benchmark`、`delist_date` 保持空值并标记来源未验证；后续另行调研这些字段的官方来源。

## 15. 已验证、部分验证和未验证汇总

### verified

- 新版统一产品列表、官方分类树、产品详情均可通过 GET JSONP 获取。
- ETF、LOF、交易型货币基金、实时申赎货币基金和 REITs 可由同一新版列表接口统一获取，并由官方 `CATEGORY` 区分。
- 510050、510300、513500、588200、501047、508000、511600、519800 样本均验证成功。
- 基金代码、简称、扩位简称、分类、上市日期、管理公司、成立日期、标的指数名称、托管人等字段有真实来源。
- 基金管理公司列表、做市商机构列表和基金—做市商关系均有公开结构化接口。
- JSONP 接口不需要 Selenium；Referer 和业务错误校验是必要的。

### partially_verified

- `market='SSE'` 来自数据源上下文，不是接口显式字段。
- 管理公司代码可用于多数连接，但公司列表存在 `-` 代码且与产品列表代码集合不完全一致。
- 旧接口支持封闭式基金和分级 LOF 参数，但当前返回 0，历史覆盖未验证。
- 产品详情跨多种基金类型的样本已成功，但没有完成全部 1,107 只的覆盖率审计。
- 当前列表中的 `fund_code` 唯一，但历史代码复用风险未验证。

### unverified / unsupported

- 正式上市状态、退市日期、历史有效区间。
- 币种、业绩比较基准。
- 基金产品历史全量快照和最早可追溯日期。
- 做市关系生效日期和终止日期。
- 通过当前接口完整恢复已退市封闭式基金、分级 LOF 等历史产品。
