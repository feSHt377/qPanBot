#全自动q群文件网盘管理
import asyncio
import json
import os
import re
import time
from types import SimpleNamespace

import httpx
import shortuuid
from nonebot import get_driver, on, on_command, on_message, on_notice
from nonebot.adapters.onebot.v11 import Bot, Event, Message
from nonebot.exception import FinishedException
from nonebot.params import CommandArg
from nonebot.typing import T_State
from pypinyin import Style, lazy_pinyin


def convert_chinese_to_pinyin(filename: str) -> str:
    """将中文文件名转换为拼音，保留扩展名和非中文字符"""
    # 分离文件名和扩展名
    if "." in filename:
        name_parts = filename.rsplit(".", 1)
        name = name_parts[0]
        ext = "." + name_parts[1]
    else:
        name = filename
        ext = ""

    # 转换为拼音（无音调，小写）
    pinyin_name = "".join(lazy_pinyin(name, style=Style.NORMAL))
    return pinyin_name + ext


async def get_qpan_groups(bot: Bot):
    # 获取所有群列表
    groups = await bot.get_group_list() # type: ignore
    # 过滤出包含 "qpan" 的群
    qpan_groups = [group for group in groups if "qpan" in group["group_name"]] # type: ignore
    return qpan_groups
async def get_qpan_files(bot: Bot):
    # 获取所有群的根目录文件列表
    qpan_groups = await get_qpan_groups(bot) # type: ignore
    file_list = []
    for group in qpan_groups:
        files = SimpleNamespace(**await bot.get_group_root_files(group_id=group["group_id"])).files # type: ignore
        # files.group_name = group["group_name"] # type: ignore
        for file in files:
            file["group_name"] = group["group_name"] # type: ignore # 给每个文件对象添加所属群名称属性
        file_list.extend(files) # 将每个群的文件列表合并到一个总列表中

    # 按文件名排序（忽略大小写）
    file_list.sort(key=lambda f: f["file_name"].lower())

    return file_list 

# 获取群盘文件系统信息，计算总空间和已用空间
async def get_qpan_file_info(bot: Bot , group_id = None):
    if group_id is None:
        qpan_group = await get_qpan_groups(bot) # type: ignore # 获取所有群盘信息
    else:
        qpan_group = [group for group in await get_qpan_groups(bot) if group["group_id"] == group_id] # type: ignore # 获取指定群盘信息
    
    used_space = 0
    total_space = 0
    for group in qpan_group:
        re = SimpleNamespace(**await bot.get_group_file_system_info(group_id=group["group_id"])) # type: ignore
        used_space += re.used_space
        total_space += re.total_space
    class QPanInfo:
        def __init__(self, used_space, total_space, group_count):
            self.used_space = used_space
            self.total_space = total_space
            self.group_count = group_count
    
    return QPanInfo(used_space, total_space, len(qpan_group))
    # print(re)

async def get_qpan_group_with_enough_space(bot: Bot, file_size: int):
    # 获取所有群盘信息，找到一个剩余空间足够存储指定文件大小的群盘
    qpan_groups = await get_qpan_groups(bot) # type: ignore
    for group in qpan_groups:
        info = await get_qpan_file_info(bot, group_id=group["group_id"]) # type: ignore
        if info.total_space - info.used_space >= file_size:
            return group["group_id"] # type: ignore 返回第一个满足条件的群ID
    return None # 如果没有找到满足条件的群盘，返回None

# 由于傻逼qq群文件换地方会导致file_id变化，所以设置永久保存时不能用file_id作为参数，而是只能通过文件名和大小来设置，因此这个函数会有一定的误判风险，如果同名同大小的文件存在的话可能会设置错误的文件为永久保存，后续可以考虑增加一些其他的判断条件来提高准确性，例如文件的上传时间等
async def set_qpan_file_forever(bot: Bot, file_size : int, file_name: str, group_id: int, max_retries: int = 3):
    # 设置文件永久保存，带重试机制
    for attempt in range(max_retries):
        try:
            await asyncio.sleep(0.35)  # 延迟 0.35 秒后再调用
            files = await get_qpan_files(bot) # type: ignore 获取当前群盘文件列表
            target_file = next((f for f in files if f["file_name"] == file_name and f["file_size"] == file_size and f["group_id"] == group_id), None) # type: ignore # 找到对应的文件信息
            if target_file is None:
                raise ValueError(f"未在群 {group_id} 中找到文件 {file_name}（大小 {file_size}），可能尚未同步")  # noqa: TRY003, TRY301
            await bot.set_group_file_forever(file_id=target_file["file_id"], group_id=group_id) # type: ignore
            break  # 成功则跳出重试循环
        except Exception as e:
            print(f"设置永久保存失败（第{attempt + 1}次）：{e}")
            if attempt == max_retries - 1:
                break #不退出函数，只记录错误日志，继续后续操作
    await asyncio.sleep(2)  # 等待一段时间让设置生效

    qpan_files = await get_qpan_files(bot) # type: ignore
    for file in qpan_files:
        if file["file_name"] == file_name and file["file_size"] == file_size and file["group_id"] == group_id and file["dead_time"] == 0: # type: ignore # 找到对应的文件信息# 更新文件的过期时间为0，表示永久保存
            return True

    return False # 如果没有找到对应的文件，返回False表示设置失败

