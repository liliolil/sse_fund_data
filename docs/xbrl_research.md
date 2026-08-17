# 上海证券交易所基金 XBRL 数据源调研

调研日期：2026-08-14（Asia/Shanghai）

## 结论摘要

基金 XBRL 存在两套需要区分的公开资源：

1. **上海证券交易所网站**提供 XBRL 介绍、基金分类标准和分类标准实例包。分类标准包中包含 XSD、计算/标签/展示/参考链接库 XML；实例包中包含可直接解析的真实基金 `.xbrl` 实例文件。
2. **中国证监会“资本市场电子化信息披露平台”**（以下简称 EID 平台）提供正在运行的“公募基金—基金 XBRL 专区”，可以查询季度报告、中期报告、年度报告、净值日报及部分临时公告，并用 `instanceid` 打开服务端生成的 XBRL 展示 HTML。

上交所基金公告页本身只返回公告元数据和 PDF URL，没有返回 XBRL URL。以 510050 的 2026 年第二季度报告为例，EID XBRL 记录与上交所 PDF 公告可按基金代码、报告类型、报告年度和公告日期对应，但两套接口没有共同的显式公告 ID。

当前可确认：

- 季度报告、中期报告、年度报告都有真实 XBRL 记录和非空 XBRL 展示页；
- 上交所分类标准实例包中有可直接下载并解析的 `.xbrl` 原始实例；
- EID 当前前端只公开“查看 XBRL”展示页，没有观察到当前生产报告原始 `.xbrl/.xml` 的独立下载按钮或真实下载请求；
- 不需要 Selenium，列表、筛选、分页、展示 HTML、PDF、分类标准和示例文件均可用普通 HTTP 请求取得；
- 公告元数据和展示 HTML适合历史全量及增量采集；**当前生产报告原始 XBRL 文件的全量下载能力仍未验证**，不能根据展示页目录名猜测原始文件 URL。

## 1. 上交所 XBRL 页面

### 1.1 上交所与 XBRL

页面：

```text
https://www.sse.com.cn/services/information/xbrl/ssexbrl/
```

页面介绍上交所 XBRL 工作，并说明上交所制定了公募基金信息披露 XBRL 分类标准。该页面属于介绍材料，不是实例文件检索入口。

### 1.2 上交所 XBRL 分类标准总页

```text
https://www.sse.com.cn/services/information/xbrl/classification/
```

页面列出上市公司、金融类公司和基金分类标准。上交所页面说明其上市公司和基金 XBRL 分类标准在 2010 年获得 XBRL International “Approved”认证。

### 1.3 上交所基金分类标准页

```text
https://www.sse.com.cn/services/information/xbrl/classification/found/
```

页面标题为“基金分类标准”，英文名称为 `China Fund Company Information Disclosure Taxonomy`，标注日期 `2008-12-01`、状态 `Final`。页面提供五个真实 ZIP 下载：

| 内容 | 页面名称 | 真实 URL |
| --- | --- | --- |
| 分类标准 DTS | `cfcid-DTS.zip` | `https://www.sse.com.cn/services/information/xbrl/classification/found/c/10076118/files/e6d85e45ef9c4b69aece62c1aee8051d.zip` |
| 分类标准说明 | `CFCID-Taxonomy-SummaryDocs.zip` | `https://www.sse.com.cn/services/information/xbrl/classification/found/c/10076118/files/b985b1063eda44b792195718c2579f52.zip` |
| 元素打印稿 | `CFCID-Taxonomy-Printouts.zip` | `https://www.sse.com.cn/services/information/xbrl/classification/found/c/10076118/files/f157283d56e8468db0ccbd463331f7bf.zip` |
| 分类标准实例 | `CFCID-2008-12-01-Taxonomy-Instances.zip` | `https://www.sse.com.cn/services/information/xbrl/classification/found/c/10076118/files/ba3433445d224d41934d60528d8f6df8.zip` |
| 测试报告 | `CFCID-Taxonomy-TestReport.zip` | `https://www.sse.com.cn/services/information/xbrl/classification/found/c/10076118/files/829df785e5424754bc5d96c05a54c700.zip` |

本次直接下载验证：

- DTS ZIP：HTTP 200，`Content-Type: application/zip`，311,046 字节，56 个 ZIP 条目；
- 实例 ZIP：HTTP 200，`Content-Type: application/zip`，259,897 字节，13 个 ZIP 条目，其中 8 个 `.xbrl` 文件；
- 两个响应均以 ZIP 文件头 `PK\x03\x04` 开始，非 HTML 伪下载。

