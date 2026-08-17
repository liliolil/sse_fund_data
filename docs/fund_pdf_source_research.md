# EID 公募基金 XBRL 对应 PDF 的公开来源覆盖调研

调研日期：2026-08-14（Asia/Shanghai）

## 1. 结论摘要

对于无法在上交所基金公告接口中匹配的 EID 公募基金 XBRL 记录，存在比“逐家基金管理人官网”更统一的官方来源：**EID 平台自己的“公告信息”系统**。

EID 的“基金 XBRL 专区”和“公告信息”是两套相邻但 ID 不互通的公开数据集：

- XBRL 元数据通过 `advanced_search_xbrl.do` 查询，并用 XBRL `uploadInfoId` 打开展示 HTML；
- PDF 公告元数据通过 `advanced_search_report.do` 查询，并用另一套 PDF 公告 `uploadInfoId` 打开 `instance_show_pdf_id.do`；
- 两套记录没有经过验证的共同 ID，不能把 XBRL `uploadInfoId` 直接拼进 PDF URL；
- 可以用 `fundCode + reportCode/report type + reportYear + reportSendDate + 标题语义` 做可解释匹配。

主样本 `fundCode=000001`、XBRL `uploadInfoId=23167397` 已在 EID 公告系统中找到官方 PDF。EID 公告查询是公开 JSON、支持筛选和服务端分页，PDF 可匿名普通 HTTP GET，因而属于 **A 类：官方、结构化、适合批量采集**。

同时验证了两条补充路径：

- 深交所存在真实结构化基金公告接口，能够覆盖深市挂牌基金；真实样本 `159919` 可查询到 2026 年第二季度报告和 PDF，但 `000001` 在相同日期窗口返回 0 条。深交所不能替代 EID 的全行业覆盖。
- 华夏基金官网能按 `fundcode=000001` 系统性列出公告，并能从公告详情页发现直接 PDF；它是有效的管理人官网补充源，但各管理人网站没有经过验证的统一接口规范。

本次只验证了少量代表性样本，没有对全部 14,023 条 EID 记录做覆盖率审计。因此不能声称 EID PDF 系统已经对每一条 XBRL 记录达到 100% 可匹配；它是目前证据最充分、覆盖范围最广的官方主来源。

## 2. 主要样本事实

本地 EID XBRL 元数据中，主要样本为：

| 字段 | 真实值 |
| --- | --- |
| `fundCode` | `000001` |
| XBRL `uploadInfoId` | `23167397` |
| `fundShortName` | 华夏成长混合 |
| `organName` | 华夏 |
| `reportYear` | `2026` |
| `reportDesp` | 第二季度报告 |
| `uploadDate` | `2026-07-20` |
| `reportSendDate` | `2026-07-21` |
| 报告类型代码 | `FB030020` |

在 EID 公告信息系统中查询到的对应 PDF 元数据为：

| 字段 | 真实值 |
| --- | --- |
| `reportName` | 华夏成长证券投资基金2026年第二季度报告 |
| `reportYear` | `2026` |
| `reportDesp` | 第二季度报告 |
| `reportCode` | `FB030020` |
| `uploadDate` | `2026-07-20` |
| `reportSendDate` | `2026-07-21` |
| PDF 系统 `uploadInfoId` | `1534170` |
| `uploadInfoDetailId` | `1584316` |
| `fundCode` | `000001` |
| `fundShortName` | 华夏成长混合 |
| `tableName` | `PDF` |
| `correctionsNum` | `0` |

两个 `uploadInfoId` 分别是 `23167397` 和 `1534170`，明确不是同一个标识。

## 3. EID 平台自身的 PDF 来源

### 3.1 页面与真实网络请求

EID 公募基金入口：

```text
http://eid.csrc.gov.cn/fund/disclose/index.html
```

主页面中的“公告信息”加载：

```text
http://eid.csrc.gov.cn/fund/subpage/public_affiche_subpage.html
http://eid.csrc.gov.cn/fund/subpage/public_affiche_subpage.js
```

当前前端 JavaScript 明确使用下列真实资源：

```text
GET http://eid.csrc.gov.cn/fund/disclose/publicAfficheSearchData.json
GET http://eid.csrc.gov.cn/fund/disclose/advanced_search_report.do
GET http://eid.csrc.gov.cn/fund/disclose/instance_show_pdf_id.do?instanceid={PDF系统uploadInfoId}
```

其中：