async def send_file_to_group(bot: Bot, group_id: int, file_id: str) -> bool:
    """通过转发原始消息将文件发送到目标群，不触发下载"""
    info = _find_file_message(file_id)
    if info is None:
        print(f"未找到 file_id={file_id} 的原始消息记录，无法转发（仅支持通过聊天框发送的文件，文件面板上传不产生消息事件）")

        files = await get_qpan_files(bot) # type: ignore # 尝试刷新文件列表，可能会更新 file_messages 中的记录
        file_url = None
        file_name_fallback = file_id  # 兜底文件名
        for file in files:
            if file["file_id"] == file_id : # type: ignore
                file_url = (await bot.get_group_file_url(file_id=file_id, group_id=file["group_id"]))["url"] # type: ignore
                file_name_fallback = file["file_name"]  # type: ignore
        if file_url is None:
            await bot.send_group_msg(group_id=group_id, message=f"未找到 file_id={file_id} ,是否从未上传过？") # type: ignore
            return False
        await bot.send_group_msg(group_id=group_id, message=f"未找到 file_id={file_id} 的原始消息记录，无法转发，开始重新下载上传") # type: ignore
        # await bot.upload_group_file(group_id=group_id, file=file_url, name=file_name_fallback) # type: ignore
        # await download_file_by_url(file_url, file_name_fallback) # type: ignore

        #创建transfer_file_to_free_group任务
        asyncio.create_task(transfer_file_to_free_group(bot, file_id, group_id, file_name_fallback, 0)) # type: ignore # 直接调用转移函数，文件大小未知暂时传0，转移函数会处理下载和上传到有空间的群盘

        # await bot.send_group_msg(group_id=group_id, message=f"[CQ:file,file_id={file_id},file={file_name_fallback},url=,path={file_url}]") # type: ignore
        return False
    try: # == else: try:
        await bot.forward_group_single_msg(group_id=group_id, message_id=info["message_id"])  # type: ignore
        return True  # noqa: TRY300
    except Exception as e:
        print(f"转发文件失败：{e}")
        return False

DOWNLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "downloads"))  # noqa: PTH100
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


async def download_file_by_url(url: str, file_name: str) -> str:
    """通过 HTTP 直接下载文件到本地 downloads 目录"""
    try:
        print(f"开始下载文件到{DOWNLOAD_DIR}：{file_name}，URL: {url}")
        file_path = os.path.join(DOWNLOAD_DIR, file_name)
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30, read=120, write=30, pool=30), follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(file_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            print(f"\r下载 {file_name}: {downloaded/1024/1024:.2f}/{total/1024/1024:.2f} MB ({downloaded*100//total}%)", end="", flush=True)
                        else:
                            print(f"\r下载 {file_name}: {downloaded/1024/1024:.2f} MB", end="", flush=True)
                print()  # 换行
    except Exception as e:
        print(f"下载文件失败：{e}")
        raise
    print(f"下载完成 {file_path}")
    return file_path



async def transfer_file_to_free_group(bot: Bot, file_id : str , group_id: int, file_name: str, file_size: int):
    """后台执行文件转移：直接 HTTP 下载 -> 上传到有空间的群盘"""
    file_path = ""
    #file_name = file_name.replace(":", "_").replace("*", "_").replace("?", "_").replace('"', "_").replace("<", "_").replace(">", "_").replace("|", "_").replace(" ", "_")  # 替换文件名中的斜杠，避免路径问题
    try:
        files = await get_qpan_files(bot) # type: ignore # 刷新文件列表，确保 file_id 对应的文件信息已更新到 file_messages 中
        target_group_id = next((f["group_id"] for f in files if f["file_id"] == file_id), group_id) # type: ignore # 获取文件所属的群ID，优先使用最新的文件列表信息
        file_url = (await bot.get_group_file_url(file_id=file_id, group_id=target_group_id))["url"] # type: ignore
        if not file_url:
            await bot.send_group_msg(group_id=group_id, message=f"未找到 file_id={file_id} 的下载链接，无法转移") # type: ignore
            return
        print("111111111111111111111111111")
        file_path = await download_file_by_url(file_url, file_name)
        print("222222222222222222222222222222")
        free_group_id = await get_qpan_group_with_enough_space(bot, file_size) # type: ignore
        print("23333333333333333333333333")
        if free_group_id:
            #[CQ:file,file=stopRunDeathReboot.txt,url=,file_id=/ac730bb9-08a3-4e7b-b9f1-e9e23e450d60,path=,file_size=3]
            # await bot.upload_group_file(group_id=free_group_id, file=file_path, name=file_name) # type: ignore
            #file_path = file_path.replace("\\" , "/") # Windows路径转换为URL路径
            #await bot.send_group_msg(group_id=group_id, message=f"[CQ:file,file_id={file_id},file={file_name},path={file_path},file_size={file_size}]")
            await bot.send_group_msg(group_id=group_id, message=f"[CQ:file,file_id={file_id},file={file_path},file_size={file_size}]")
            await bot.send_group_msg(group_id=group_id, message=f"文件 {file_name} 已成功转移到群 {free_group_id}！") # type: ignore
            # if message_id :
            #     # 记录转移后的消息ID和时间戳，后续用于自动刷新
            #     file_messages[file_id] = {
            #         "message_id": message_id,
            #         "timestamp": time.time(),
            #         "group_id": free_group_id,
            #         "file_name": file_name,
            #     }


            #     _save_file_messages()
        else:
            await bot.send_group_msg(group_id=group_id, message=f"警告：未找到剩余空间足够的群盘来存储文件 {file_name}，请管理员尽快清理空间！") # type: ignore
        # 清理临时文件
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"文件转移失败：{e}")
        try:
            await bot.send_group_msg(group_id=group_id, message=f"文件 {file_name} From 路径 {file_path} 转移失败：{e}") # type: ignore
        except Exception:
            pass


