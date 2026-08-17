# 基金 XBRL 元数据增量发现机制调研

调研日期：2026-08-14（Asia/Shanghai）

## 1. 结论

`advanced_search_xbrl.do` 的 `startUploadDate`、`endUploadDate` **具有真实筛选作用**，但实测筛选的是返回记录的 `reportSendDate`，不是参数名称暗示的 `uploadDate`。因此正式实现中应把它称为“报告送出日期筛选”，不能把它解释成上传日期筛选。

推荐采用混合增量架构：

1. 以 `advanced_search_xbrl.do` 的送出日期区间筛选作为完整增量主链路；
2. 以 `uploadInfoId` 去重并识别更正或新增记录；
3. 用 `xbrlAfficheData.json`、`indexXbrlData.json` 作为一次请求的轻量告警/发现信号，不能作为唯一增量来源；
4. 每日对近期日期做小范围回看，同时用无日期条件查询的第一页总数与本地分区数量核对；
5. 当总数差异无法由近期日期查询解释时，执行补偿扫描；并保留低频周期性全量校验。

本次只调查和设计，没有修改 crawler、Parquet，也没有下载展示 HTML。

## 2. 验证对象与请求方式

查询接口：

```text
GET http://eid.csrc.gov.cn/fund/disclose/advanced_search_xbrl.do
```

固定业务条件：

```text
reportTypeCode = FB030020
reportYear = 2026
fundCode = 空
```

筛选参数仍位于页面实际使用的 `aoData` JSON 数组中。接口强制每页最多返回 20 条；即使将 `iDisplayLength` 设置为 100、500 或 1000，实测仍只返回 20 条。

## 3. 日期筛选真实验证

### 3.1 三组核心对照

| 方案 | `startUploadDate` | `endUploadDate` | `iTotalRecords` / `iTotalDisplayRecords` | 当前页条数 | 首批记录特征 |
| --- | --- | --- | ---: | ---: | --- |
| A：不筛日期 | 空 | 空 | 14,023 | 20 | `reportSendDate=2026-07-21`，`uploadDate=2026-07-20/21` |
| B：单日 | 2026-07-20 | 2026-07-20 | 2,838 | 20 | `reportSendDate=2026-07-20`，但 `uploadDate=2026-07-17` |
| C：短区间 | 2026-07-20 | 2026-07-21 | 13,679 | 20 | 同时覆盖两个送出日期 |

短区间总数满足：

```text
2026-07-20 单日 2,838
+ 2026-07-21 单日 10,841
= 2026-07-20 至 07-21 区间 13,679
```

说明日期区间为包含首尾的有效筛选，而不是被服务端忽略。

### 3.2 对参数真实语义的补充验证

| 输入单日 | 总数 | 首/末页 `reportSendDate` | 观察到的 `uploadDate` |
| --- | ---: | --- | --- |
| 2026-07-17 | 51 | 全为 2026-07-17 | 2026-07-16 |
| 2026-07-20 | 2,838 | 全为 2026-07-20 | 2026-07-14 至 07-17（抽查首末页） |
| 2026-07-21 | 10,841 | 全为 2026-07-21 | 2026-07-16、07-17、07-20、07-21（抽查首末页） |
| 2026-08-14 | 0 | 无数据 | 无数据 |

因此：

- 日期条件真实有效；
- 它筛选 `reportSendDate`；
- 它不等价于按 `uploadDate` 查询；
- 参数名称与实际筛选字段不一致，正式代码和文档必须保留这一实测说明。

抽查返回记录均包含 `uploadDate`、`reportSendDate`、`uploadInfoId`、`fundCode` 和 `reportDesp`。例如 2026-07-20 单日查询的首条之一为：

```json
{
  "uploadDate": "2026-07-17",
  "reportSendDate": "2026-07-20",
  "uploadInfoId": 23152888,
  "fundCode": "519160",
  "reportDesp": "第二季度报告"
}
```

## 4. `xbrlAfficheData.json` 验证

接口：

```text
GET http://eid.csrc.gov.cn/fund/disclose/xbrlAfficheData.json
```

实测：