## 2. 正在运行的基金 XBRL 公开入口

### 2.1 EID 公募基金入口

```text
http://eid.csrc.gov.cn/fund/disclose/index.html
```

该站为“资本市场电子化信息披露平台”。左侧菜单包含：

- 公募基金净值信息；
- 公告信息；
- 主体信息；
- 基金 XBRL 专区：
  - XBRL 公告；
  - XBRL 分类标准框架。

原 `fund.csrc.gov.cn` 在本次环境中无法正常解析/连接；证监会当前公开页面和接口实际可从 `eid.csrc.gov.cn` 访问。

### 2.2 XBRL 公告页面的加载方式

主页面初始 HTML 不含完整列表。点击“XBRL 公告”后，前端 GET：

```text
http://eid.csrc.gov.cn/fund/subpage/xbrl_affiche_subpage.html
http://eid.csrc.gov.cn/fund/subpage/xbrl_affiche_subpage.js
```

子页面使用 DataTables 服务端分页，通过普通 GET 请求 JSON 接口。不是 JSONP，也不是必须执行浏览器才能取得的数据。

### 2.3 查询条件元数据

- URL：`http://eid.csrc.gov.cn/fund/disclose/xbrlAfficheSearchData.json`
- 方法：GET（前端也以 POST 初始化，服务端 GET 已验证成功）
- 返回：纯 JSON
- 分页：无

返回包含：

- `yearList`：页面年份选项；
- `fundTypeList`：基金类型选项；
- `reportTypeList`：报告类型代码与名称；
- `netDate`：平台当前日期。

基金类型真实值包括股票型、货币型、债券型、混合型、QDII、FOF、商品基金、短期理财债券型和不动产投资信托基金。

与本次目标直接相关的报告代码：

| 报告类型 | `reportTypeCode` |
| --- | --- |
| 年度报告 | `FB010010` |
| 中期报告（原半年度报告） | `FB020010` |
| 第一季度报告 | `FB030010` |
| 第二季度报告 | `FB030020` |
| 第三季度报告 | `FB030030` |
| 第四季度报告 | `FB030040` |
| 季度报告父分类 | `FB030` |
| 基金净值日报 | `FB040020` |

平台还列出基金募集信息、产品资料概要、基金合同生效公告和若干结构化临时公告。本文只验证了定期报告相关链路，不能把下拉框中所有类型都视为已完成逐类验证。

`yearList` 当前给出 1997 至 2026，但这只是页面选项，不代表每个年份都有 XBRL 数据。真实历史范围必须以查询接口非空结果为准。

## 3. XBRL 公告搜索接口

### 3.1 接口

- URL：`http://eid.csrc.gov.cn/fund/disclose/advanced_search_xbrl.do`
- 请求方法：GET
- 返回格式：纯 JSON
- 分页：DataTables 服务端分页
- 主要参数：一个名为 `aoData` 的 JSON 数组

页面真实代码把 DataTables 自带的分页参数和业务筛选参数组成数组，再序列化为 `aoData`：

```json
[
  {"name": "sEcho", "value": 1},
  {"name": "iColumns", "value": 5},
  {"name": "sColumns", "value": ",,,,"},
  {"name": "iDisplayStart", "value": 0},
  {"name": "iDisplayLength", "value": 20},
  {"name": "mDataProp_0", "value": "fundShortName"},
  {"name": "mDataProp_1", "value": "fundCode"},
  {"name": "mDataProp_2", "value": "reportDesp"},
  {"name": "mDataProp_3", "value": "reportSendDate"},
  {"name": "mDataProp_4", "value": "uploadInfoId"},
  {"name": "fundType", "value": ""},
  {"name": "reportTypeCode", "value": "FB030020"},
  {"name": "reportYear", "value": "2026"},
  {"name": "fundCompanyShortName", "value": ""},
  {"name": "fundCode", "value": "510050"},
  {"name": "fundShortName", "value": ""},
  {"name": "startUploadDate", "value": ""},
  {"name": "endUploadDate", "value": ""}
]
```

参数说明：

