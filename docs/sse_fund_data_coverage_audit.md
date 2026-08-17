# 上交所基金公开数据覆盖缺口审计

调研日期：2026-08-15

## 1. 审计口径与结论摘要

本次审计以当前项目源码、既有调研文档、上交所官方页面、页面实际加载的 JavaScript，以及对官方 JSON/JSONP/XML 接口的少量真实 HTTP 请求为依据。页面上出现一个栏目，不等于存在一个应单独采集的数据集；只有能确认真实数据来源、且与项目已有表不重复时，才计为覆盖缺口。

状态定义：

- `implemented`：已有正式 crawler/service/存储或对应正式能力。
- `partially_implemented`：核心来源已接入，但分类、字段或历史能力仍不完整。
- `researched_only`：真实接口已经验证，但尚无正式模块。
- `not_implemented`：存在真实、独立且可采集的数据，但项目尚未实现。
- `not_worth_collecting`：可见或可查，但重复、过时或维护价值很低。
- `unsupported`：目前没有验证到稳定公开数据，或接口在代表日期始终为空。

结论：当前项目已覆盖 **12 类核心数据能力**：四类规模、基金成交汇总、ETF PCF、公告、XBRL 元数据、XBRL/PDF 关联、基金主数据、基金管理公司、基金做市商。按“独立且不与现有表重复”的口径，本次确认 **11 个尚未正式实现的数据集**，其中 P0 4 个、P1 4 个、P2 3 个；另有 2 项属于现有 PCF 模块的部分覆盖缺口，不应新建重复 crawler。

最高价值缺口是基金净值：LOF 净值和 REITs 净值均有官方结构化接口、可验证历史数据，却尚无正式存储模块。若只再实现一个模块，建议做统一 `fund_nav`（内部保留 LOF、REITs 两个数据源适配器）。

## 2. 审计方法与证据等级

### 2.1 使用的官方入口