- HTTP 200，纯 JSON；
- `iTotalRecords=25153`；
- `iTotalDisplayRecords=25153`；
- `aaData` 实际只有 20 条；
- 每条包含 `uploadInfoId`、`fundCode`、`fundShortName`、`reportDesp`、`reportYear`、`uploadDate`、`reportSendDate` 等；
- 不包含明确的 `reportTypeCode`；只能从 `reportDesp` 识别业务描述；
- 本次 20 条的 `reportSendDate` 全为 2026-08-14，`uploadDate` 为 2026-08-13 或 08-14；
- 记录在同一送出日期内大体按 `uploadInfoId` 递增，不是严格“最大 ID 在前”的倒序列表。

分别传入以下参数，返回的 20 个 `uploadInfoId` 与无参数请求完全相同：

- DataTables `aoData`，其中 `iDisplayStart=20`；
- 直接查询参数 `iDisplayStart=20&iDisplayLength=20`。

因此该 JSON 的当前入口不接受这些分页方式，不能取得其声称的 25,153 条完整结果。

判断：

- 唯一增量来源：**不适合**；
- 轻量发现源：**适合**；
- 风险：一天超过 20 条时必然只暴露一个小窗口，不能把这 20 条当作当天全部记录。

## 5. `indexXbrlData.json` 验证

接口：

```text
GET http://eid.csrc.gov.cn/fund/disclose/indexXbrlData.json
```

返回四组，每组固定 5 条，共 20 条：

| 分组 | 条数 | 含义 |
| --- | ---: | --- |
| `fAXBRLReportList` | 5 | 募集/产品资料等 |
| `halfyearXBRLReportList` | 5 | 年度、中期类展示分组 |
| `noticeXBRLReportList` | 5 | 临时公告类 |
| `seasonXBRLReportList` | 5 | 季度报告类 |

字段特点：

- `idStr` 可对应列表记录的实例标识，本次值形如 `23174372`；字段名不是 `uploadInfoId`；
- 包含 `fundcode`、`fundshortName`、`reportSendDate`、`reportYear`、`reportTypereportDesp`；
- `reportCode` 本次全部为空，不能据此取得 `FB030020`；
- 不返回 `uploadDate`；
- 季度报告分组只有 5 条，当前均为 2026 年第二季度报告；
- 分组内 `idStr` 并非严格升序或降序，不能把其顺序当作可靠游标。

判断：

- 唯一增量来源：**不适合**；
- 轻量发现源：**适合做告警或快速发现少量新 ID**；
- 风险：每个分组只有 5 条，披露高峰期会漏掉同一天绝大多数报告，也缺少可靠的报告类型代码。

## 6. 当前页面是否还有其他最新接口

读取当前官方资源：

```text
http://eid.csrc.gov.cn/fund/subpage/xbrl_affiche_subpage.js
```

脚本真实引用的相关入口包括：

- `/fund/disclose/xbrlAfficheData.json`：默认 20 条列表；
- `/fund/disclose/advanced_search_xbrl.do`：筛选与服务端分页；
- `/fund/disclose/xbrlAfficheSearchData.json`：查询条件元数据；
- `/fund/disclose/instance_html_view.do`：展示 HTML；
- 详情页和净值日报相关入口。

未发现另一个由当前 XBRL 公告页面实际使用、可提供完整“最新 XBRL 元数据”的接口。`xbrlAfficheSearchData.json` 只提供年份、基金类型、报告类型等筛选选项，不是记录列表。

## 7. 对候选增量方案的评价

### 方案 A：按日期直接查询

**推荐作为主方案，但必须按 `reportSendDate` 理解。**

优点：

- 服务端真实过滤，结果有总数并可完整分页；
- 同一天超过 20 条时仍可取得全部记录；
- 新 `uploadInfoId` 可捕捉更正稿或补发记录，而不会因基金代码相同被删除；
- 普通无数据日只需 1 个请求即可确认总数为 0。

限制：

- 参数名虽为 UploadDate，实际不是按 `uploadDate`；
- 若平台在较晚日期补录一条旧 `reportSendDate` 记录，仅查询“今天”可能发现不了；
- 披露高峰仍需较多分页请求，这是取得当天完整集合所必需的成本。

实测请求量示例（每页20条）：

| 送出日期/区间 | 记录数 | 完整分页请求数 |
| --- | ---: | ---: |
| 无数据日 2026-08-14 | 0 | 1 |
| 2026-07-17 | 51 | 3 |
| 2026-07-20 | 2,838 | 142 |
| 2026-07-21 | 10,841 | 543 |
| 2026-07-20 至 07-21 | 13,679 | 684 |

### 方案 B：最新 JSON 发现后再补查询