| 参数 | 作用 |
| --- | --- |
| `iDisplayStart` | 结果偏移量；第一页为 0，第二页在每页 20 条时为 20 |
| `iDisplayLength` | 每页条数，页面使用 20 |
| `reportTypeCode` | 报告类型代码 |
| `reportYear` | 定期报告年度 |
| `fundType` | 基金类型代码 |
| `fundCompanyShortName` | 基金管理人简称；前端会 URL 编码 |
| `fundCode` | 六位基金代码 |
| `fundShortName` | 基金简称；前端会 URL 编码 |
| `startUploadDate` / `endUploadDate` | 募集、临时公告等按上传日期筛选；定期报告页面主要使用 `reportYear` |

返回结构：

```json
{
  "iTotalRecords": 1,
  "iTotalDisplayRecords": 1,
  "sEcho": 1,
  "aaData": [
    {
      "reportYear": "2026",
      "reportDesp": "第二季度报告",
      "uploadDate": "2026-07-20",
      "reportSendDate": "2026-07-21",
      "uploadInfoId": 23167526,
      "fundId": 7,
      "fundCode": "510050",
      "fundShortName": "华夏上证50ETF",
      "fundSign": "9010-1020",
      "organName": "华夏"
    }
  ]
}
```

分页验证：查询 2008 年第四季度报告得到 `iTotalRecords=417`。分别使用 `iDisplayStart=0` 和 `20` 取得两页，每页 20 条；两页 `uploadInfoId` 无交集，各页内也无重复。

### 3.2 首页/默认数据 JSON

平台还提供：

```text
http://eid.csrc.gov.cn/fund/disclose/indexXbrlData.json
http://eid.csrc.gov.cn/fund/disclose/xbrlAfficheData.json
```

- `indexXbrlData.json`：首页少量最新 XBRL 数据，按募集、临时、季度、年度/中期等分组；适合轻量发现，不适合历史全量。
- `xbrlAfficheData.json`：XBRL 公告页默认结果。2026-08-14 验证返回 `iTotalRecords=25153`，但本次响应的 `aaData` 只有当前页 20 条；仍须按分页获取。

正式实现不能把这两个静态 JSON 当作完整历史清单。

## 4. XBRL 展示入口和文件形态

### 4.1 当前生产报告展示入口

列表中的 XBRL 图标实际调用：

```text
GET http://eid.csrc.gov.cn/fund/disclose/instance_html_view.do?instanceid={uploadInfoId}
```

该接口返回 302 跳转，最终进入服务器生成的 HTML。例如：

```text
初始入口：
http://eid.csrc.gov.cn/fund/disclose/instance_html_view.do?instanceid=23167526

最终 URL：
http://eid.csrc.gov.cn/xbrl/REPORT/HTML/2026/FB030020/CN_50030000_510050_FB030020_20260004/CN_50030000_510050_FB030020_20260004.html
```

真实验证结果：

- HTTP 200；
- `Content-Type: text/html; charset=utf-8`；
- 136,230 字节；
- HTML 已包含完整报告内容，并非空壳；
- 在不执行 JavaScript的普通 HTTP 响应中可找到：
  - “上证50交易型开放式指数证券投资基金”；
  - “2026年第2季度报告”；
  - 报告期 `2026-06-30`；
  - 报告送出日期 `2026-07-21`；
  - 基金代码、主要财务指标、投资组合和报告期末基金份额总额等内容。

这证明展示页确实由结构化 XBRL 数据生成，但返回文件类型是 HTML，不是原始 XBRL/XML。

### 4.2 是否存在当前生产实例原始文件下载

**未验证存在。**

本次检查了 XBRL 专区页面、当前 JavaScript 和真实点击链路：

- XBRL 图标只调用 `instance_html_view.do?instanceid=...`；
- 最终只返回 `/xbrl/REPORT/HTML/.../*.html`；
- 页面没有“下载原始 XBRL/XML”按钮；
- 真实链路没有发起 `.xbrl` 或 `.xml` 文件请求；
- 没有发现经过前端代码或真实网络请求确认的生产实例下载接口。

展示目录中出现了规范的报告目录名，但不能据此替换后缀、改变目录或猜测原始文件 URL。

### 4.3 独立原始 XBRL/XML 示例入口

EID 分类标准框架页：

```text
http://eid.csrc.gov.cn/fund-xbrl/TaxonomyFrameworkOverview.htm
```

该页提供两个可直接 GET 的 XML 示例：