file_upload = on_notice()

@file_upload.handle()
async def handle_group_upload(bot: Bot, event: Event ):  # noqa: C901
    if event.get_user_id() == str(bot.self_id):
        return  # 忽略自己上传的文件事件，避免死循环

    event_type = event.notice_type # type: ignore
    print(f"收到事件：{event_type}") # 打印事件类型以调试
    if event_type == "group_upload": # 监听群文件上传事件
        group_id = event.group_id # type: ignore
        user_id = event.user_id # type: ignore
        file_name = event.file.name # type: ignore
        file_size = event.file.size # type: ignore

        current_qpan_info = await get_qpan_file_info(bot, group_id) # type: ignore # 获取当前群盘信息以计算剩余空间
        await file_upload.send(f"检测到群 {group_id} 中用户 {user_id} 上传了文件 {file_name}，大小为 {file_size} 字节，当前群盘使用率：{int(current_qpan_info.used_space/current_qpan_info.total_space * 100)}% ，是否足够？ {current_qpan_info.total_space - current_qpan_info.used_space >= file_size}") # type: ignore # 发送通知消息

        if file_id := event.file.id: # type: ignore # 获取上传文件的 file_id
            file_msg = _find_file_message(file_id)
            if file_msg is None:
                await file_upload.send("该文件的 uid 记录尚未更新到 file_messages 中，可能尚未捕获到消息事件，稍后将自动刷新")
            else:
                await file_upload.send(f"该文件已生成 uid={file_msg.get('uid')}，message_id={file_msg.get('message_id')}") # type: ignore

        files = await get_qpan_files(bot) # type: ignore # 刷新文件列表，确保 file_messages 中有最新的记录
        for file in files:
            if file["file_name"] == file_name and file["file_size"] == file_size: # type: ignore
                await file_upload.finish(f"文件 {file_name} 已存在于群盘中") # type: ignore
                return  # 如果文件已存在于群盘中，直接返回，不进行后续处理

        # 等待 handle_message 捕获用户发送的原始文件消息（notice 与 message 事件几乎同时到达，稍等即可）
        await asyncio.sleep(1)
        current_qpan_info = await get_qpan_file_info(bot, group_id) # type: ignore #刷新群盘信息，获取最新的剩余空间情况

        if current_qpan_info.total_space - current_qpan_info.used_space < file_size or file_name == "test.txt": # 如果剩余空间不足以存储新文件
            if file_name == "test.txt":
                file_size = 1024 * 1024 * 1024 * 5 # 模拟一个5GB的文件大小用于测试转移功能
                await file_upload.send(f"检测到测试文件 {file_name}，模拟文件大小为 {file_size} 字节，用于测试转移功能！") # type: ignore 发送测试文件消息

            await file_upload.send(f"警告：群 {group_id} 中用户 {user_id} 上传的文件 {file_name} 大小为 {file_size} 字节，超过了当前群盘剩余空间！正在查找空闲群盘...") # type: ignore 发送警告消息
            free_group_id = await get_qpan_group_with_enough_space(bot, file_size) # type: ignore # 查找一个剩余空间足够的群盘
            if free_group_id:
                await file_upload.send(f"找到空闲群盘 {free_group_id}，正在转移文件 {file_name}...") # type: ignore 发送找到空闲群盘的消息
                if await send_file_to_group(bot, free_group_id, event.file.id): # type: ignore
                    await file_upload.send(f"已转发 {file_name} 至 {free_group_id}，正在转为永久文件") # type: ignore
                else:
                    await file_upload.send(f"转发失败：未找到 {file_name} 的原始消息（仅聊天框拖入的文件支持转发，文件面板上传不支持）") # type: ignore
                    return

                if await set_qpan_file_forever(bot, file_size=file_size, file_name=file_name, group_id=free_group_id) :# type: ignore # 尝试设置新上传的文件为永久保存
                    await file_upload.send(f"已自动设置文件 {file_name} 为永久保存！") # type: ignore # 发送成功消息
                else:
                    await file_upload.send(f"自动设置文件 {file_name} 为永久保存失败，可能是因为未找到对应文件信息！") # type: ignore # 发送失败消息




        else:
            if await set_qpan_file_forever(bot, file_size=file_size, file_name=file_name, group_id=group_id) : # type: ignore # 尝试设置新上传的文件为永久保存
                await file_upload.send(f"已自动设置文件 {file_name} 为永久保存！") # type: ignore # 发送成功消息
            else:
                await file_upload.send(f"自动设置文件 {file_name} 为永久保存失败，可能是因为未找到对应文件信息！") # type: ignore # 发送失败消息


        # 在这里处理文件上传事件，例如记录日志或发送通知
        print(f"群 {group_id} 中用户 {user_id} 上传了文件 {file_name}，大小为 {file_size} 字节 ,file_id: {event.file.id}") # type: ignore # 打印文件信息以调试



qpan = on_command("qpan", aliases={"群盘"} , priority=5) # 定义一个命令处理器，监听 "qpan" 和 "群盘" 命令，优先级为 5