**适合作为告警层，不适合作为完整主链路。**

两个 JSON 一共只需 1—2 个请求，但窗口只有 20 条或每组5条。披露高峰一天可能出现数千至上万条，单靠它们必然漏数。发现未见 ID 后，应根据记录的 `reportSendDate` 回到 `advanced_search_xbrl.do` 查询该日期的完整集合。

### 方案 C：无日期重新分页，遇到已有 ID 后停止

**不推荐作为可靠方案。**

无日期结果大体表现为较新送出日期在前，但没有观察到可作为契约的严格排序：

- 第0页 `uploadInfoId` 从 `23191384` 一组变化到 `23191793`；
- 第20条后的页面又回到 `23191364`；
- 页内和跨页不是严格按 ID 单调排列；
- 同一送出日期的新记录可能插入已有记录附近，遇到一个已有 ID 后停止会漏掉后续新 ID。

除非未来官方明确提供稳定排序和游标，否则不能采用“首个已有 ID 即停止”。

### 方案 D：日期主链路 + 最新告警 + 总数对账

**最终推荐。**

这是 A 与 B 的组合，并增加低成本完整性对账：

1. 每日按目标 `reportTypeCode + reportYear` 查询当天及短回看窗口的 `reportSendDate`；
2. 对返回结果完整分页，以 `uploadInfoId` 与本地集合做差集；
3. 新 ID 才写入元数据，保留同一 `fundCode` 的多条记录；
4. 每日读取一个最新 JSON 作为异常告警。若其中出现本地未知 ID，则按其送出日期补查完整当天集合；
5. 对无日期条件查询第一页，仅用其 `iTotalDisplayRecords` 与本地该分区总数对账；这一步只需1个请求；
6. 若远程总数大于本地，而近期日期查询无法解释差额，触发补偿扫描；
7. 周期性执行全量校验，防止迟到补录、旧送出日期更正或最新窗口截断造成长期遗漏。

## 8. 推荐每日请求预算

仅针对当前 `FB030020 / 2026` 分区：

- 常规无数据期：
  - 1次日期区间/单日查询；
  - 1次最新 JSON 告警（可选读取其中一个）；
  - 1次无日期总数对账；
  - 合计约 **2—3次/日**。
- 有少量新增且不超过20条：约 **2—3次基础请求**，日期查询的首请求已经携带数据。
- 有 N 条新增：日期主链路约 `ceil(N/20)` 次，再加1—2次告警/对账请求。
- 披露高峰如 2026-07-21 的10,841条：完整发现至少需要543页；最新20条接口无法安全减少这一必要成本。

为了避免每天反复扫描高峰日期，应维护“送出日期—远程总数—已采集唯一 ID 数”的检查点。近期日期可短期回看；已经稳定且计数一致的高峰日期不应每天重新抓取全部页面。

## 9. 是否仍需周期性全量校验

**需要。** 原因是当前日期参数筛选 `reportSendDate`，不能保证晚到记录的送出日期一定等于采集当天；两个最新 JSON 又是截断窗口。

建议分两层：

1. 日常低成本总数对账：每个活跃“报告类型×年度”分区请求无日期第一页，比较远程总数与本地唯一 `uploadInfoId` 数；
2. 周期性完整校验：按披露期活跃程度安排，例如活跃披露期更频繁、稳定后降低频率。具体周期应根据实际运行中的迟报和更正分布确定，当前不写死为永久业务规则。

只要总数发生无法解释的增长，就应触发日期补查或全量补偿，不能仅依赖最新20条。

## 10. 推荐最终增量架构

```text
每日调度
  -> 最新 JSON（轻量告警，不作为完整来源）
  -> advanced_search_xbrl.do 日期查询（完整主来源）
       -> 按 iTotalDisplayRecords 分页至完整
       -> uploadInfoId 与本地做差集
       -> 保存新元数据
  -> 无日期第一页总数对账
       -> 数量一致：结束
       -> 数量不一致且近期查询无法解释：补偿扫描
  -> 周期性全量校验
```

检查点至少保存：

- `reportTypeCode`；
- `reportYear`；
- 查询的 `reportSendDate` 或区间；
- 接口报告总数；
- 已采集唯一 `uploadInfoId` 数；
- 最近成功检查时间；
- 是否需要补偿扫描。

本阶段不实现上述增量代码，也不修改已有 XBRL 元数据 Parquet。