```text
http://eid.csrc.gov.cn/fund-xbrl/example1.xml
http://eid.csrc.gov.cn/fund-xbrl/example2.xml
```

`example1.xml` 验证结果：

- HTTP 200；
- `Content-Type: text/xml`；
- 8,135 字节；
- XML 可解析；
- 根节点为 `{http://www.xbrl.org/2003/instance}xbrl`；
- 含 `link:schemaRef`，引用：

```text
http://eid.csrc.gov.cn/cn/fid/fi/ar/2007-09-01/cfid-fi-ar-2007-09-01.xsd
```

该 XSD 也已直接 GET 验证：HTTP 200、2,299 字节、根节点为 XML Schema `schema`，并继续导入 XBRL instance/linkbase 标准和基金报告模块 XSD。

上述两个 XML 是分类标准示例，不应冒充当前基金生产报告。

## 5. 至少一个真实基金报告原始 XBRL 验证

上交所官方 `CFCID-2008-12-01-Taxonomy-Instances.zip` 内含多个真实基金实例。本次选择：

```text
ZIP URL:
https://www.sse.com.cn/services/information/xbrl/classification/found/c/10076118/files/ba3433445d224d41934d60528d8f6df8.zip

ZIP 内成员路径:
CFCID-2008-12-01-Taxonomy-Instances/cn/China Asset Management Co.,Ltd/CN_50030000_000021_FB020010_20080001.xbrl
```

验证结果：

- 文件大小 391,419 字节；
- XML 可正常解析；
- 根节点为 XBRL 2.1 instance `xbrl`；
- `GongGaoMingCheng`：`华夏优势增长股票型证券投资基金2008年半年度报告`；
- `JiJinMingCheng`：`华夏优势增长股票型证券投资基金`；
- `JiJinJianCheng`：`华夏优势增长`；
- `BaoGaoQiMoRiQi`：`2008-06-30`；
- 文件中有 contexts、units 和大量带 `contextRef` 的事实节点。

该实例的 `link:schemaRef` 为：

```text
http://www.xbrl-cn.org/cn/fcid/fi/qr/2008-12-01/cfcid-fi-qr-2008-12-01.xsd
```

该 URL 当前会跳转到 HTTPS 并返回 HTTP 200，文件为 2,323 字节的 XSD，`targetNamespace` 为：

```text
http://www.xbrl-cn.org/cn/fcid/fi/qr/2008-12-01
```

它继续导入：

- XBRL 2.1 instance schema；
- XBRL linkbase schema；
- 基金管理报告 `mr`；
- 基金基本信息/公司治理信息 `cgi`；
- 全局通用文档 `gcd`；
- 重大事件 `ie`；
- 审计报告 `ar`；
- 财务信息 `pt` 等模块 XSD。

因此，真实引用关系为：

```text
基金 .xbrl 实例
  -> link:schemaRef 入口 XSD
     -> 多个业务模块 XSD
        -> 各模块的 calculation / label / presentation / reference 等链接库 XML
```

需要注意：这个 `.xbrl` 是上交所分类标准页面发布的“实例文档包”成员，而不是 EID 当前生产报告的原始下载接口。它能证明原始基金报告实例格式和 schema 引用真实存在，但不能证明所有生产实例都可通过同样路径逐个下载。

## 6. Taxonomy、Schema、XSD 和链接库

上交所 `cfcid-DTS.zip` 中已验证存在：

- `.xsd` 模式文件；
- `*-calculation.xml` 计算链接库；
- `*-label-cn.xml` 中文标签链接库；
- `*-label-en.xml` 英文标签链接库；
- `*-presentation.xml` 展示链接库；
- `*-reference.xml` 参考链接库。

已观察的模块目录包括：

- `common/pt`：财务信息；
- `rpt/ar`：审计报告；
- `rpt/cgi`：基金基本/治理信息；
- `rpt/gcd`：全局通用文档；
- `rpt/ie`：重大事件；
- `rpt/mr`：管理报告；
- `rpt/common`：报告通用定义。

EID 当前分类标准框架页还提供：

```text
http://eid.csrc.gov.cn/fund-xbrl/FundXBRL.rar
```

本次直接 GET 返回 HTTP 200、`Content-Type: application/x-rar-compressed`、366,089 字节，并具有 RAR 文件头。由于当前环境没有 RAR 解析库，本次未解包核对其内部文件，内部版本和目录明确标注为“未验证”。