- `publicAfficheSearchData.json` 返回报告类型、年份和基金类型等筛选元数据；
- `advanced_search_report.do` 返回 PDF 公告元数据；
- `instance_show_pdf_id.do` 返回 PDF 文件；
- 页面代码还会对带附件或更正稿的特殊记录使用 `fund_attach_detail.html`、`uploadInfoDetailId` 等分支，正式实现时应遵循返回字段和前端分支，不能对所有记录强行使用同一种 URL。

`publicAfficheSearchData.json` 已真实 GET 验证：HTTP 200、`Content-Type: application/json`、响应 12,561 字节，报告类型字典明确包含 `FB030020 -> 第二季度报告`。

### 3.2 PDF 公告查询接口

- URL：`http://eid.csrc.gov.cn/fund/disclose/advanced_search_report.do`
- 请求方式：GET
- 返回格式：JSON
- 登录：不需要
- Selenium：不需要
- 分页：DataTables 服务端分页
- 参数载体：查询参数 `aoData`，值为 JSON 数组

页面真实使用的业务筛选参数包括：

| 参数 | 含义 |
| --- | --- |
| `fundType` | 基金类型，可空 |
| `reportType` | 报告类型；本样本为 `FB030020` |
| `reportYear` | 报告年度；本样本为 `2026` |
| `fundCompanyShortName` | 管理人简称，可空 |
| `fundCode` | 基金代码；本样本为 `000001` |
| `fundShortName` | 基金简称，可空 |
| `startUploadDate` | 页面命名的开始日期参数 |
| `endUploadDate` | 页面命名的结束日期参数 |
| `iDisplayStart` | 分页偏移量 |
| `iDisplayLength` | 每页条数 |

本次真实请求使用 `reportType=FB030020`、`reportYear=2026`、`fundCode=000001`，日期参数留空，`iDisplayStart=0`、`iDisplayLength=20`。接口返回 HTTP 200、纯 JSON、总数 1、当前页 1 条。

精简后的真实返回示例：

```json
{
  "iTotalRecords": 1,
  "iTotalDisplayRecords": 1,
  "aaData": [
    {
      "reportName": "华夏成长证券投资基金2026年第二季度报告",
      "reportYear": "2026",
      "reportDesp": "第二季度报告",
      "reportCode": "FB030020",
      "uploadDate": "2026-07-20",
      "reportSendDate": "2026-07-21",
      "uploadInfoId": 1534170,
      "uploadInfoDetailId": 1584316,
      "fundCode": "000001",
      "fundShortName": "华夏成长混合",
      "tableName": "PDF",
      "correctionsNum": 0
    }
  ]
}
```

### 3.3 PDF 下载验证

主样本的真实 PDF URL：

```text
http://eid.csrc.gov.cn/fund/disclose/instance_show_pdf_id.do?instanceid=1534170
```

普通 HTTP GET 验证结果：

| 项目 | 结果 |
| --- | --- |
| HTTP 状态 | `200` |
| 最终 URL | 与请求 URL 相同，无重定向 |
| `Content-Type` | `application/pdf` |
| 响应大小 | 266,591 字节 |
| 文件头 | `%PDF-1.7` |
| 登录/Cookie | 不需要 |
| Selenium | 不需要 |

服务器对本次 `Range` 请求未返回分段，而是返回完整 PDF；正式下载端应同时兼容 200 和 206。

当前环境中同一路径的 HTTPS 请求发生 TLS 错误，官方页面和监管文件给出的入口也是 HTTP。因此该来源当前可自动化，但传输层只验证了 HTTP。URL 是官方、由记录 ID 驱动的确定性入口；其长期永久性没有公开契约，不能写成“永久不变”。

对于本条非更正记录，页面真实链接只使用 `instanceid=1534170`。自行附加 `uploadInfoDetailId=1584316` 会返回 404，说明必须遵循页面分支，不能因为返回了 detail ID 就无条件加入 URL。

### 3.4 EID XBRL 与 EID PDF 的匹配方法

推荐候选查询和评分字段：

1. `fundCode` 完全一致；
2. XBRL 报告类型代码与 PDF `reportCode` 一致；
3. `reportYear` 一致；
4. `reportSendDate` 一致或落在有明确限制的小窗口；
5. 标题标准化后，报告年度和“第二季度报告”等语义一致；
6. 更正稿、附件和多候选必须保留并单独判定，不可只取第一条。

EID XBRL `uploadInfoId` 仍作为 XBRL 主键，EID PDF `uploadInfoId` 应作为来源侧公告 ID 单独保存。两者之间建立匹配关系表，而不是覆盖任一 ID。