async def cmd_help(bot, event, sub_args):
    await qpan.finish(
        "可用子命令：\n"
        "  help/帮助          - 显示本帮助\n"
        "  list/列表 [页码] [0/1] - 分页列表（0=非永久,1=永久）\n"
        "  search/搜索 <关键词> - 按文件名搜索\n"
        "  info/总盘          - 查看空间统计\n"
        "  get/获取 <uid|/file_id> - 转发文件到当前群\n"
        "  remove/删除 <uid|/file_id|all> - 删除文件\n"
        "  refresh/刷新       - 手动刷新过期记录\n"
        "  resend             - 补充未记录的群盘文件（后台执行）\n\n"
        "示例：\n"
        "  qpan list\n"
        "  qpan search 报告\n"
        "  qpan get abc123xyz （通过uid）\n"
        "  qpan get /ac730bb9... （通过file_id，以/开头）\n"
        "  qpan remove abc123xyz （删除uid）\n"
        "  qpan remove /ac730bb9... （删除file_id）\n"
        "  qpan remove all nonpermanent （删除所有非永久文件）\n"
        "  qpan remove all repeated （删除所有重复文件）\n"
        "  qpan resend （扫描并补充未被记录的文件）"
    )


def _uid_by_file(file_id: str, group_id: int, file_name: str, file_size: int) -> str:
    record = _find_file_message(file_id)
    if record is None:
        record = _find_file_message_by_signature(group_id, file_name, file_size)
    return str(record.get("uid")) if record is not None else "-"

async def cmd_list(bot, event, sub_args):
    # 解析参数：sub_args[0] = 页码, sub_args[1] = 筛选条件(0=非永久, 1=永久)
    page_arg = sub_args[0] if len(sub_args) > 0 else ""
    filter_arg = sub_args[1] if len(sub_args) > 1 else None  # None表示不筛选

    page = int(page_arg) if page_arg.isdigit() else 1 # 默认显示第一页
    # 解析筛选条件：0=只显示非永久文件, 1=只显示永久文件, None=全部显示
    filter_permanent = None
    if filter_arg in ("0", "1"):
        filter_permanent = filter_arg == "1"

    max_files_per_page = 10

    file_list = await get_qpan_files(bot) # type: ignore

    # 按永久/非永久筛选
    if filter_permanent is not None:
        file_list = [f for f in file_list if (f["dead_time"] == 0) == filter_permanent]

    # 分页处理
    all_page = len(file_list) // max_files_per_page + (1 if len(file_list) % max_files_per_page > 0 else 0)
    page = max(1, min(page, all_page)) # 确保页码在有效范围内
    start_index = (page - 1) * max_files_per_page
    end_index = start_index + max_files_per_page
    paginated_files = file_list[start_index:end_index]

    filter_desc = "全部" if filter_permanent is None else ("永久" if filter_permanent else "非永久")
    file_info_list = "\n".join(
        f"{file['file_name']} \n(大小: {file['file_size']/1024/1024:.2f} MB ，属于群 {file['group_name']} , 是否永久 {file['dead_time'] == 0} , file_id: {file['file_id']} , uid: {_uid_by_file(file['file_id'], file['group_id'], file['file_name'], file['file_size'])})"
        for file in paginated_files
    )

    await qpan.finish(f"文件列表（{filter_desc}）：\n{file_info_list}\n共 {len(file_list)} 个文件 \n 第 {page} / {all_page} 页")

async def cmd_search(bot, event, sub_args):
    keyword = sub_args[0] if sub_args else ""
    file_list = await get_qpan_files(bot) # type: ignore

    matching_files = [f for f in file_list if keyword in f["file_name"]]

    await qpan.finish(
        f"搜索：{keyword}，找到 {len(matching_files)} 个文件：\n"
        + "\n".join(
            f"{file['file_name']} (大小: {file['file_size']/1024/1024:.2f} MB，属于群 {file['group_name']} , 是否永久 {file['dead_time'] == 0} , uid: {_uid_by_file(file['file_id'], file['group_id'], file['file_name'], file['file_size'])})"
            for file in matching_files
        )
    )

async def cmd_info(bot, event, sub_args):
    # qpan_info = await get_qpan_file_info(bot) # type: ignore
    qpan_groups = await get_qpan_groups(bot) # type: ignore

    details = "\n"
    used_space = 0
    total_space = 0
    qpan_groups.sort(key=lambda group: group["group_name"])
    for group in qpan_groups:
        re = SimpleNamespace(**await bot.get_group_file_system_info(group_id=group["group_id"])) # type: ignore
        used_space += re.used_space
        total_space += re.total_space
        details += f"{group['group_name']} {group['group_id']}: {int(re.used_space/re.total_space * 100)}% ({re.used_space/1024/1024/1024:.2f} GB / {re.total_space/1024/1024/1024:.2f} GB)\n"
    class QPanInfo:
        def __init__(self, used_space, total_space, group_count):
            self.used_space = used_space
            self.total_space = total_space
            self.group_count = group_count
    qpan_info =QPanInfo(used_space, total_space, len(qpan_groups))

    # print(re)
    await qpan.finish(
        f"网盘使用率：{int(qpan_info.used_space/qpan_info.total_space * 100)}% ({qpan_info.used_space/1024/1024/1024:.2f} GB / {qpan_info.total_space/1024/1024/1024:.2f} GB) " +
        details +
        f"\n共 {qpan_info.group_count} 个群盘，平均每个群盘使用空间：{(qpan_info.used_space/qpan_info.group_count)/1024/1024/1024:.2f} GB"
        )

async def cmd_remove_old(bot, event, sub_args):
    # 只提供 uid 参数，后续可以增加更多参数来提高准确性，例如文件名、大小、所属群等
    sub_args[0] if sub_args else ""
    await qpan.finish("删除功能尚未实现")

async def cmd_refresh(bot, event, sub_args):
    await qpan.send(f"开始刷新，共 {len(file_messages)} 条记录，超过 {REFRESH_AFTER_DAYS} 天的将被重新转发...")
    await _do_refresh_file_messages()
    await qpan.finish("刷新完成")

