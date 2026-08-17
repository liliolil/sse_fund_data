# 2026 年第二季度 XBRL 元数据 EID PDF 覆盖率审计

审计日期：2026-08-14（Asia/Shanghai）

## 1. 审计范围

数据来源：

```text
data/processed/xbrl_metadata.parquet
```

筛选条件：

```text
reportTypeCode = FB030020
reportYear = 2026
```

筛选分区共有 14,023 条 XBRL 元数据、14,023 个不同 `fundCode`、164 个不同 `organName`。该分区没有缺失 `organName`、没有重复 XBRL `uploadInfoId`。

本次只审计 100 条，不修改或追加 `data/processed/xbrl_pdf_links.parquet`。

## 2. 样本选择方法

固定随机种子：

```text
20260814
```

选择方法：

1. 对分区内 164 个非空 `organName` 排序；
2. 使用 NumPy `default_rng(20260814)` 无放回随机选择 100 个管理人；
3. 在每个选中管理人的记录中，再使用同一随机数生成器随机选择 1 条；
4. 检查最终 XBRL `uploadInfoId` 不重复。

这不是顺序取前 100 条。最终样本包含：

- 100 条 XBRL 记录；
- 100 个不同管理人；
- 100 个不同基金代码；
- 100 个不同基金简称；
- XBRL 主键重复数为 0。

该方案优先评估不同管理人的跨机构覆盖能力。它是“管理人多样性平衡样本”，不是按各管理人记录数量加权的简单随机样本，因此 99% 结果不应直接解释为全部 14,023 条的精确总体覆盖率。

样本的 `reportSendDate` 构成：

| reportSendDate | 数量 |
| --- | ---: |
| 2026-07-14 | 1 |
| 2026-07-15 | 1 |
| 2026-07-16 | 1 |
| 2026-07-17 | 1 |
| 2026-07-18 | 5 |
| 2026-07-20 | 21 |
| 2026-07-21 | 70 |

完整样本和逐条结果保存在：

```text
data/processed/xbrl_pdf_coverage_sample.parquet
```

## 3. 查询与匹配方法

每条样本使用现有 EID 公告 crawler 查询：

```text
GET http://eid.csrc.gov.cn/fund/disclose/advanced_search_report.do
```

查询条件为该条 XBRL 的：

- `reportTypeCode`；
- `reportYear`；
- `fundCode`。

执行规则：

- 顺序、单线程请求；
- 相邻业务请求至少间隔 0.25 秒；
- 使用现有有限重试 Session；
- 按接口总数完整分页；
- 一个基金已经取得完整候选后不重复查询；
- 网络、HTTP 或响应解析异常单独记为 `request_error`，不转换成 `not_found`；
- 使用现有匹配评分和阈值，没有为了本次审计放宽规则。

100 条样本共请求 100 个 EID 结果页。每条均在第一页完成，候选数量分布为：

| 候选数 | 样本数 |
| ---: | ---: |
| 1 | 99 |
| 2 | 1 |

## 4. 覆盖率结果

| 状态 | 数量 | 比例 |
| --- | ---: | ---: |
| `matched` | 99 | 99.00% |
| `ambiguous` | 1 | 1.00% |
| `not_found` | 0 | 0.00% |
| `requires_special_handling` | 0 | 0.00% |
| `request_error` | 0 | 0.00% |
| 合计 | 100 | 100.00% |

99 条 `matched` 均是唯一最高分候选，基金代码、报告类型、报告年度、报告送出日期和标题语义符合现有严格匹配条件，并落入已经验证的普通 PDF URL 分支。

## 5. PDF URL 轻量验证

本次没有批量下载 PDF，也没有把 PDF 保存到本地。

从审计结果中固定取前 10 条 `matched` 记录，对每个 URL 发送带 `Range: bytes=0-63` 的流式 GET。EID 可能忽略 Range 并返回 HTTP 200，因此客户端只读取响应流前 8 字节后立即关闭连接。

结果：

- 轻量检查数量：10；
- HTTP 响应及文件头有效：10；
- `Content-Type` 为 PDF、文件头以 `%PDF` 开始：10；
- 未完整下载或保存 PDF。

其余 89 条 `matched` 只验证了匹配元数据和普通 PDF URL 构造，没有发起 PDF 请求。

## 6. 非 matched 样本明细

本次只有 1 条 `ambiguous`，没有 `not_found`、`requires_special_handling` 或 `request_error`。