## 4. 监管依据与“集中查询入口”判断

中国证监会《关于实施〈公开募集证券投资基金信息披露管理办法〉有关问题的规定》明确：

- 中国证监会基金电子披露网站为 `http://eid.csrc.gov.cn/fund`；
- 该网站集中展示公募基金募集信息、运作信息和临时信息；
- 指定机构负责相关文件报送管理、监测监控和信息展示；
- 实施后还要求组织全行业统一报送历史基金信息披露文件。

来源：

```text
https://www.csrc.gov.cn/csrc/c101877/c1029541/1029541/files/%E9%99%84%E4%BB%B6%EF%BC%9A%E3%80%8A%E5%85%B3%E4%BA%8E%E5%AE%9E%E6%96%BD%E3%80%88%E5%85%AC%E5%BC%80%E5%8B%9F%E9%9B%86%E8%AF%81%E5%88%B8%E6%8A%95%E8%B5%84%E5%9F%BA%E9%87%91%E4%BF%A1%E6%81%AF%E6%8A%AB%E9%9C%B2%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95%E3%80%89%E6%9C%89%E5%85%B3%E9%97%AE%E9%A2%98%E7%9A%84%E8%A7%84%E5%AE%9A%E3%80%8B.pdf
```

证监会 2020 年关于 EID 正式上线的公告也说明投资者可以免费查询包括公募基金管理公司在内的依法公开披露信息：

```text
https://www.csrc.gov.cn/csrc/c100028/c1000699/content.shtml
```

因此，本次发现的 EID “公告信息”查询接口就是目前已验证的**官方基金公告集中查询接口**。没有发现另一个覆盖更广、已验证可公开批量查询的证监会或基金业协会公募基金 PDF 接口。基金业协会面向私募基金的披露系统与本任务不是同一数据范围，不能作为公募基金 PDF 来源。

## 5. 上海证券交易所来源

现有上交所基金公告接口：

```text
https://query.sse.com.cn/commonQuery.do
sqlId=COMMON_PL_JJXX_JJGG_NEW_L
```

该接口对上交所基金公告有效，能够直接返回公告标题、日期和 PDF 路径。但真实样本 `000001` 在现有跨源匹配中为 `not_found`，而 EID 公告系统可以找到同一报告。这证明上交所接口不能作为全体 EID 公募基金的唯一 PDF 来源。

监管规则也区分了指定网站与交易所网站：基金管理人、托管人和中国证监会基金电子披露网站承担公募基金指定披露职责；基金份额在交易所上市交易时，才额外涉及证券交易所网站。不能据此反向假定全部公募基金都应出现在某一交易所公告接口。

来源：

```text
https://www.csrc.gov.cn/csrc/c106256/c1653985/content.shtml
```

## 6. 深圳证券交易所来源

### 6.1 页面和真实接口

深交所基金公告页面：

```text
https://www.szse.cn/disclosure/fund/notice/index.html
```

当前页面真实加载的脚本：

```text
https://res.static.szse.cn/modules/disclosure/js/modules/fundAnnoun.min.js
```

脚本明确使用：

```text
POST https://www.szse.cn/api/disc/announcement/annList
Content-Type: application/json
```

真实请求 JSON 结构：

```json
{
  "stock": ["159919"],
  "channelCode": ["fundinfoNotice_disc"],
  "pageSize": 50,
  "pageNum": 1,
  "seDate": ["2026-07-20", "2026-07-22"],
  "type": 2
}
```

页面代码和真实请求共同确认：

- `stock` 是代码数组；
- `channelCode` 对普通基金公告使用 `fundinfoNotice_disc`；
- `seDate` 是起止日期数组；
- `pageSize`、`pageNum` 用于分页；
- 响应是 JSON，包含 `announceCount` 和 `data`。

### 6.2 覆盖边界真实验证

同一日期窗口分别查询：

1. `stock=["000001"]`：HTTP 200，返回 `{"announceCount":0,"data":[]}`；
2. `stock=["159919"]`：HTTP 200，返回 1 条：

```json
{
  "announceCount": 1,
  "data": [
    {
      "id": "dfbd3576-eab5-44bf-b222-f543b50f00b5",
      "annId": 1225433397,
      "title": "沪深300ETF嘉实：嘉实沪深300交易型开放式指数证券投资基金2026年第2季度报告",
      "publishTime": "2026-07-21 00:00:00",
      "attachPath": "/disc/disk03/finalpage/2026-07-21/720e86f0-e8cd-4625-8d0f-aa367f06f288.PDF",
      "attachFormat": "PDF",
      "secCode": ["159919"],
      "secName": ["沪深300ETF嘉实"]
    }
  ]
}
```

