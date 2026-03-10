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
- OneBot V11 实现端（目前已知 LLONEBOT 支持文件转永久操作，其他未知）注意！需要开启上报机器人消息！！
- 测试端建议使用 [LuckyLilliaBot](https://github.com/LLOneBot/LuckyLilliaBot)


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
| 命令 | 别名 | 说明 |
|---|---|---|
| `qpan help` | `群盘 帮助` | 显示帮助 |
| `qpan list [page] [0/1]` | `群盘 列表` | 文件分页列表；`0`=非永久，`1`=永久 |
| `qpan search <keyword>` | `群盘 搜索` | 按文件名关键词搜索 |
| `qpan info` | `群盘 总盘` | 查看总空间、已用空间、群盘数量 |
| `qpan get <uid \| /file_id>` | `群盘 获取` | 转发指定文件到当前群；uid无前缀，file_id以`/`开头 |
| `qpan remove <uid \| /file_id \| all>` | `群盘 删除` | 删除指定文件或批量删除；支持 `all nonpermanent` 或 `all repeated` |
| `qpan refresh` | `群盘 刷新` | 手动触发过期消息记录刷新 |

## 📖 使用示例

### 查看与搜索
```text
qpan list              # 显示第1页（10条/页）
qpan list 2            # 显示第2页
qpan list 1 1          # 显示第1页的永久文件
qpan search 报告       # 搜索文件名包含"报告"的文件
qpan info              # 查看总容量和使用情况
```

### 获取文件（转发到当前群）
```text
qpan get 7K9mXpQ2w     # 通过uid获取（uid在list/search输出中）
qpan get /c56bcc83...  # 通过file_id获取（以/开头），若未记录则自动下载重传
```

### 删除文件
```text
qpan remove 7K9mXpQ2w      # 删除指定uid的文件
qpan remove /c56bcc83...   # 删除指定file_id的文件
qpan remove all nonpermanent  # 删除所有非永久文件
qpan remove all repeated    # 删除所有重复文件（按名称和大小判断）
```

### 其他
```text
qpan refresh           # 手动刷新过期记录（防止文件消息失效）
```

## ⚙️ 上传处理流程

收到 `group_upload` 后：

1. 读取上传信息（群号、文件名、大小）。
2. 计算当前群盘空间使用率。
3. **空间充足**：直接尝试设置文件为永久保存。
4. **空间不足**：查找可用目标群，优先通过 `forward_group_single_msg` 零下载转发（需文件由聊天框拖入产生过消息记录）；若无消息记录则回退到 HTTP 下载后重新上传。

## 📨 文件消息记录机制

- **消息监听**：监听所有消息，检测 `[CQ:file,...]` 格式，提取 `file_id`、`message_id` 和文件元数据。
- **持久化存储**：记录存储于 `src/plugins/file_messages.json`（最多保留 100 条，FIFO 淘汰）。
- **记录字段**：每条记录包含 `file_id`、`uid`、`message_id`、`timestamp`、`group_id`、`file_name`、`file_size`。
- **自动刷新**：后台每 1 小时检查一次，对超过 0.5 天未刷新的记录自动重新转发，更新 `message_id` 以防因平台失期而失效。
- **uid 稳定性**：当文件被转移到不同群盘时，系统通过"文件名 + 大小 + 群号"的特征匹配自动复用已有的 uid，保证查询连贯性。

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

## 🔐 uid 与 file_id

- **uid**: 稳定的文件唯一标识符（使用 shortuuid），不会因群盘位置变化而改变。
- **file_id**: QQ 平台的文件 ID，当文件移入不同群盘时会变化（系统会自动追踪并保持uid不变）。
- **get/remove命令** 均支持两种查询方式：
  - `uid`：直接输入（无前缀），用于已记录的文件
  - `file_id`：以`/`开头输入，用于查询群盘中的文件

## ⚠️ 当前限制与注意事项

### 文件转发与传输
- **零下载转发**：仅支持通过**聊天框拖入**的文件（产生消息事件）；通过文件面板上传的文件无消息记录，只能走 HTTP 下载后重新上传的路径。
- **自动去重**：删除重复文件时，以"文件名 + 文件大小"作为重复判断标准。

### 平台与兼容性
- OneBot 实现差异：`set_group_file_forever`、`forward_group_single_msg` 及文件 CQ 码的支持度因实现端而异，需在目标环境验证。
- 频率限制：平台对某些操作有限流，重试仍可能失败，需适当调整延迟参数。
- **推荐实现端**：[LuckyLilliaBot](https://github.com/LLOneBot/LuckyLilliaBot)（基于 LLONEBOT）

## � 工作流程速览

### 文件上传时
1. 机器人监听 `group_upload` 事件，读取文件信息（名称、大小）。
2. 计算当前群盘空间使用率。
3. **空间充足** → 直接尝试设置为永久保存。
4. **空间不足** → 查找可用目标群，优先用"零下载转发"；无消息记录则回退"HTTP下载后重传"。
5. 自动更新 `file_messages.json` 记录（含新分配的 uid）。

### 文件查询/转发时
1. 用户通过 `qpan get <uid|/file_id>` 查询。
2. 系统在记录中查找，若 file_id 已变化则触发特征匹配更新。
3. 通过 `forward_group_single_msg` 或文件下载链接将文件转发到当前群。

### 文件定期刷新时
1. 后台定期扫描过期记录（超 0.5 天）。
2. 重新转发原消息以获取新的 `message_id`。
3. 更新时间戳，延长有效期。

## 🛠️ 开发与调试

### 代码质量检查
```bash
ruff check src/
ruff check src/ --fix
pyright src/
```

### 手动测试
```bash
# 查看日志输出
nb run

# 监听关键事件
# - group_upload：文件上传到群文件
# - message：聊天框发送文件
# - message_sent：机器人自身发送的消息
```

## � 常见问题

**Q: 删除文件失败？**
A: 可能的原因：
- 文件已被其他人删除
- 没有对应群的删除权限
- OneBot 实现端不支持 `delete_group_file`

尝试用Web操作手动删除，或检查机器人权限。

**Q: get 命令说"找不到file_id"？**
A: 可能是：
- file_id 已过期（群盘文件被清理）
- 输入的 file_id 不存在
- 机器人无法访问该群盘

**Q: 刷新操作没有生效？**
A: 默认每小时自动刷新一次。也可手动运行 `qpan refresh`。若失败可能是：
- 群文件对应的消息已被撤回
- 平台限流导致操作失败

**Q: 重复文件怎么判断？**
A: 按"文件名"和"文件大小"两维度判断，保留首次出现的，删除后续重复项。

## �📄 许可证

MIT