- [基金市场首页](https://www.sse.com.cn/assortment/fund/)
- [基金产品列表](https://www.sse.com.cn/assortment/fund/list/)
- [基金公告](https://www.sse.com.cn/disclosure/fund/announcement/)
- [ETF 申购赎回清单](https://www.sse.com.cn/disclosure/fund/etflist/)
- [LOF 净值](https://www.sse.com.cn/assortment/fund/lof/netvalue/)
- [交易型货币基金每日申赎参数](https://www.sse.com.cn/assortment/fund/currencyfund/basicinfo/)
- [REITs 行情](https://www.sse.com.cn/assortment/fund/reits/market/)
- [REITs 净值](https://www.sse.com.cn/assortment/fund/reits/netvalue/)
- [REITs 发售与扩募](https://www.sse.com.cn/assortment/fund/reits/issue/)
- [REITs 产品详情](https://www.sse.com.cn/reits/assortment/prices/detail/price/)
- [分级 LOF 规模](https://www.sse.com.cn/market/funddata/volumn/fjlofvolumn/)
- [基金成交概况（日）](https://www.sse.com.cn/market/funddata/overview/day/)
- [基金规模：ETF](https://www.sse.com.cn/market/funddata/volumn/etfvolumn/)、[LOF](https://www.sse.com.cn/market/funddata/volumn/lofvolumn/)、[交易型货币基金](https://www.sse.com.cn/market/funddata/volumn/tcuvolumn/)、[REITs](https://www.sse.com.cn/market/funddata/volumn/reits/)

主要前端证据：

- `https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_fund_2021.js`
- `https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_fundInformation_2021.js`
- `https://www.sse.com.cn/xhtml/reits/js/search/search_hq.js`

### 2.2 验证原则

- `verified`：已从官方脚本确认请求，并至少执行一次真实请求取得非空响应。
- `partially_verified`：脚本和接口存在，但只验证了部分日期、产品或分支。
- `unverified`：尚未取得可证明语义的非空结果，不据此推荐实现。
- 页面脚本常把 JSONP 请求写为 `type: "post"`；浏览器 JSONP transport 和本次成功验证均为 HTTP GET，因此本文按实际网络行为记录为 GET。
- 本次没有使用 Selenium；已核实的数据源均可由普通 HTTP 请求访问。

## 3. 当前项目覆盖基线

| 当前能力 | 主要模块/产物 | 覆盖判断 |
|---|---|---|
| ETF、LOF、交易型货币基金、REITs 规模 | `etf_scale`、`lof_scale`、`money_market_scale`、`reits_scale` | `implemented` |
| 基金成交概况（日/周/月/年） | `fund_turnover` | `implemented`；这是全市场/分类汇总，不是逐基金 OHLC 行情 |
| ETF 最新 PCF、XML、header、components | `etf_pcf` | `implemented`，但历史 PCF 仍无已验证公开 URL |
| 基金公告与 PDF | `fund_announcements` | `implemented` |
| XBRL 元数据、增量、HTML、PDF 匹配 | `xbrl`、`xbrl_service`、PDF match | `implemented`/部分来源匹配能力 |
| 产品、公司、做市商 | `fund_master`、`fund_companies`、`fund_market_makers` | `implemented`；做市商主要是当前关系快照 |

CLI、watch 和日志是运行基础设施，不作为新增数据集计数。

## 4. 已确认的重要未覆盖数据源

### 4.1 P0：LOF 净值

- 页面：[LOF 净值](https://www.sse.com.cn/assortment/fund/lof/netvalue/)
- 接口：`https://query.sse.com.cn/commonQuery.do`
- 方法/格式：GET，JSONP
- `sqlId`：`COMMON_SSE_CP_JJ_LOF_SSKFSJJJZ_L`
- 参数：`PRODUCT_TYPE=11,14`（LOF）或 `15`、`SEARCH_DATE=YYYY-MM-DD`、`type=inParams`、标准 `pageHelp.*` 分页参数。
- 关键原始字段：`PRODUCT_TYPE`、`NAV`、`FUND_CODE`、`FUND_ABBR`、`ASSESS_DATE`、`SEC_NAME_FULL`、`NUM`。
- 真实验证：空日期查询返回 112 条，实际最新 `ASSESS_DATE=2026-08-13`；精确查询 `2020-01-02` 返回 82 条；`2026-08-14` 返回空，不自动回退；`2015-01-05` 返回空。
- 历史能力：`partial_backfill`。精确历史日期有效，但最早边界未做暴力扫描，不能宣称全历史。
- 更新频率：daily；适合 watch，但建议每日低频检查，而不是分钟级。
- 当前状态：`not_implemented`；P0。

### 4.2 P0：REITs 净值

- 页面：[REITs 净值](https://www.sse.com.cn/assortment/fund/reits/netvalue/)
- 接口：`https://query.sse.com.cn/commonSoaQuery.do`
- 方法/格式：GET，JSONP
- `sqlId`：`REITS_JZ`
- 参数：`appraiseDate=YYYYMMDD`；最新查询使用 `maxDate=1`；标准 `pageHelp.*`。
- 关键原始字段：`fundCode`、`secNameCn`、`secNameFull`、`appraiseDate`、`fundUnitnetWorth`。
- 真实验证：`maxDate=1` 返回 52 条，日期为 `2025-12-31`；`2025-12-31` 返回 52 条、`2024-12-31` 返回 33 条、`2024-06-30` 返回 24 条。
- 语义：这是评估/报告时点净值，不是每日行情，也不应把它伪装成日频数据。
- 历史能力：`partial_backfill`；已验证多个时点，最早边界未验证。
- 更新频率：event_driven/periodic；可进入 watch 的低频组。
- 当前状态：`not_implemented`；P0。

### 4.3 P0：ETF / LOF / REITs 当前行情快照

官方页面 JavaScript 直接请求行情服务器：

| 类型 | 真实接口 | 真实返回规模（2026-08-14） |
|---|---|---:|
| ETF | `https://yunhq.sse.com.cn:32042/v1/sh1/list/exchange/ebs` | 917 |
| LOF 列表 | `https://yunhq.sse.com.cn:32042/v1/sh1/list/exchange/lof` | 119 |
| LOF 详情 | `https://yunhq.sse.com.cn:32042/v1/sh1/list/self/{codes}` | 按代码批量 |
| REITs | `https://yunhq.sse.com.cn:32042/v1/sh1/list/exchange/reits` | 61 |

- 方法/格式：GET，JSON；`begin`/`end` 分页，`select` 指定字段。
- 关键字段：`code`、`name`/`cpxxextendname`、`open`、`high`、`low`、`last`、`prev_close`、`chg_rate`、`volume`、`amount`；ETF 还请求 `tradephase`。
- 页面刷新：约 15 秒，属于 intraday 快照。
- 历史能力：未发现日期参数，判定为 `snapshot_from_now`，不能历史回填。
- 与 `fund_turnover` 的关系：不重复。现有成交模块保存市场/类别汇总，这里是逐基金行情。
- 推荐：单独 `fund_market_data` 模块；第一版先做收盘附近或保守间隔快照，不应在 watch 中按页面 15 秒频率轮询。
- IOPV：本次确认的行情 `select` 中没有 IOPV；不能据此猜字段或另造接口。
- 当前状态：`not_implemented`；P0。

### 4.4 P0：实时申赎货币市场基金每日申赎参数

- 页面：[交易型货币基金每日申赎参数](https://www.sse.com.cn/assortment/fund/currencyfund/basicinfo/)
- 接口：`https://query.sse.com.cn/commonQuery.do`
- 方法/格式：GET，JSONP
- `sqlId`：`COMMON_SSE_ZQPZ_JJLB_SSSSHBJJLB_CPJBXX_L`
- 参数：`FUND_TYPE=30`，页面请求不分页。
- 真实字段：`FUND_CODE`、`FUND_ABBREVIATION`、`COMPANY_NAME`、`FILE_DATE`、`TRADEDATE`、`BUY_LIMIT`、`BUY_LIMIT_SUM`、`SELL_LIMIT`、`SELL_LIMIT_SUM`、`ONEBUY_LIMIT`、`ONEBUY_LIMIT_SUM`、`ONESELL_LIMIT`、`ONESELL_LIMIT_SUM`、`OTHERS`、`NUM`。
- 真实验证：2026-08-15 请求返回 5 条，数据日为 `2026-08-14`。
- 与 `fund_master` 的关系：代码、简称、公司是重复字段；每日申购/赎回限额不是 fund_master 字段，当前没有保存。
- 历史能力：页面接口没有确认日期参数，按 `latest_only` 处理；从实现日起形成快照历史。
- 更新频率：daily；适合 watch 中频/日频检查。
- 当前状态：`researched_only`；P0。

### 4.5 P1：REITs 逐基金成交统计（日/周/月）

REITs 产品详情页的“成交统计”不是全市场 `fund_turnover` 的重复数据，它按单只 REIT 返回成交量、成交金额、换手率以及规模/市值字段。

- 日：`COMMON_SSE_SJ_JJSJ_JJGM_REITSGM_L`，参数 `FUND_CODE`、`TRADE_DATE=YYYYMMDD`、`SEARCH_DAY`、`FUND_TYPE=01`。
- 周：`COMMON_SSE_REITS_HQXX_HQYTJ_CJTJ_WEEK_L`，参数 `FUND_CODE`、`START_DATE`、`END_DATE`、`SEARCH_WEEK`。
- 月：`COMMON_SSE_REITS_HQXX_HQYTJ_CJTJ_MONTH_L`，参数 `FUND_CODE`、`TRADE_DATE=YYYY-MM`。
- 方法/格式：GET，JSONP，支持 `pageHelp.*`。
- 真实字段：`FUND_CODE`、`FUND_ABBR`、`FUND_EXPAND_ABBR`、`TRADE_DATE`、`TRADE_VOL`、`TRADE_AMT`、`TO_RATE`、`TOTAL_VOL`、`LIMIT_VOL`、`UNLIMIT_VOL`、`SELL_VOL`、`TOTAL_VALUE`、`NEGO_VALUE`、`CURRENT_SHARE_DATE`。
- 真实验证：508000 在 `2026-08-14` 日、`2026-08-03` 至 `2026-08-07` 周、`2026-07` 月均返回 1 条非空结果。
- 当前 `reits_scale` 已把日接口的完整原始行保留在 `raw_record_json`，但只标准化规模字段；周、月未采集。因此状态是 `partially_implemented`。
- 历史能力：日/周/月参数真实有效，`partial_backfill`；边界未扫描。
- 更新频率：daily/weekly/monthly；若实现，日频可进 watch，中低频即可。
- 优先级：P1，宜作为 REITs analytics 扩展，不应重复抓取已有日规模。

### 4.6 P1：REITs 发售与扩募

- 页面：[REITs 发售与扩募](https://www.sse.com.cn/assortment/fund/reits/issue/)
- 接口：`https://query.sse.com.cn/commonSoaQuery.do`
- 方法/格式：GET，JSONP，`pageHelp.*` 分页。
- `sqlId`：`REITS_FXYKM`
- 参数：列表可不传 `fundCode`；详情按 `fundCode` 查询。
- 真实字段：`fundCode`、`fundAbbr`、`saleStartDate`、`saleEndDate`、`listingDate`、`saleCopies`、`salePrice`。
- 真实验证：列表返回 64 条。
- 与 fund_master 的关系：`listingDate` 可能重复，但发售区间、份额和价格不在 fund_master 中，是独立事件数据。
- 历史能力：接口返回累计发行/扩募记录，适合 `full_backfill`（以当前可见全集为边界）和 upload-like 事件增量。
- 更新频率：event_driven；可进 watch 低频组。
- 当前状态：`not_implemented`；P1。

### 4.7 P1：REITs 分红

- 页面：[REITs 产品详情](https://www.sse.com.cn/reits/assortment/prices/detail/price/)
- 接口：`https://query.sse.com.cn/commonSoaQuery.do`
- 方法/格式：GET，JSONP，支持分页。
- `sqlId`：`REITS_FH`
- 参数：`fundCode`、`pageHelp.*`。
- 真实字段：`fundCode`、`secNameCn`、`year`、`fundDividends`、`rightsRegistDate`、`exrightDate`。
- 真实验证：508000 返回 9 条，包含 2026-04-16 登记、2026-04-17 除权的一条记录。
- 与公告关系：公告 PDF 是证据文件；这里是可直接分析的结构化权益数据，不是重复表。
- 历史能力：累计记录，适合 `full_backfill` 和事件增量。
- 更新频率：event_driven；可进入 watch 低频组。
- 当前状态：`not_implemented`；P1。

### 4.8 P1：REITs 大宗交易

- 页面：[REITs 产品详情](https://www.sse.com.cn/reits/assortment/prices/detail/price/)
- 当前接口：`COMMON_SSE_XXPL_JYXXPL_DZJYXX_LATEST_L_1`。
- 历史接口：`COMMON_SSE_XXPL_JYXXPL_DZJYXX_L_1`。
- 接口 URL/格式：`https://query.sse.com.cn/commonQuery.do`，GET，JSONP，`pageHelp.*`。
- 参数：`stockId`、`startDate`、`endDate`。
- 真实字段：`stockid`、`abbrname`、`tradedate`、`tradeprice`、`tradeqty`、`tradeamount`、`branchbuy`、`branchsell`、`ifZc`、`NUM`。
- 真实验证：508000 在 `2026-01-01` 至 `2026-08-14` 返回 9 条；“latest”在本次请求返回空，不能把空结果当接口失效。
- 历史能力：日期区间查询有效，`partial_backfill`。
- 更新频率：event_driven；若实现，可日频检查，不需要高频。
- 说明：底层是全市场大宗交易数据的证券筛选，不是基金专属基础数据；但 REITs 研究价值较高。
- 当前状态：`not_implemented`；P1。

### 4.9 P2：分级 LOF 历史规模

- 页面：[分级 LOF 规模](https://www.sse.com.cn/market/funddata/volumn/fjlofvolumn/)
- 接口：`https://query.sse.com.cn/commonQuery.do`
- 方法/格式：GET，JSONP。
- `sqlId`：`COMMON_SSE_FUND_FJLOF_SCALE_CX_S`
- 参数：`FILEDATE=YYYYMMDD`。
- 真实字段：`FUND_CODE`、`FUND_ABBR`、`TRADE_DATE`、`INTERNAL_VOL`、`NUM`。
- 真实验证：`2020-12-31` 返回 21 条，`2019-12-31` 返回 33 条；`2026-08-14` 返回空。
- 历史能力：`historical_only`/`partial_backfill`。当前没有活跃数据，不应加入 watch。
- 当前状态：`not_implemented`；P2。

### 4.10 P2：分级 LOF 历史分拆合并统计

- 页面同上。
- 接口：`https://query.sse.com.cn/commonQuery.do`
- 方法/格式：GET，JSONP。
- `sqlId`：`COMMON_SSE_FUND_FJLOF_SM_CX_S`
- 参数：`FILEDATE=YYYYMMDD`。
- 真实字段：`FUND_CODE`、`FUND_ABBR`、`TRADE_DATE`、`SPLIT_VOL`、`MERGE_VOL`、`NUM`。
- 真实验证：`2020-12-31` 返回 7 条，`2019-12-31` 返回 11 条；`2026-08-14` 返回空。
- 历史能力：`historical_only`/`partial_backfill`；不加入 watch。
- 当前状态：`not_implemented`；P2。

### 4.11 P2：已终止封闭式基金的历史详情数据

上交所基金详情旧脚本仍包含：基金发起人、持有人结构、前十大股票、行业分布、历年分红、基金净值等结构化 `commonQuery.do` 接口，例如：

- `COMMON_SSE_ZQPZ_JJLB_FEJG_JJFQR_L`
- `COMMON_SSE_ZQPZ_JJLB_FEJG_JJCYRJG_L`
- `COMMON_SSE_ZQPZ_JJLB_TZZH_JJLSHQCX_C`
- `COMMON_SSE_ZQPZ_JJLB_TZZH_GJJTZD10DGP_L`
- `COMMON_SSE_ZQPZ_JJLB_TZZH_JJCGSSHYFLQ10M_L`
- `COMMON_SSE_ZQPZ_JJLB_JYGK_LNFHQK_L`
- `COMMON_SSE_ZQPZ_JJLB_JYGK_JJJZ_L`

对当前 ETF 510050、LOF 501018 请求上述部分接口均为空；已终止封闭式基金 500008 的净值、分红、持有人结构接口返回非空历史数据。例如净值摘要字段为 `CURNETVALUE`、`LAST_DATE`、`MAXNETVALUE`、`MAXDATE`、`MINNETVALUE`、`MINDATE`。

因此这组数据不是当前 ETF/LOF 的通用净值来源，而是遗留封闭式基金历史资料。若项目将来需要市场史，可单独建 legacy archive；当前主线优先级 P2，不进入 watch。

## 5. 现有模块的部分覆盖缺口

以下两项不计入前述 11 个“新数据集”，因为现有 PCF crawler 已具备主要 transport/XML 能力。

### 5.1 交易型货币基金 PCF 分类

官方 PCF 页面在同一个列表接口中使用：

- `sqlId=COMMON_SSE_PL_ETFGGSGSHQD_L`
- `ETF_CLASS=05,07`
- 下载仍为 `downloadETF2Bulletin.do?fundCode={fundCode}`。

真实列表请求返回 24 条。511600 XML 请求返回 HTTP 200、1076 bytes，根节点为 `SSEPortfolioCompositionFile`，`TradingDay=20260814`、`RecordNumber=1`；现有 `parse_pcf_xml` 能正确解析，成分代码为 `SSXJ`。这说明数据协议已被现有模块覆盖，但正式列表范围、状态和真实验证样本集中在普通 ETF，状态应为 `partially_implemented`。建议扩展现有 PCF 分类配置与测试，不新建 crawler；优先级 P1。

### 5.2 PCF header 的其他每日参数

510050 的真实 XML 除当前已标准化字段外，还包含：

- `MaxCashRatio`
- `RedemptionLimit`
- `PublishIOPVFlag`
- `CreationRedemptionSwitch`
- `CreationRedemptionMechanism`

原始 XML 已保留，因此没有数据丢失；只是 header Parquet 尚未标准化这些字段。应在确认不同 ETF 的节点可选性和单位后扩展现有 schema，不另建数据源。状态 `partially_implemented`，优先级 P1。

## 6. 看似遗漏、实际已覆盖或不应重复建设的栏目

| 看似新增内容 | 审计判断 | 原因 |
|---|---|---|
| ETF 份额变化 | `duplicate / already covered` | ETF 日规模已按日期保存；变化量可由相邻日期 `shares_10k` 派生，无需再抓同源页面 |
| REITs 份额结构/规模 | `duplicate / already covered` | 产品详情仍调用 `COMMON_SSE_SJ_JJSJ_JJGM_REITSGM_L`，即现有 REIT scale 来源；扩展交易字段应在同源上处理 |
| REITs 公告 | `duplicate / already covered` | `REITS_BULLETIN` 是 REIT 专区展示；正式基金公告模块已覆盖 REIT 公告类型和 PDF |
| ETF/LOF/REIT 产品代码、简称、上市日、管理人 | `duplicate / already covered` | fund_master、fund_companies 已保存，不因多个页面重复展示而新增 crawler |
| REITs 基础概况 `FUND_BASIC_INFO` | `duplicate / already covered` | 与 fund_master/detail 字段高度重叠；未见足以支撑独立表的新主键事实 |
| 基金市场日/周/月/年汇总 | `implemented` | fund_turnover 已覆盖；不要与逐基金行情混淆 |
| ETF PCF 中 NAV、申购赎回单位、现金差额 | `implemented` | 已在 PCF header 中；不应另建“ETF 每日申赎参数”重复表 |
| XBRL 页面和公告 PDF 中的定期报告 | `implemented` | 元数据、增量和跨源 PDF 匹配已经存在；facts 解析是后续深度能力，不是新的公开来源 |
| 基金管理公司/做市商页面下载文件 | `duplicate / already covered` | 当前维表和关系表已覆盖官方结构化来源 |
| 年鉴/统计资料下载 | `not_worth_collecting` | 多为静态历史文件，且主要汇总口径与 fund_turnover 重复；可作为人工核验资料 |

## 7. 不支持或暂不建议采集

### 7.1 分级 LOF 净值

前端存在 `COMMON_SSE_FUND_FJLOF_NETVALUE_CX_S`，参数为 `FILEDATE`，但对 2026-08-14、2020-12-31、2020-12-30、2020-12-29、2019-12-31、2019-12-30 的代表性请求均为空。接口存在是 `verified`，可用数据和字段语义仍为 `unverified`，当前标记 `unsupported`/Skip，不能据接口名猜数据。

### 7.2 ETF IOPV 独立历史数据

PCF 的 `PublishIOPVFlag` 仅表示是否发布 IOPV，不是 IOPV 数值。已验证的公开行情请求字段中也没有 IOPV。本次没有发现可历史查询的稳定官方 Web 接口，标记 `unsupported`/Skip。未来若官方页面出现真实字段，再单独复核。

### 7.3 REITs 交易公开信息

REITs 详情页调用 `JYGKXX_ZL`，但该接口是全市场“交易公开信息”数据源。空 `secCode` 的 3 年查询返回 20,727 条证券记录；508000 在本次区间查询为空。它不是基金专属数据，事件稀疏，且会把项目范围扩展到通用证券龙虎榜，标记 `not_worth_collecting`/Skip。若未来构建统一市场异常交易库，应在独立项目或 market-wide 模块处理。

## 8. 历史能力与 watch 适配

| 数据集 | 更新频率 | 历史能力 | 建议加入 watch | 建议频率 |
|---|---|---|---|---|
| LOF 净值 | daily | partial_backfill | 是 | 每日 1–2 次 |
| REITs 净值 | event_driven/periodic | partial_backfill | 是 | 每日或更低频 |
| ETF/LOF/REIT 行情 | intraday | snapshot_from_now | 有条件 | 保守快照；不要 15 秒全量轮询 |
| 货币基金每日申赎参数 | daily | latest_only/snapshot_from_now | 是 | 每日 1–2 次 |
| REITs 逐基金成交统计 | daily/weekly/monthly | partial_backfill | 日频可选 | 每日；周/月到期检查 |
| REITs 发售扩募 | event_driven | 当前接口累计记录 | 是 | 每日或每周 |
| REITs 分红 | event_driven | 当前接口累计记录 | 是 | 每日或每周 |
| REITs 大宗交易 | event_driven | partial_backfill | 可选 | 每日 |
| 分级 LOF 规模/分拆合并 | historical_only | partial_backfill | 否 | 一次性历史回填 |
| 遗留封闭基金详情 | historical_only | partial_backfill | 否 | 一次性归档 |

## 9. 优先级与实施建议

### P0

1. LOF 净值。
2. REITs 净值。
3. ETF/LOF/REIT 逐基金行情快照。
4. 实时申赎货币市场基金每日限额参数。

实施时建议合并成三个代码模块，而不是四个：

- `fund_nav`：共享存储与服务层，分别维护 LOF、REITs 两个来源适配器，绝不强行统一不同频率语义。
- `fund_market_data`：统一行情 schema，按 ETF/LOF/REIT 三条官方路由获取；明确仅从实现日起形成快照历史。
- `money_fund_redemption_params`：每日快照，保留官方限额原始字段。

### P1

1. REITs 逐基金日/周/月成交统计。
2. REITs 发售与扩募。
3. REITs 分红。
4. REITs 大宗交易。
5. 在现有 PCF 模块中纳入 `ETF_CLASS=05,07` 并扩展已确认的 header 字段；这属于增强项，不计入 11 个新数据集。

### P2

1. 分级 LOF 历史规模。
2. 分级 LOF 历史分拆合并统计。
3. 已终止封闭式基金历史详情归档。

### Skip

- 分级 LOF 净值（未验证到非空数据）。
- 独立 ETF IOPV 历史数据（未发现稳定公开接口）。
- REITs 公告、产品概况、份额变化等与现有模块重复的页面。
- 全市场交易公开信息、统计年鉴等偏离基金主线或低维护收益的数据。

## 10. 第一版完成度判断

### 10.1 是否已覆盖主要公开数据

是。当前项目已经覆盖上交所基金公开数据的主干：产品主数据、管理人/做市商、各类规模、市场成交汇总、公告、XBRL、PDF 关联和 ETF PCF。按功能面估算，第一版约完成 **85%**；这个百分比是工程完整度判断，不是对上交所全部页面数量的机械计数。

### 10.2 真正重要的缺口

- 净值：LOF 日净值和 REITs 定期净值。
- 逐基金行情：ETF/LOF/REIT 当前 OHLC、成交量、成交额。
- 交易型货币基金每日申赎限额。
- 次一级为 REITs 的发行、分红和产品级成交专题数据。

### 10.3 如果只再做一个模块

实现 `fund_nav`，首期覆盖 LOF 和 REITs 两条已验证来源。它具备明确历史价值、接口请求量低，并补上当前项目最明显的金融核心字段。

### 10.4 如果再做三个模块

1. `fund_nav`（LOF + REITs）。
2. `fund_market_data`（ETF + LOF + REITs 当前行情，保守采样）。
3. `money_fund_redemption_params`（交易型货币基金每日限额）。

### 10.5 第一版正式完成标准

完成上述三个 P0 模块，并给现有 PCF 模块补上交易型货币基金分类验证和已确认 header 字段后，可以认为项目第一版的数据覆盖正式完成。REITs 发行/分红/大宗交易以及分级 LOF 历史资料可进入 1.x 后续迭代，不应阻塞第一版。

## 11. 完整覆盖矩阵

| # | 数据名称 | 官方页面/证据 | 真实接口或文件 | 关键字段 | 更新频率 | 当前模块 | 历史能力 | 增量能力 | 状态 | 是否值得实现 | 优先级 |
|---:|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 基金产品主数据 | 基金产品列表 | `commonSoaQuery.do`, `FUND_LIST` 等 | code/name/type/list date/manager | static_snapshot | fund_master | snapshot_from_now | 有 | implemented | 已覆盖 | Skip |
| 2 | 基金管理公司 | 管理公司列表 | 官方 JSONP | 公司代码/名称/产品关系 | static_snapshot | fund_companies | snapshot_from_now | 有 | implemented | 已覆盖 | Skip |
| 3 | 基金做市商/产品关系 | 做市商页面 | 官方 JSONP/Excel | fund_code/market_maker/type | static_snapshot | fund_market_makers | snapshot_from_now | 有 | implemented | 已覆盖 | Skip |
| 4 | ETF 规模 | ETF 规模页 | `COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L` | date/code/name/shares | daily | etf_scale | partial_backfill | 有 | implemented | 已覆盖 | Skip |
| 5 | LOF 规模 | LOF 规模页 | `COMMON_SSE_SJ_JJSJ_JJGM_LOFGMTJ_L` | date/code/name/shares | daily | lof_scale | partial_backfill | 有 | implemented | 已覆盖 | Skip |
| 6 | 交易型货币基金规模 | 货币基金规模页 | `COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_JYXJJ_SEARCH_L` | date/code/name/shares | daily | money_market_scale | partial_backfill | 有 | implemented | 已覆盖 | Skip |
| 7 | REITs 规模 | REITs 规模页 | `COMMON_SSE_SJ_JJSJ_JJGM_REITSGM_L` | date/code/name/total volume | daily | reits_scale | partial_backfill | 有 | implemented | 已覆盖 | Skip |
| 8 | 基金成交汇总（日/周/月/年） | 基金成交概况 | 现有六个 verified sqlId | period/category/volume/amount | daily/weekly/monthly/yearly | fund_turnover | 混合 full/partial | 有 | implemented | 已覆盖 | Skip |
| 9 | ETF 最新 PCF | ETF PCF 页 | 列表/基本信息/成分券 sqlId + XML 下载 | header/components/XML | daily | etf_pcf | latest_only | 有 | implemented | 已覆盖 | Skip |
| 10 | 交易型货币基金 PCF | ETF PCF 页货币分支 | 列表 sqlId + `ETF_CLASS=05,07` + 同一 XML 下载 | 同 PCF；可含 `SSXJ` | daily | etf_pcf | latest_only | 可用但未纳入正式范围 | partially_implemented | 扩展现有模块 | P1 |
| 11 | PCF 扩展每日参数 | PCF 原始 XML | XML 节点 | MaxCashRatio/limits/switch/mechanism | daily | etf_pcf raw XML | latest_only | 有 | partially_implemented | 扩展 schema | P1 |
| 12 | 基金公告/PDF | 基金公告页 | `COMMON_PL_JJXX_JJGG_NEW_L` + PDF | id/code/title/date/url | event_driven | fund_announcements | full/partial_backfill | 有 | implemented | 已覆盖 | Skip |
| 13 | XBRL 元数据/展示 HTML | EID/上交所 XBRL | `advanced_search_xbrl.do` 等 | uploadInfoId/report/fund/date | event_driven | xbrl | full_backfill | 有 | implemented | 已覆盖 | Skip |
| 14 | XBRL/PDF 关联 | EID/SSE 公告来源 | EID PDF + SSE announcements | XBRL ID/PDF ID/url/status | event_driven | xbrl_pdf_match | partial_backfill | 有 | partially_implemented | 继续覆盖率治理 | P1 |
| 15 | LOF 净值 | LOF 净值页 | `COMMON_SSE_CP_JJ_LOF_SSKFSJJJZ_L` | code/date/NAV/name/type | daily | 无 | partial_backfill | 可实现 | not_implemented | 是 | P0 |
| 16 | REITs 净值 | REITs 净值页 | `REITS_JZ` | code/appraiseDate/unit NAV | event_driven | 无 | partial_backfill | 可实现 | not_implemented | 是 | P0 |
| 17 | ETF/LOF/REIT 当前行情 | 各市场/行情页 | `yunhq ... /ebs`, `/lof`, `/reits`, `/self` | OHLC/last/volume/amount | intraday | 无 | snapshot_from_now | 可快照 | not_implemented | 是，低频 | P0 |
| 18 | 货币基金每日申赎限额 | 货币基金 basicinfo | `COMMON_SSE_ZQPZ_JJLB_SSSSHBJJLB_CPJBXX_L` | buy/sell/single/aggregate limits | daily | 无 | latest_only | 可快照 | researched_only | 是 | P0 |
| 19 | REITs 逐基金成交统计 | REITs 产品详情 | 日同规模；周/月两个 REIT sqlId | trade volume/amount/turnover/value | d/w/m | reits_scale 仅保留日原始行 | partial_backfill | 可实现 | partially_implemented | 是 | P1 |
| 20 | REITs 发售与扩募 | REITs issue 页 | `REITS_FXYKM` | sale dates/copies/price/list date | event_driven | 无 | 当前累计记录 | 可实现 | not_implemented | 是 | P1 |
| 21 | REITs 分红 | REITs 产品详情 | `REITS_FH` | year/dividend/register/ex-date | event_driven | 无 | 当前累计记录 | 可实现 | not_implemented | 是 | P1 |
| 22 | REITs 大宗交易 | REITs 产品详情 | `...DZJYXX_LATEST_L_1`/`...DZJYXX_L_1` | date/price/qty/amount/buy/sell branch | event_driven | 无 | partial_backfill | 可实现 | not_implemented | 有研究价值 | P1 |
| 23 | 分级 LOF 历史规模 | 分级 LOF 页 | `COMMON_SSE_FUND_FJLOF_SCALE_CX_S` | code/date/internal volume | historical_only | 无 | partial_backfill | 不需要 | not_implemented | 历史补充 | P2 |
| 24 | 分级 LOF 分拆合并 | 分级 LOF 页 | `COMMON_SSE_FUND_FJLOF_SM_CX_S` | code/date/split/merge volume | historical_only | 无 | partial_backfill | 不需要 | not_implemented | 历史补充 | P2 |
| 25 | 遗留封闭基金详情 | 旧基金详情页脚本 | 多个 `COMMON_SSE_ZQPZ_JJLB_*` | holders/portfolio/dividend/NAV | historical_only | 无 | partial_backfill | 不需要 | not_implemented | 仅市场史 | P2 |
| 26 | 分级 LOF 净值 | 分级 LOF 页脚本 | `COMMON_SSE_FUND_FJLOF_NETVALUE_CX_S` | 未验证 | historical_only | 无 | unverified | 不适用 | unsupported | 暂不做 | Skip |
| 27 | ETF IOPV 历史序列 | PCF/行情页 | 未发现已验证公开接口 | IOPV | intraday | 无 | unsupported | 不适用 | unsupported | 暂不做 | Skip |
| 28 | ETF/REIT 份额变化派生 | 规模页 | 与现有 scale 同源 | adjacent-date change | daily | scale modules | 已有历史可计算 | 可派生 | duplicate/already covered | 不建 crawler | Skip |
| 29 | REITs 公告专区 | REITs 详情 | `REITS_BULLETIN` | title/date/url | event_driven | fund_announcements | 已覆盖 | 有 | duplicate/already covered | 不建 crawler | Skip |
| 30 | REITs 交易公开信息 | REITs 详情/全市场接口 | `JYGKXX_ZL` | abnormal trade metrics | event_driven | 无 | partial_backfill | 可查 | not_worth_collecting | 非基金专属 | Skip |
| 31 | 年鉴/统计静态文件 | 统计资料栏目 | 官方下载文件 | 年度汇总 | yearly/historical_only | fund_turnover 部分重叠 | 文件历史 | 无必要 | not_worth_collecting | 仅人工核验 | Skip |

## 12. 未验证边界

- LOF 净值、REITs 净值、REITs 成交专题和分级 LOF 的最早可追溯日期没有高频扫描，只能标记 `partial_backfill`。
- 没有找到 ETF 独立历史 NAV/IOPV 的稳定公开 Web 接口；ETF PCF 只能证明最新清单中的 NAV 等字段。
- 行情服务器可取得当前快照，但服务稳定性、允许的长期采样频率和停牌/集合竞价状态语义需要在正式实现前做小规模专项验证。
- 交易型货币基金 PCF 已验证 511600，可否覆盖全部 `ETF_CLASS=05,07` 产品以及特殊节点差异仍需正式测试。
- XBRL/PDF 的跨源覆盖率属于现有模块质量问题，不应被计为新的上交所数据集。