| 字段 | 值 |
| --- | --- |
| `xbrl_upload_info_id` | `23170443` |
| `fundCode` | `025736` |
| `fundShortName` | 华西科技成长 |
| `organName` | 华西 |
| `reportSendDate` | `2026-07-21` |
| 状态 | `ambiguous` |
| 候选数量 | 2 |
| 原因 | 两条候选匹配得分均为 100，不能强制选择 |

两个真实候选具有相同的：

- `pdf_upload_info_id = 1530958`；
- `fundCode = 025736`；
- `reportCode = FB030020`；
- `reportYear = 2026`；
- `reportSendDate = 2026-07-21`；
- 报告标题；
- `correctionsNum = 1`。

但二者的来源侧明细不同：

| 候选 | `uploadInfoDetailId` | `operationUploadType` |
| --- | ---: | --- |
| 1 | `1581090` | `9090-1010` |
| 2 | `1591115` | `9090-1030` |

这属于真实更正/明细分支歧义。现有逻辑正确保留为 `ambiguous`，本次没有猜测 URL，也没有为了提高覆盖率选择其中一条。

## 7. 失败原因分类

| 原因分类 | 数量 | 说明 |
| --- | ---: | --- |
| 同一 PDF 公告 ID 存在多个更正明细候选 | 1 | 相同 PDF ID、不同 detail ID，得分并列 |
| EID 无候选 | 0 | 本样本未出现 |
| 候选得分不足 | 0 | 本样本未出现 |
| 无法确认的单一特殊分支 | 0 | 本样本未出现 `requires_special_handling` |
| 网络/HTTP/响应错误 | 0 | 本样本未出现 `request_error` |

## 8. 是否建议进入 14,023 条全量处理

**建议进入 2026 年第二季度这 14,023 条记录的分批全量元数据匹配，但不建议同时批量下载 PDF。**

依据：

- 100 个不同管理人的平衡样本中，严格规则匹配成功 99%；
- 没有发现 EID 无候选、低分候选或请求错误；
- 唯一失败属于可解释的更正明细歧义，现有状态模型可以安全保留；
- 三个既有真实样本和本次 100 条审计结果方向一致。

全量前仍应保留以下控制：

1. 分批执行并保存检查点，例如每批 100—500 条；
2. `ambiguous`、`requires_special_handling`、`request_error` 分开保存；
3. 网络错误重试耗尽后进入重试队列，不写成 `not_found`；
4. 不自动选择更正稿并列候选；
5. 先只保存公告元数据和 URL，PDF 下载作为独立阶段；
6. 全量结束后按状态、管理人、送出日期和候选数生成覆盖报告。

## 9. 预计全量请求量

该分区 14,023 条记录对应 14,023 个不同基金代码，因此按当前“每条 XBRL 使用基金代码查询一次”的安全策略，不能通过同代码缓存明显减少查询。

根据本次样本每个查询均为一页：

- 预计最低业务查询页数：约 14,023 页；
- 若少数基金出现超过 20 条候选，会增加分页请求；
- 临时错误的有限重试会增加底层 HTTP 尝试次数；
- 本次没有记录到需要额外分页的样本。

按请求间隔 0.25 秒计算，仅固定间隔的理论下限约为 3,506 秒，即约 58 分钟；加上网络响应、落盘和重试，实际应按约 1—2 小时的分批任务设计。该估算不包含 PDF 下载请求。

## 10. 数据文件字段

`xbrl_pdf_coverage_sample.parquet` 每条审计记录至少包含：

- 固定种子和样本序号；
- XBRL ID、基金代码、基金简称、管理人和报告送出日期；
- PDF ID、PDF detail ID、候选公告标题和 URL；
- `source=eid_pdf`；
- 匹配分数、状态、候选数量和原因；
- 查询页数与接口总数；
- 少量 PDF URL 的轻量 HTTP 验证结果。

该文件的 XBRL 主键重复数为 0，基金代码 `000001` 等值按字符串保存。本次没有写入正式 `xbrl_pdf_links.parquet`。

## 11. 测试结果

运行命令：

```text
pytest tests/test_xbrl.py tests/test_xbrl_incremental.py tests/test_xbrl_pdf_match.py tests/test_eid_fund_announcement.py -v
```

结果：

```text
23 passed in 1.25s
```

没有 warning。本次审计没有新增正式业务逻辑，因此没有修改代码或新增测试文件。
