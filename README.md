# qPan

> 一个偏自动化的 QQ 群文件网盘管家，基于 NoneBot2 + OneBot V11。

## ✨ 这是什么

`qPan` 面向“多个群当作分片网盘”的场景，核心能力如下：

- 📥 监听群文件上传事件。
- 📊 汇总多个群盘空间状态。
- 🔎 文件列表与关键词搜索。
- 💾 自动尝试将上传文件设置为永久。
- 🔄 空间不足时尝试转移到有空余的群盘。

## 🧩 环境要求

- Python `>=3.10`
- `nonebot2[fastapi,websockets] >= 2.4.4`
- `nonebot-adapter-onebot >= 2.4.6`
- OneBot V11 实现端（目前已知LLONEBOT支持文件转永久操作，其他未知）

## 🚀 快速启动

```bash
nb run
```

Windows 启动：

```bash
qstart.bat
```

## 🏷️ 群筛选规则

群名包含 `qpan` 才会被识别为“群盘池”。

示例：

- `qpan-01`
- `我的qpan备份群`

## 🧠 命令速查

| 命令 | 说明 |
|---|---|
| `qpan help` | 显示帮助 |
| `qpan list [page] [0/1]` | 文件分页列表；`0`=非永久，`1`=永久 |
| `qpan search <keyword>` | 按文件名搜索 |
| `qpan info` | 查看总空间、已用空间、群盘数量 |

常用示例：

```text
qpan list
qpan list 2
qpan list 1 1
qpan search 报告
qpan info
```

## ⚙️ 上传处理流程

收到 `group_upload` 后：

1. 读取上传信息（群号、文件名、大小）。
2. 计算当前群盘空间使用率。
3. 空间不足则查找可用目标群并尝试转移。
4. 空间充足则尝试设置文件为永久。

## ⚠️ 当前限制

- 中文文件名目前会被拦截并提示，不直接处理。
- `set_group_file_forever` 受平台限流影响，重试后仍可能失败。
- 不同 OneBot 实现端对 CQ `file` 兼容性存在差异，需在目标环境验证。

## 📁 项目结构

```text
qPan/
├─ src/plugins/qpan.py
├─ pyproject.toml
├─ qstart.bat
└─ README.md
```

## 🛠️ 开发检查

```bash
ruff check src/
ruff check src/ --fix
pyright src/
```

## 📄 许可证

MIT