async def cmd_resend(bot, event, sub_args):
    """触发后台任务：扫描群盘文件并补充未被记录的文件"""
    await qpan.send("开始补充文件记录，将在后台执行...")
    asyncio.create_task(_resend_all_file_norecord(bot))
    await qpan.finish("后台任务已启动，请稍候")

async def cmd_get(bot, event, sub_args):
    identifier = sub_args[0] if sub_args else ""
    if not identifier:
        await qpan.finish("请提供 uid 或 file_id（file_id 以 / 开头），示例：qpan get <uid> 或 qpan get /<file_id>")
        return

    # 判断是 file_id 还是 uid（file_id 以 / 开头）
    if identifier.startswith("/"):
        # 用户提供的是 file_id
        file_id = identifier
        file_list = await get_qpan_files(bot) # type: ignore
        target_file = next((f for f in file_list if f["file_id"] == file_id), None) # type: ignore

        if target_file:
            await qpan.send(f"正在发送文件 {target_file['file_name']} 到当前群！(file_id: {file_id})") # type: ignore
            await send_file_to_group(bot, event.group_id, file_id) # type: ignore
        else:
            # 文件不在程序记录中，启用下载并重新上传的流程
            await qpan.send(f"文件 {file_id} 未在程序记录中，准备启用下载并重新上传流程...") # type: ignore
            asyncio.create_task(transfer_file_to_free_group(bot, file_id, event.group_id, file_id, 0)) # type: ignore
            await qpan.finish("已启动后台转移任务，请稍候...")
    else:
        # 用户提供的是 uid
        uid = identifier
        record = _find_file_message_by_uid(uid)
        if record is None:
            await qpan.finish("未找到指定 uid 的文件记录")
            return

        file_id = str(record.get("file_id", ""))
        file_list = await get_qpan_files(bot) # type: ignore
        target_file = next((f for f in file_list if f["file_id"] == file_id), None) # type: ignore # next函数会返回第一个满足条件的文件对象，如果没有找到则返回None

        # file_id 可能变化，按历史特征回查并更新到最新 file_id
        if target_file is None:
            target_file = next(
                (
                    f for f in file_list
                    if f["group_id"] == _as_int(record.get("group_id", 0))
                    and f["file_name"] == record.get("file_name")
                    and f["file_size"] == _as_int(record.get("file_size", 0))
                ),
                None,
            )
            if target_file is not None:
                record["file_id"] = target_file["file_id"]
                record["timestamp"] = time.time()
                _save_file_messages()

        if target_file:
            # 检查是否缺少 message_id，如果缺失则需要重新上传
            message_id = _as_int(record.get("message_id", 0))
            if message_id == 0:
                # message_id 缺失，启动后台重新上传任务
                await qpan.send(f"文件 {target_file['file_name']} 的消息记录缺失，正在重新上传以获取消息 ID...") # type: ignore
                asyncio.create_task(
                    transfer_file_to_free_group(
                        bot,
                        target_file["file_id"],
                        _as_int(record.get("group_id", 0)),
                        target_file["file_name"],
                        _as_int(target_file.get("file_size", 0))
                    )
                )
                await qpan.finish("已启动后台重新上传任务，请稍候...")
            else:
                # message_id 存在，直接转发
                await qpan.send(f"正在发送文件 {target_file['file_name']} 到当前群！(uid: {uid})") # type: ignore
                await send_file_to_group(bot, event.group_id, target_file["file_id"]) # type: ignore
        else:
            await qpan.finish("未找到指定文件，可能已被删除或 file_id 尚未同步")