PDF URL 由官方文件域名与返回路径拼接：

```text
https://disc.static.szse.cn/disc/disk03/finalpage/2026-07-21/720e86f0-e8cd-4625-8d0f-aa367f06f288.PDF
```

直接 GET 并发送 `Range: bytes=0-63` 的验证结果：HTTP 206、`Content-Type: application/pdf`、`Content-Range: bytes 0-63/269921`、文件头 `%PDF-1.7`，不需要登录。

结论：深交所是**官方、结构化且适合批量采集的深市挂牌基金来源**，但对 `000001` 返回空，不能作为全体 EID 公募基金的兜底。某只基金是否“深交所 eligible”应由经过验证的挂牌/证券代码关系判断，不能只根据六位代码前缀猜测。

## 7. 基金管理人官网来源

### 7.1 华夏基金主样本

华夏基金按基金代码查询公告的真实页面：

```text
https://fund.chinaamc.com/product/publishGgList.do?fundcode=000001
```

该页面可匿名 GET，按基金代码系统性列出公告并提供分页。本次页面包含：

```text
华夏成长证券投资基金2026年第2季度报告
发布日期：2026-07-21
详情相对链接：../c/2026-07-21/995706.shtml
```

公告详情页：

```text
https://www.chinaamc.com/c/2026-07-21/995706.shtml
```

详情页真实给出的 PDF：

```text
https://www.chinaamc.com/upload/resources/file/2026/07/21/60a11f2859364144a6b512991bf0e9fa.pdf
```

直接 GET 的字节范围验证：HTTP 206、`Content-Type: application/pdf`、`Content-Range: bytes 0-63/266591`、文件头 `%PDF-1.7`，不需要登录。

该 PDF 总大小与 EID 主样本 PDF 同为 266,591 字节；本次没有下载两份完整文件并计算哈希，因此只记录“大小一致”，不声称字节完全相同。

### 7.2 是否适合作为统一来源

华夏基金官网对该管理人具有可发现的列表、分页、详情和 PDF 链路，适合作为补充与交叉校验。但基金管理人之间的网站域名、参数、分页和附件结构没有统一公开标准。没有真实证据支持用同一个接口覆盖所有管理人。

因此管理人官网分类为 **C 类：官方管理人来源，可作为补充**，不宜作为首选的全行业核心数据源。正式实施需要逐管理人适配器、健康检查和 URL 变更监测。

## 8. 来源分类

| 分类 | 来源 | 结构化程度 | 已验证覆盖 | 批量适用性 | 结论 |
| --- | --- | --- | --- | --- | --- |
| A | EID 公告信息 `advanced_search_report.do` + `instance_show_pdf_id.do` | JSON、筛选、分页、ID 驱动 PDF | `000001` 成功 | 高 | 全行业主来源候选，优先使用 |
| A（限定范围） | 上交所基金公告 API | JSONP、筛选、分页、PDF 路径 | 上交所可披露基金；`000001` 未覆盖 | 高 | 上交所挂牌/披露范围内的官方来源 |
| A（限定范围） | 深交所 `api/disc/announcement/annList` | JSON、筛选、分页、PDF 路径 | `159919` 成功；`000001` 返回 0 | 高 | 深市挂牌基金的官方来源 |
| C | 基金管理人官网 | 各家不同；华夏样本有列表和分页 | `000001` 成功 | 中低 | 补充、交叉校验、异常兜底 |
| D | 搜索引擎或第三方基金网站 | 不统一 | 本次不作为证据核心 | 低 | 只可辅助发现，不应作为核心数据源 |

没有必要把“证监会官网普通文章搜索”另列为 PDF 主源，因为真正的集中披露系统就是 EID。也未验证到另一个独立的官方全行业公募基金 PDF API。

## 9. 推荐多来源匹配架构

推荐顺序不是简单地按基金代码猜交易所，而是先用覆盖面最广的 EID 官方公告系统，再用交易所和管理人来源校验或补漏：