该页还提供 2026 年模板 ZIP，例如：

```text
http://eid.csrc.gov.cn/fund-xbrl/JiBaoMoBan20260309.zip
http://eid.csrc.gov.cn/fund-xbrl/NianBaoMoBan20260309.zip
```

两者已验证为真实 ZIP，但内部分别是季度报告模板 DOCX、年度和中期报告模板 DOC，并不是 taxonomy XSD 包。

2026 年中国基金业协会发布的新 XBRL 模板自 2026-05-01 起施行，包含季度报告、净值公告、年度和中期报告、基金合同生效及临时公告、基金产品资料概要。正式解析时必须记录实例所引用的 taxonomy 版本，不能把 2008 年 XSD 固定用于所有年份。

## 7. 三类定期报告验证

使用基金代码 510050 逐类查询并打开 `instance_html_view.do`：

| 类型 | 查询条件 | `uploadInfoId` | 报告送出日 | 展示结果 |
| --- | --- | ---: | --- | --- |
| 2026 年第一季度报告 | `FB030010`, `2026` | 22290878 | 2026-04-22 | HTTP 200，完整 HTML |
| 2026 年第二季度报告 | `FB030020`, `2026` | 23167526 | 2026-07-21 | HTTP 200，完整 HTML |
| 2025 年中期报告 | `FB020010`, `2025` | 20213699 | 2025-08-30 | HTTP 200，完整 HTML |
| 2025 年年度报告 | `FB010010`, `2025` | 22084938 | 2026-03-31 | HTTP 200，完整 HTML |

结论：季度、中期和年度报告均存在真实 XBRL 平台记录和由 XBRL 生成的可访问内容。当前生产实例的原始 `.xbrl/.xml` 下载仍未验证。

## 8. 历史范围

### 8.1 官方历史说明

证监会在 2009-07-20 发布的“基金信息披露网站正式上线”说明中明确：

- 可查询自 2009-01-01 以来所有基金净值日报 XBRL；
- 有部分基金 2008 年第三季度报告 XBRL；
- 有自 2008 年第四季度以来所有基金季度报告 XBRL；
- 当时年度报告和半年度报告仍表述为后续扩展方向。

该说明与当前接口中的早期季度数据基本一致。

### 8.2 当前接口真实查询

| 报告类型/年度 | 当前接口结果数 | 结论 |
| --- | ---: | --- |
| 季度报告父类 `FB030`, 2007 | 0 | 2007 未验证到数据 |
| 第三季度 `FB030030`, 2008 | 277 | 已验证有部分 2008 Q3 |
| 第四季度 `FB030040`, 2008 | 417 | 已验证有 2008 Q4 |
| 季度父类 `FB030`, 2008 | 694 | 等于 Q3 + Q4 |
| 年度报告 `FB010010`, 2008 | 0 | 当前查询无结果 |
| 年度报告 `FB010010`, 2009 | 530 | 已验证非空 |
| 中期报告 `FB020010`, 2008 | 81 | 已验证非空，多条在 2008-12 上传 |
| 中期报告 `FB020010`, 2009 | 0 | 当前查询无结果，存在历史空档 |
| 中期报告 `FB020010`, 2010 | 588 | 已验证非空 |

因此，最保守的可验证起点是：

- 季度报告：2008 年第三季度；
- 年度报告：报告年度 2009；
- 中期/半年度报告：存在 2008 年实例，但当前平台 2009 年为空、2010 年恢复，早期覆盖并不连续；
- 上交所分类标准实例包另含 2008 年半年度报告和其他真实 `.xbrl` 样本。

不能根据页面的 1997 年下拉选项宣称 XBRL 从 1997 年开始。

## 9. 与上交所基金公告模块的关系

### 9.1 同一报告的实际对应验证

EID XBRL 记录：

```json
{
  "fundCode": "510050",
  "fundShortName": "华夏上证50ETF",
  "reportDesp": "第二季度报告",
  "reportYear": "2026",
  "reportSendDate": "2026-07-21",
  "uploadInfoId": 23167526
}
```

上交所基金公告接口同日记录：