async def cmd_remove(bot, event, sub_args):
    """删除文件，支持按uid、按file_id或删除所有特定类型文件"""
    if not sub_args:
        await qpan.finish("请提供删除参数，例如：qpan remove <uid|/file_id> 或 qpan remove all nonpermanent/repeated")
        return

    # 模式1：按 file_id 删除（以 "/" 开头）
    if sub_args[0].startswith("/"):
        file_id = sub_args[0]
        record = _find_file_message(file_id)
        
        # 当记录中找不到时，直接从群文件列表搜索
        if record is None:
            file_list = await get_qpan_files(bot)  # type: ignore
            target_file = next((f for f in file_list if f["file_id"] == file_id), None)  # type: ignore
            
            if target_file is None:
                await qpan.finish(f"未找到 file_id={file_id} 的文件")
                return
            
            # 文件存在于群盘中但无记录，直接删除
            try:
                await bot.delete_group_file(group_id=target_file["group_id"], file_id=file_id)  # type: ignore
                await qpan.finish(f"已删除文件 {target_file['file_name']}（file_id: {file_id}）")  # type: ignore
                return
            except FinishedException:
                raise
            except Exception as e:
                await qpan.finish(f"删除文件失败：{e}\n文件：{target_file['file_name']}")  # type: ignore
            return
        
        # 如果记录存在，从记录和群文件中都删除
        file_messages.remove(record)
        _save_file_messages()

        group_id = _as_int(record.get("group_id"))
        file_name = str(record.get("file_name", "未知文件"))
        try:
            await bot.delete_group_file(group_id=group_id, file_id=file_id)  # type: ignore
            await qpan.finish(f"已删除文件 {file_name}（file_id: {file_id}）")
        except FinishedException:
            raise
        except Exception as e:
            await qpan.finish(f"已从记录中删除，但群文件删除失败：{e}\n文件：{file_name}")

    # 模式2：按 uid 删除
    elif sub_args[0] != "all":
        uid = sub_args[0]
        record = _find_file_message_by_uid(uid)
        if record is None:
            await qpan.finish(f"未找到 uid={uid} 的文件记录")
            return

        file_id = str(record.get("file_id", ""))
        file_name = str(record.get("file_name", "未知文件"))
        group_id = _as_int(record.get("group_id"))

        # 从记录中删除
        file_messages.remove(record)
        _save_file_messages()

        # 尝试从群文件中删除
        try:
            await bot.delete_group_file(group_id=group_id, file_id=file_id)  # type: ignore
            await qpan.finish(f"已删除文件 {file_name}（uid: {uid}）")
        except FinishedException:
            raise
        except Exception as e:
            await qpan.finish(f"已从记录中删除，但群文件删除失败：{e}\n文件：{file_name}")

    # 模式3：删除所有特定类型文件
    elif sub_args[0] == "all":
        if len(sub_args) < 2:
            await qpan.finish("请指定删除类型：qpan remove all nonpermanent（非永久）或 qpan remove all repeated（重复）")
            return

        sub_cmd = sub_args[1]

        # 删除所有非永久文件
        if sub_cmd == "nonpermanent":
            file_list = await get_qpan_files(bot)  # type: ignore
            # 找出所有非永久文件（dead_time != 0）
            nonpermanent_files = [f for f in file_list if f.get("dead_time", 0) != 0]  # type: ignore

            if not nonpermanent_files:
                await qpan.finish("没有找到非永久文件")
                return

            deleted_count = 0
            failed_count = 0
            for file in nonpermanent_files:
                try:
                    await bot.delete_group_file(group_id=file["group_id"], file_id=file["file_id"])  # type: ignore
                    # 从记录中删除
                    record = _find_file_message(file["file_id"])  # type: ignore
                    if record:
                        file_messages.remove(record)
                    deleted_count += 1
                    await asyncio.sleep(0.3)  # 避免频率限制
                except FinishedException:
                    raise
                except Exception as e:  # noqa: PERF203
                    print(f"删除文件 {file['file_name']} 失败：{e}")  # type: ignore
                    failed_count += 1

            _save_file_messages()
            await qpan.finish(f"已删除 {deleted_count} 个非永久文件，失败 {failed_count} 个")

        # 删除所有重复文件
        elif sub_cmd == "repeated":
            file_list = await get_qpan_files(bot)  # type: ignore
            # 按文件名和大小分组，找出重复的
            seen = {}  # (file_name, file_size) -> 第一个文件对象
            duplicates = []

            for file in file_list:
                key = (file["file_name"], file["file_size"])  # type: ignore
                if key in seen:
                    duplicates.append(file)
                else:
                    seen[key] = file

            if not duplicates:
                await qpan.finish("没有找到重复文件")
                return

            deleted_count = 0
            failed_count = 0
            for file in duplicates:
                try:
                    await bot.delete_group_file(group_id=file["group_id"], file_id=file["file_id"])  # type: ignore
                    # 从记录中删除
                    record = _find_file_message(file["file_id"])  # type: ignore
                    if record:
                        file_messages.remove(record)
                    deleted_count += 1
                    await asyncio.sleep(0.3)  # 避免频率限制
                except FinishedException:
                    raise
                except Exception as e:  # noqa: PERF203
                    print(f"删除文件 {file['file_name']} 失败：{e}")  # type: ignore
                    failed_count += 1

            _save_file_messages()
            await qpan.finish(f"已删除 {deleted_count} 个重复文件，失败 {failed_count} 个")
        else:
            await qpan.finish(f"未知的删除类型：{sub_cmd}，请使用 nonpermanent 或 repeated")



SUB_COMMANDS = {
    "help": cmd_help, "帮助": cmd_help,
    "list": cmd_list, "列表": cmd_list,
    "search": cmd_search, "搜索": cmd_search,
    "info" : cmd_info, "总盘" : cmd_info ,
    "set" : None, "设置" : None, # 预留设置命令
    "remove" : cmd_remove, "删除" : cmd_remove, # 预留删除命令
    "get" : cmd_get , "获取" : cmd_get , # 预留获取文件命令
    "refresh" : cmd_refresh , "刷新" : cmd_refresh , # 手动触发消息刷新
    "resend" : cmd_resend , # 后台补充未记录的文件
}

@qpan.handle()
async def handle_qpan(bot: Bot, event: Event, state: T_State, args: Message = CommandArg()):
    print(event.get_message()) # 打印原始参数以调试
    cmd = args.extract_plain_text().strip().split()
    sub = cmd[0] if cmd else ""
    sub_args = cmd[1:] if len(cmd) > 1 else []

    handler = SUB_COMMANDS.get(sub)
    if handler:
        await handler(bot, event, sub_args)
    elif sub == "":
        await qpan.finish("请输入子命令，发送 qpan help 查看帮助")
    else:
        await qpan.finish(f"未知子命令：{sub}")


msg = on_message(priority=10)
self_msg = on()

FILE_MESSAGES_PATH = os.path.join(os.path.dirname(__file__), "file_messages.json")
FILE_MESSAGES_MAX = 100
REFRESH_INTERVAL_HOURS = 1 # 每隔多少小时检查一次
REFRESH_AFTER_DAYS = 0.5    # 消息超过几天则重新转发刷新

# REFRESH_INTERVAL_HOURS = 0.0038 # 每隔多少小时检查一次
# REFRESH_AFTER_DAYS = 0    # test 设置为0表示每条消息都刷新，实际使用时建议设置为3天以上，避免频繁刷新导致的性能问题和可能的频率限制



