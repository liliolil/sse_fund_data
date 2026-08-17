# v1.0 架构说明

项目采用简单分层，避免把传输、业务流程和存储耦合在一个文件中：

```text
Official SSE / EID HTTP sources
              ↓
Crawler：请求、重试、分页、JSON/JSONP/XML 解析、原始字段映射
              ↓
Service：质量检查、合并去重、增量或回填决策
              ↓
Parquet / raw evidence / state checkpoint
              ↓
CLI：status、update、backfill、test
              ↓
watch：按模块分级间隔调用同一 update 调度
```

## 核心语义

- `update`：检查官方最新数据，只在出现新数据或已识别修订时写入。
- `backfill`：对已验证支持历史参数的数据源查询指定范围；不支持的模块明确拒绝。
- `incremental`：使用本地主键、最新日期或 checkpoint 与远程结果比较，避免重复追加。
- `snapshot`：记录查询时可见状态，不代表能够恢复查询前的历史，例如逐基金行情快照。
- `state`：保存最近检查时间、状态、远程/本地日期或模块配置；它不是业务数据主表。

## 路径和存储安全

`src/config/paths.py` 通过自身文件位置向上推导 `PROJECT_ROOT`，所有正式默认路径均以项目根目录为基准。测试可以显式传入 `tmp_path`，不会污染正式数据。

结构化数据主要使用 Parquet。关键 service 在完成合并和质量检查后再保存；基础存储使用同目录临时文件和 `os.replace` 进行原子替换。原始 XML、HTML 或 JSON 与清洗后的 Parquet 分开保存。

## 调度和日志

CLI 是唯一统一入口。`update all` 顺序运行已注册模块并汇总成功/失败；watch 复用同一 update 调度，不复制 crawler/service 逻辑。日志写入项目 `logs/`，采用标准库轮转 handler；终端仅显示简洁状态。