```json
{
  "SECURITY_CODE": "510050",
  "FUND_EXPANSION_ABBR": "上证50ETF华夏",
  "SSEDATE": "2026-07-21",
  "ORG_BULLETIN_TYPE_DESC": "季度报告",
  "BULLETIN_TYPE_DESC": "定期报告(基金)",
  "TITLE": "上证50交易型开放式指数证券投资基金2026年第2季度报告",
  "URL": "/disclosure/fund/announcement/c/new/2026-07-21/510050_20260721_85EI.pdf"
}
```

PDF 绝对 URL：

```text
https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-07-21/510050_20260721_85EI.pdf
```

二者的基金代码、报告类型和日期一致，标题语义一致，说明 PDF 公告和 XBRL 是同一报告的两种披露表现。

### 9.2 不能直接一一连接的地方

- 上交所公告接口没有 `uploadInfoId`；
- EID 搜索结果没有上交所 PDF URL；
- 上交所公告 PDF 记录没有 XBRL URL；
- 两边基金简称不一定完全相同；
- 同一基金同一天可能有多份公告，因此不能只用“基金代码 + 日期”唯一关联。

推荐关联键：

1. 基金代码；
2. 报告年度/季度；
3. 规范化报告类型；
4. 公告/送出日期；
5. 标题标准化后复核。

保存时两套来源仍应各自保留原生唯一键：

- EID：`uploadInfoId`；
- 上交所：完整 PDF URL，最新公告链路另有 `discloseId` 时同时保存。

## 10. 是否适合历史全量回填

### 元数据和展示 HTML：适合，但要分批

EID 搜索接口支持：

- 报告类型；
- 报告年度；
- 基金代码；
- 基金简称；
- 管理人简称；
- 基金类型；
- 服务器分页及总数。

推荐按“报告类型 × 报告年度”分区，再以 `iDisplayStart` 翻页。这样可断点续传、控制单次查询规模，并能够对 `iTotalRecords` 做数量校验。

### 当前生产原始 XBRL：暂不能确认适合全量

当前页面只验证到 XBRL 展示 HTML，没有验证原始 `.xbrl/.xml` 下载。若项目目标是保存监管报送的原始 XBRL 实例，必须先找到真实生产下载接口或获得官方数据渠道；不能把 HTML 展示页改后缀当作原始文件。

### 历史质量注意事项

- 早期年度/中期报告覆盖有空档；
- taxonomy 版本会变化；
- 更正稿可能产生新的 `uploadInfoId`；
- 报告年度与上传/送出日期不是同一字段；
- 全量结束后应按 `reportTypeCode + reportYear` 对比接口总数，检查空页、重复 `uploadInfoId` 和缺失展示页。

## 11. 是否适合每日增量更新

适合做元数据和展示页增量。

推荐：

1. 每日读取 `indexXbrlData.json` 作为轻量发现源；
2. 对定期报告按当前年度和相关报告类型调用 `advanced_search_xbrl.do`；
3. 以 `uploadInfoId` 作为 EID 文档主键；
4. 对最近若干日/当前报告季保留回看窗口，发现更正或迟报；
5. 新 `uploadInfoId` 出现后再获取 `instance_html_view.do` 展示页；
6. 同步调用上交所基金公告模块补充 PDF，并执行跨源匹配；
7. 不使用页面首 20 条作为“全部最新数据”。

原始 XBRL 文件增量仍取决于未来能否确认真实下载入口。目前只能稳定增量保存元数据、展示 HTML 和上交所 PDF。

## 12. 是否需要 Selenium

不需要。

- 页面子模板和 JavaScript 可直接 GET；
- 查询接口返回普通 JSON；
- 展示接口返回服务器生成的完整 HTML；
- PDF、ZIP、RAR、XML、XSD 都是普通文件请求；
- 没有登录、验证码、下载令牌或必须执行浏览器脚本的数据生成环节。

Selenium 也不能自动解决“生产原始 XBRL 下载入口未发现”的问题，因为当前 UI 本身没有发出该请求。

## 13. 推荐采集路线

本阶段不编写爬虫或 XBRL 解析器。后续建议分成四层：

1. **XBRL 元数据层**：采集 EID `advanced_search_xbrl.do` 返回的原始 JSON，主键 `uploadInfoId`。
2. **XBRL 展示层**：保存 `instance_html_view.do` 最终 HTML 和最终 URL，记录 HTTP 状态、大小和内容摘要。
3. **公告 PDF 层**：复用现有基金公告接口，保存上交所 PDF URL、公告日期、标题和公告类型。
4. **taxonomy 层**：按版本独立保存 XSD 和链接库；实例解析时使用实例自己的 `schemaRef`，不写死 2008 taxonomy。

