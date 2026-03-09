# qPan

> 一个偏自动化的 QQ 群文件网盘管家，基于 NoneBot2 + OneBot V11。

## ✨ 这是什么

`qPan` 面向"多个群当作分片网盘"的场景，核心能力如下：

- 📥 监听群文件上传事件，自动设置永久保存。
- 🚀 空间不足时零下载转发文件到有空余的群盘（无流量消耗）。
- 💾 持久化记录文件消息，支持后台定期刷新保活。
- 📊 汇总多个群盘空间状态。
- 🔎 文件列表与关键词搜索，支持按需取回文件。

## 🧩 环境要求

- Python `>=3.10`
- `nonebot2[fastapi,websockets] >= 2.4.4`
- `nonebot-adapter-onebot >= 2.4.6`
- OneBot V11 实现端（目前已知 LLONEBOT 支持文件转永久操作，其他未知）

## 🚀 快速启动

```bash
nb run
```

Windows 启动：

```bash
qstart.bat
```

默认连接方式为 reverse WebSocket，地址：`ws://127.0.0.1:8080/onebot/v11/ws`

## 🏷️ 群筛选规则

群名包含 `qpan` 才会被识别为"群盘池"。

示例：

- `qpan-01`
- `我的qpan备份群`

## 🧠 命令速查

| 命令 | 别名 | 说明 |
|---|---|---|
| `qpan help` | `群盘 帮助` | 显示帮助 |
| `qpan list [page] [0/1]` | `群盘 列表` | 文件分页列表；`0`=非永久，`1`=永久 |
| `qpan search <keyword>` | `群盘 搜索` | 按文件名搜索 |
| `qpan info` | `群盘 总盘` | 查看总空间、已用空间、群盘数量 |
| `qpan get <file_id>` | `群盘 获取` | 将指定文件转发到当前群 |
| `qpan refresh` | `群盘 刷新` | 手动触发过期消息记录刷新 |

常用示例：

```text
qpan list
qpan list 2
qpan list 1 1
qpan search 报告
qpan info
qpan get /c56bcc83-678b-4454-8bab-c6eb99b0dc6d
qpan refresh
```

## ⚙️ 上传处理流程

收到 `group_upload` 后：

1. 读取上传信息（群号、文件名、大小）。
2. 计算当前群盘空间使用率。
3. **空间充足**：直接尝试设置文件为永久保存。
4. **空间不足**：查找可用目标群，优先通过 `forward_group_single_msg` 零下载转发（需文件由聊天框拖入产生过消息记录）；若无消息记录则回退到 HTTP 下载后重新上传。

## 📨 文件消息记录机制

- 监听所有消息，检测 `[CQ:file,...]` 格式，提取 `file_id` 和 `message_id`。
- 记录存储于 `src/plugins/file_messages.json`，最多保留 100 条（FIFO 淘汰）。
- 每条记录含 `message_id`、`timestamp`、`group_id`、`file_name`。
- 后台每小时检查一次，对超过 0.5 天未刷新的记录自动重新转发以更新 `message_id`（防过期失效）。

## 📁 项目结构

```text
qPan/
 src/
   plugins/
      qpan.py
      file_messages.json   # 自动生成，文件消息持久化
 downloads/                 # 临时下载目录（自动创建）
 pyproject.toml
 qstart.bat
 README.md
```

## ⚠️ 当前限制

- 零下载转发仅支持通过**聊天框拖入**的文件（产生消息事件）；通过文件面板上传的文件无消息记录，只能走下载重传路径。
- `set_group_file_forever` 受平台限流影响，重试后仍可能失败。
- 不同 OneBot 实现端对 `forward_group_single_msg` 和文件 CQ 码的兼容性存在差异，需在目标环境验证。

## 🛠️ 开发检查

```bash
ruff check src/
ruff check src/ --fix
pyright src/
```

## 📄 许可证

MIT