def _load_file_messages() -> list[dict[str, object]]:
    try:
        with open(FILE_MESSAGES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # 兼容旧格式：
        # 1) {file_id: {...}} 的字典映射
        # 2) {file_id: message_id} 的简化映射
        # 3) [{file_id: ..., ...}] 的新格式列表
        if isinstance(data, dict):
            records: list[dict[str, object]] = []
            for fid, info in data.items():
                if isinstance(info, dict):
                    record = dict(info)
                    record["file_id"] = str(record.get("file_id", fid))
                else:
                    record = {
                        "file_id": str(fid),
                        "message_id": int(info),
                        "timestamp": 0.0,
                        "group_id": 0,
                        "uid": shortuuid.uuid(),
                        "file_size": 0,
                    }
                records.append(record)
            return records
        if isinstance(data, list):
            records = [r for r in data if isinstance(r, dict) and "file_id" in r]
            for record in records:
                record.setdefault("timestamp", 0.0)
                record.setdefault("group_id", 0)
                uid = str(record.get("uid", ""))
                record["uid"] = uid if uid and uid != "0" else shortuuid.uuid()
                record.setdefault("file_size", 0)
            return records
        return []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _find_file_message(file_id: str) -> dict[str, object] | None:
    return next((item for item in file_messages if item.get("file_id") == file_id), None)


def _find_file_message_by_uid(uid: str) -> dict[str, object] | None:
    return next((item for item in file_messages if item.get("uid") == uid), None)


def _find_file_message_by_signature(group_id: int, file_name: str, file_size: int) -> dict[str, object] | None:
    return next(
        (
            item for item in reversed(file_messages)
            if _as_int(item.get("group_id", 0)) == group_id
            and str(item.get("file_name", "")) == file_name
            and _as_int(item.get("file_size", 0)) == file_size
        ),
        None,
    )


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _upsert_file_message(file_id: str, message_id: int, group_id: int, file_name: str, file_size: int) -> None:
    existing = _find_file_message(file_id)
    if existing is None:
        # file_id 会变，按文件特征复用既有 uid
        existing = _find_file_message_by_signature(group_id, file_name, file_size)

    now = time.time()
    payload = {
        "file_id": file_id,
        "message_id": message_id,
        "timestamp": now,
        "group_id": group_id,
        "uid": str(existing.get("uid")) if existing is not None else shortuuid.uuid(),
        "file_name": file_name,
        "file_size": file_size,
    }
    if existing is not None:
        existing.update(payload)
    else:
        file_messages.append(payload)

    # 超出上限时删除最旧记录
    if len(file_messages) > FILE_MESSAGES_MAX:
        file_messages.sort(key=lambda x: _as_float(x.get("timestamp", 0.0)))
        del file_messages[: len(file_messages) - FILE_MESSAGES_MAX]

def _save_file_messages() -> None:
    with open(FILE_MESSAGES_PATH, "w", encoding="utf-8") as f:
        json.dump(file_messages, f, ensure_ascii=False, indent=2)

async def _do_refresh_file_messages() -> None:
    """将超过 REFRESH_AFTER_DAYS 天的记录重新转发到原群，handle_message 会自动更新 timestamp"""
    try:
        from nonebot import get_bot
        bot = get_bot()
    except Exception:
        print("刷新文件消息：未找到可用的 bot 实例")
        return
    now = time.time()
    expired = [
        info for info in file_messages
        if now - _as_float(info.get("timestamp", 0)) > REFRESH_AFTER_DAYS * 86400
    ]
    if not expired:
        return
    print(f"开始刷新 {len(expired)} 条过期文件消息...")
    for info in expired:
        file_id = str(info.get("file_id", ""))
        if not info.get("group_id"):
            print(f"跳过 file_id={file_id}：无有效 group_id")
            continue
        try:
            message_id = (await bot.forward_group_single_msg(group_id=info["group_id"], message_id=info["message_id"]))["message_id"]  # type: ignore

            info["message_id"] = message_id
            info["timestamp"] = time.time()
            _save_file_messages()
            print(f"已转发刷新 file_id={file_id}")
        except Exception as e:
            print(f"刷新 file_id={file_id} 失败：{e}")
        await asyncio.sleep(1)  # 避免频率限制

async def _refresh_loop() -> None:
    last_refresh = time.time()
    while True:
        await asyncio.sleep(5)  # 每分钟检查一次
        if time.time() - last_refresh >= REFRESH_INTERVAL_HOURS * 3600:
            await _do_refresh_file_messages()
            last_refresh = time.time()
        # else:
        #     print(f"距离下次刷新还有 {(REFRESH_INTERVAL_HOURS * 3600 - (time.time() - last_refresh)) / 60:.2f} 分钟")

def _cleanup_download_dir() -> None:
    """启动时清理下载目录中的残余文件"""
    try:
        if not os.path.exists(DOWNLOAD_DIR):
            print(f"下载目录不存在：{DOWNLOAD_DIR}")
            return

        files = os.listdir(DOWNLOAD_DIR)
        if not files:
            print("下载目录已清空")
            return

        deleted_count = 0
        for file_name in files:
            file_path = os.path.join(DOWNLOAD_DIR, file_name)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    deleted_count += 1
                    print(f"删除残余文件：{file_name}")
                elif os.path.isdir(file_path):
                    import shutil
                    shutil.rmtree(file_path)
                    deleted_count += 1
                    print(f"删除残余目录：{file_name}")
            except Exception as e:
                print(f"删除 {file_name} 失败：{e}")

        if deleted_count > 0:
            print(f"下载目录自检完成，删除了 {deleted_count} 个残余文件/目录")
    except Exception as e:
        print(f"下载目录自检失败：{e}")

# 遍历群盘文件，为缺失 uid 的文件补充 uid，缺失 message_id 的文件将由消息捕获自动更新
async def _resend_all_file_norecord(bot : Bot) -> None:
    """遍历群盘文件，为缺失 uid 的文件补充 uid
    
    说明：
    - 只负责补充 uid，使用文件特征（group_id, file_name, file_size）匹配复用现有 uid
    - 缺失 message_id 的文件需要通过重新下载上传，由 msg 事件自动捕获并更新
    """
    try:
        files = await get_qpan_files(bot)  # type: ignore
        if not files:
            print("群盘中没有文件")
            return

        updated_count = 0
        needs_reupload = []  # 记录需要重新上传的文件（缺少 message_id）
        
        for file in files:
            file_id = file.get("file_id", "")
            if not file_id:
                continue

            # 查找是否已有记录
            record = _find_file_message(file_id)

            # 如果没有记录，或者 uid 丢失，则需补充 uid
            if record is None or not str(record.get("uid", "")).strip():
                # 按文件特征匹配现有 uid（文件可能已移动但同名同大小）
                existing_by_sig = _find_file_message_by_signature(
                    _as_int(file.get("group_id", 0)),
                    file.get("file_name", ""),
                    _as_int(file.get("file_size", 0))
                )

                # 复用旧 uid 或生成新 uid
                uid = str(existing_by_sig.get("uid")) if existing_by_sig is not None else shortuuid.uuid()

                # 构建新记录（message_id 可为 0，后续由消息事件自动更新）
                payload = {
                    "file_id": file_id,
                    "message_id": _as_int(record.get("message_id", 0)) if record else 0,
                    "timestamp": time.time(),
                    "group_id": _as_int(file.get("group_id", 0)),
                    "uid": uid,
                    "file_name": file.get("file_name", ""),
                    "file_size": _as_int(file.get("file_size", 0)),
                }

                if record is not None:
                    # 更新现有记录
                    record.update(payload)
                else:
                    # 添加新记录
                    file_messages.append(payload)

                updated_count += 1

                # 如果缺少 message_id，标记为需要重新上传
                if payload["message_id"] == 0:
                    needs_reupload.append({
                        "file_id": file_id,
                        "group_id": payload["group_id"],
                        "file_name": payload["file_name"],
                        "file_size": payload["file_size"]
                    })

        if updated_count > 0:
            _save_file_messages()
            print(f"补充文件 uid 完成，更新了 {updated_count} 条记录，共 {len(file_messages)} 条")
        
        # 如果有文件需要重新上传以捕获 message_id，后台启动上传任务
        if needs_reupload:
            print(f"检测到 {len(needs_reupload)} 个文件缺少 message_id，需要重新下载上传")
            for file_info in needs_reupload:
                asyncio.create_task(
                    transfer_file_to_free_group(
                        bot,
                        file_info["file_id"],
                        file_info["group_id"],
                        file_info["file_name"],
                        file_info["file_size"]
                    )
                )
        
        if updated_count == 0 and not needs_reupload:
            print("所有群盘文件都已有有效记录")
    except Exception as e:
        print(f"补充文件记录失败：{e}")

driver = get_driver()

@driver.on_startup
async def _start_refresh_task() -> None:
    """机器人启动时执行初始化任务"""
    # 清理下载目录残余文件
    _cleanup_download_dir()

    # 启动后台刷新循环
    # asyncio.create_task(_resend_all_file_norecord())
    asyncio.create_task(_refresh_loop())

file_messages: list[dict[str, object]] = _load_file_messages()  # uid -> file metadata


def _record_file_message(raw_message: str , message_id: int , group_id: int) -> None:
    """从消息事件中提取文件 CQ 码并记录映射关系。"""
    # print(f"收到消息：{raw_message}") # 打印收到的消息内容以调试

    #sample [CQ:file,file=vfcompat.dll,url=,file_id=/c56bcc83-678b-4454-8bab-c6eb99b0dc6d,path=,file_size=68104]
    if "[CQ:file," in raw_message:
        match = re.search(r"file_id=([^,\]]+)", raw_message)
        if match:
            file_id = match.group(1)
            print(f"提取到 file_id：{file_id}")
            file_name_match = re.search(r"(?<!\w)file=([^,\]]+)", raw_message)
            file_name = file_name_match.group(1) if file_name_match else ""
            file_size_match = re.search(r"file_size=(\d+)", raw_message)
            file_size = int(file_size_match.group(1)) if file_size_match else 0
            _upsert_file_message(file_id, message_id, group_id, file_name, file_size)
            _save_file_messages()
            # await msg.send(f"已记录文件消息，file_id: {file_id}，message_id: {event.message_id}") # type: ignore
        # await bot.forward_group_single_msg(group_id=event.group_id, message_id=event.message_id) # type: ignore # 尝试将消息转发到另一个群，替换为实际的目标群ID


@msg.handle()
async def handle_message(bot: Bot, event: Event):
    # user_id = getattr(event, "user_id", None)
    # is_self_message = user_id is not None and str(user_id) == str(bot.self_id)
    # print(f"message 事件触发 (self={is_self_message})")
    _record_file_message(event.raw_message, event.message_id, event.group_id) # type: ignore


@self_msg.handle()
async def handle_self_message(bot: Bot, event: Event):
    if event.post_type != "message_sent":
        return
    # user_id = getattr(event, "user_id", None)
    # is_self_message = user_id is not None and str(user_id) == str(bot.self_id)
    # print(f"message_sent 事件触发 (self={is_self_message})")
    _record_file_message(event.raw_message, event.message_id, event.group_id) # type: ignore