在真实生产 `.xbrl/.xml` 下载入口确认前，不建议开始正式 XBRL facts 解析器。展示 HTML 可以用于人工核验或临时提取，但它不是原始 XBRL，DOM 模板也比 XBRL taxonomy 更容易变化。

## 14. 历史全量方案

1. 从 `xbrlAfficheSearchData.json` 获取当前报告类型和年份，不把列表硬编码为永久不变。
2. 优先回填 `FB030010` 至 `FB030040`、`FB020010`、`FB010010`。
3. 每次只查询一个报告类型和一个报告年度，以 `iDisplayStart`/`iDisplayLength` 分页。
4. 保存每页原始 JSON，记录该分区的 `iTotalRecords`、完成偏移和采集时间。
5. 以 `uploadInfoId` 去重，不因基金代码、年份或标题相同而丢弃更正记录。
6. 下载展示 HTML，并校验：HTTP 200、内容非空、基金代码/名称、报告标题和报告期存在。
7. 复用基金公告历史接口查询同期定期报告 PDF，通过组合字段关联。
8. 单独回填并版本化上交所/证监会 taxonomy 文件。
9. 对 2008—2010 早期数据单独出覆盖报告，保留“接口真实为空”与“采集失败”的区别。
10. 在生产原始 XBRL 下载源确认后，再补充原始实例文件；不要重写已完成的元数据和 PDF 层。

## 15. 增量更新方案

1. 每日低频读取首页最新 XBRL JSON。
2. 在定期报告披露窗口，查询当前年度的季度、中期和年度类型。
3. 对新 `uploadInfoId` 下载展示 HTML并记录最终重定向 URL。
4. 同日查询上交所基金公告接口的定期报告分类，补充 PDF。
5. 用 `uploadInfoId` 做 EID 去重，用完整 PDF URL/`discloseId` 做上交所去重。
6. 保留 7—30 天回看窗口，以捕捉迟报、更正和数据同步延迟；具体天数应在正式运行后依据实测调整，不写死为业务规则。
7. 定期重新核对当前年度分区总数，发现历史记录补录时进行补偿采集。

## 16. 已验证

- 上交所基金 XBRL 分类标准页面和五个真实 ZIP URL。
- DTS ZIP 内存在 XSD 与 calculation/label/presentation/reference 链接库 XML。
- 实例 ZIP 内存在可解析的真实基金 `.xbrl` 文件。
- 华夏优势增长 2008 年半年度报告 `.xbrl` 的基金名称、报告名、报告期和 `schemaRef`。
- 实例引用的 `cfcid-fi-qr-2008-12-01.xsd` 当前可直接访问并继续导入多个业务模块。
- EID 公募基金 XBRL 专区、查询条件元数据、真实搜索接口和 DataTables 分页机制。
- 2008 年第三、第四季度真实数据数量和两页不重复验证。
- 510050 的季度、中期、年度 XBRL 记录及完整展示 HTML。
- 510050 2026 年第二季度 XBRL 记录与上交所 PDF 公告的跨源对应关系。
- EID `example1.xml` 为可解析的 XBRL XML，并真实引用可访问 XSD。
- 无需 Selenium。

## 17. 未验证

- 当前生产报告原始 `.xbrl/.xml` 的公开下载 URL或下载接口。
- EID 展示 HTML 目录与原始实例存储目录的对应规则；不得根据目录名猜测。
- `FundXBRL.rar` 内部目录和 taxonomy 版本；只验证了真实 RAR 响应。
- 所有报告类型、所有年份和所有基金的完整覆盖率。
- 早期中期报告为何 2008 有数据、2009 为空、2010 恢复。
- `uploadInfoId` 的官方生成规则及跨系统永久稳定性；当前把它作为 EID 返回的实例标识使用。
- 更正稿在 EID 接口中的完整关联机制。
- 当前生产实例使用的每一个 taxonomy 版本及其全部历史下载入口。
- 上交所公告与 EID XBRL 之间是否存在未公开的共同内部 ID。

## 18. 调查边界

本次只执行少量真实页面、JSON、HTML、PDF 元数据、ZIP、RAR、XML 和 XSD 请求；没有批量下载历史全量，没有编写 XBRL 解析器或正式爬虫。调研到此结束。

