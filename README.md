# qPan

基于 NoneBot2 + OneBot V11 的 QQ 群文件网盘管理插件。

## 项目定位

`qPan` 面向“多群作为分片网盘”的使用场景，提供以下能力：

- 监听群文件上传事件。
- 汇总多个群盘空间信息。
- 查询文件列表、搜索文件。
- 尝试将上传文件设置为永久。
- 在空间不足时尝试转移到其他有空余空间的群。

## 环境要求

- Python `>=3.10`
- `nonebot2[fastapi,websockets] >= 2.4.4`
- `nonebot-adapter-onebot >= 2.4.6`
- OneBot V11 实现端（如 Lagrange / go-cqhttp）

## 快速启动

```bash
pip install -e .
```

Windows:

```bash
qstart.bat
```

## 群筛选规则

插件会把群名中包含 `qpan` 的群识别为“群盘池”。

示例：

- `qpan-01`
- `我的qpan备份群`

## 命令说明

| 命令 | 说明 |
|---|---|
| `qpan help` | 显示帮助 |
| `qpan list [page] [0/1]` | 列表分页；`0`=非永久，`1`=永久 |
| `qpan search <keyword>` | 搜索文件名 |
| `qpan info` | 查看总空间、已用空间、群盘数量 |

示例：

```text
qpan list
qpan list 2
qpan list 1 1
qpan search 报告
qpan info
```

## 上传事件处理流程

当收到 `group_upload`：

1. 读取上传文件信息（群号、文件名、大小）。
2. 统计当前群盘空间使用率。
3. 若空间不足，查找可用目标群并尝试转移。
4. 若空间充足，尝试设置文件为永久。

## 当前实现限制

- 当前逻辑对“中文文件名”采取拦截提示，不直接处理。
- `set_group_file_forever` 可能受平台限流影响，已包含重试，但仍可能失败。
- 不同 OneBot 实现端对 CQ `file` 细节兼容性不同，建议在目标实现端单独验证。

## 目录结构

```text
qPan/
├─ src/plugins/qpan.py
├─ pyproject.toml
├─ qstart.bat
└─ README.md
```

## 开发与检查

```bash
ruff check src/
ruff check src/ --fix
pyright src/
```

## 许可证

MIT