```text
EID XBRL record
    |
    +-- 1. EID 公告信息 API
    |      按 fundCode + reportType + reportYear 查询并完整分页
    |      再按 reportSendDate + 标题语义评分
    |      |
    |      +-- 唯一高置信候选 -> matched
    |      +-- 多个相近候选/更正稿 -> ambiguous，保留全部候选
    |      +-- 无候选 -> 进入来源补查
    |
    +-- 2. 经证券主数据确认属于上交所披露范围
    |      -> SSE announcement API
    |
    +-- 3. 经证券主数据确认属于深交所披露范围
    |      -> SZSE announcement API
    |
    +-- 4. 按 organName 路由到基金管理人官网适配器
    |      -> 官方公告列表 / 详情 / PDF
    |
    +-- 5. 仍无可靠候选
           -> not_found，并进入人工复核/覆盖率审计队列
```

建议保存以下来源标识，避免混淆：

- `xbrl_upload_info_id`：EID XBRL 主键；
- `source`：`eid_pdf`、`sse`、`szse`、`manager_site`；
- `source_announcement_id`：来源自身公告 ID；
- `source_detail_id`：更正稿等来源侧 detail ID，可空；
- `pdf_url`、`announcement_title`、`announcement_date`；
- `match_score`、`match_status`、`matched_fields`；
- `http_status`、`content_type`、`content_length`、可选文件哈希。

对于 EID 公告系统，应先根据元数据字段判断普通 PDF、更正稿或附件分支，再生成页面真实使用的 URL。不要把 PDF URL 或 `fundCode + reportYear` 当作 XBRL 唯一键。

## 10. 仍可能无法覆盖的情况

以下情况仍可能产生 `ambiguous` 或 `not_found`：

1. EID XBRL 与 PDF 公告系统对同一报告的标题、日期或基金代码记录不一致；
2. 同一基金同日存在原稿、更正稿、不同份额或多份附件，且自动评分无法唯一判定；
3. 较早历史数据尚未迁移、附件路径失效或记录缺字段；
4. 已清盘、合并、改名或代码变更的基金，需要历史证券主数据才能建立关系；
5. 特殊公募产品、香港互认基金等是否与当前 PDF 查询接口完全同构，本次未逐类验证；
6. 只在管理人或托管人网站保留、EID 查询暂时缺失的异常记录；
7. EID 当前仅验证 HTTP，网络或 TLS 策略变化可能影响自动化可用性。

## 11. 已验证

- `000001 / 23167397` 的 XBRL 报告名称、年度、上传日期和送出日期；
- EID 当前页面真实使用 `publicAfficheSearchData.json`、`advanced_search_report.do` 和 `instance_show_pdf_id.do`；
- EID PDF 查询对 `FB030020 / 2026 / 000001` 返回唯一真实记录；
- EID XBRL ID `23167397` 与 PDF 公告 ID `1534170` 不同；
- EID PDF 普通 HTTP GET 返回 200、`application/pdf`、266,591 字节，无需登录；
- EID 同一路径 HTTPS 在当前环境发生 TLS 错误；
- 深交所基金公告页面当前脚本、JSON POST 接口和分页参数结构；
- 深交所查询 `000001` 返回 0，查询 `159919` 返回第二季度报告；
- 深交所 PDF 直链支持匿名 GET 和 Range，返回有效 PDF；
- 华夏基金 `000001` 公告列表、详情页和 PDF 的系统性发现链路；
- 华夏基金 PDF 支持匿名 GET 和 Range；
- 证监会文件明确 EID 是公募基金信息集中展示与统一接收平台；
- 全部核心链路不需要 Selenium。

## 12. 未验证

- EID 公告 PDF 对全部 14,023 条 XBRL 记录的实际匹配覆盖率；
- EID PDF 公告 ID 与 XBRL ID 是否存在未公开的内部映射；当前公开响应没有共同 ID；
- EID 各类更正稿、多附件、净值日报和特殊临时公告的所有 URL 分支；
- EID PDF URL 的官方长期稳定性承诺，以及未来是否提供 HTTPS；
- 上交所和深交所对各自全部基金品种、全部历史年份的覆盖率；
- 跨市场、转板、退市/清盘、改名和代码变更基金的完整证券主数据来源；
- 除华夏基金外，各管理人官网接口的结构、稳定性和历史深度；
- 托管人官网是否能作为规模化补充来源；
- 香港互认基金、特殊公募产品是否全部进入当前 `advanced_search_report.do` PDF 数据集。

## 13. 调研边界

本次仅执行少量页面、JavaScript、JSON 和 PDF 字节范围请求，并对 EID 主样本做了一次 PDF 响应验证。没有修改现有 SSE 匹配代码，没有编写多来源 crawler，没有批量下载 PDF，没有处理全量 14,023 条记录，也没有解析 PDF、HTML facts 或原始 XBRL。
