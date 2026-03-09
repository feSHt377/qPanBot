#全自动q群文件网盘管理
import asyncio
import os
from types import SimpleNamespace

import httpx
from nonebot import on_command, on_message, on_notice
from nonebot.adapters.onebot.v11 import Bot, Event, Message
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

async def set_qpan_file_forever(bot: Bot, file_id: str, file_name: str, group_id: int, max_retries: int = 3):
    # 设置文件永久保存，带重试机制
    for attempt in range(max_retries):
        try:
            await asyncio.sleep(2 * (attempt + 1))  # 延迟 2/4/6 秒后再调用
            await bot.set_group_file_forever(file_id=file_id, group_id=group_id) # type: ignore
            break  # 成功则跳出重试循环
        except Exception as e:
            print(f"设置永久保存失败（第{attempt + 1}次）：{e}")
            if attempt == max_retries - 1:
                break #不退出函数，只记录错误日志，继续后续操作
    await asyncio.sleep(2)  # 等待一段时间让设置生效

    qpan_files = await get_qpan_files(bot) # type: ignore
    for file in qpan_files:
        if file["file_name"] == file_name : # type: ignore # 找到对应的文件信息
            file["dead_time"] = 0 # type: ignore # 更新文件的过期时间为0，表示永久保存
            return True

    return False # 如果没有找到对应的文件，返回False表示设置失败



DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


async def download_file_by_url(url: str, file_name: str) -> str:
    """通过 HTTP 直接下载文件到本地 downloads 目录"""
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
    return file_path


#弃用
async def transfer_file_to_free_group(bot: Bot, event: Event, group_id: int, file_name: str, file_size: int):
    """后台执行文件转移：直接 HTTP 下载 -> 上传到有空间的群盘"""
    try:
        file_url = (await bot.get_group_file_url(file_id=event.file.id, group_id=group_id))["url"] # type: ignore
        file_path = await download_file_by_url(file_url, file_name)

        free_group_id = await get_qpan_group_with_enough_space(bot, file_size) # type: ignore
        if free_group_id:
            await bot.upload_group_file(group_id=free_group_id, file=file_path, name=file_name) # type: ignore
            await bot.send_group_msg(group_id=group_id, message=f"文件 {file_name} 已成功转移到群 {free_group_id}！") # type: ignore
        else:
            await bot.send_group_msg(group_id=group_id, message=f"警告：未找到剩余空间足够的群盘来存储文件 {file_name}，请管理员尽快清理空间！") # type: ignore
        # 清理临时文件
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"文件转移失败：{e}")
        try:
            await bot.send_group_msg(group_id=group_id, message=f"文件 {file_name} 转移失败：{e}") # type: ignore
        except Exception:
            pass


file_upload = on_notice()

@file_upload.handle()
async def handle_group_upload(bot: Bot, event: Event):
    event_type = event.notice_type # type: ignore
    print(f"收到事件：{event_type}") # 打印事件类型以调试
    if event_type == "group_upload": # 监听群文件上传事件
        group_id = event.group_id # type: ignore
        user_id = event.user_id # type: ignore
        file_name = event.file.name # type: ignore
        file_size = event.file.size # type: ignore
        # 将中文文件名转换为拼音
        pinyin_filename = convert_chinese_to_pinyin(file_name)
        if pinyin_filename != file_name:
            await file_upload.finish("不支持中文文件名，请将文件名转换为英文或拼音后重新上传！") # type: ignore # 发送错误消息并结束处理

        # await file_upload.send(f"[CQ:file,file={file_name},url=,file_id={event.file.id},path=,file_size={file_size}]") # type: ignore # 发送初始通知消息
        await bot.send_group_msg(group_id=group_id, message=f"[CQ:file,file={file_name},url=,file_id={event.file.id},path=,file_size={file_size}]") # type: ignore # 发送初始通知消息

        current_qpan_info = await get_qpan_file_info(bot, group_id) # type: ignore # 获取当前群盘信息以计算剩余空间
        await file_upload.send(f"检测到群 {group_id} 中用户 {user_id} 上传了文件 {file_name}，大小为 {file_size} 字节，file_id: {event.file.id}，当前群盘使用率：{int(current_qpan_info.used_space/current_qpan_info.total_space * 100)}% ，是否足够？ {current_qpan_info.total_space - current_qpan_info.used_space >= file_size}") # type: ignore # 发送通知消息


        if current_qpan_info.total_space - current_qpan_info.used_space < file_size or file_name == "test.txt": # 如果剩余空间不足以存储新文件
            if file_name == "test.txt":
                file_size = 1024 * 1024 * 1024 * 5 # 模拟一个5GB的文件大小用于测试转移功能
                await file_upload.send(f"检测到测试文件 {file_name}，模拟文件大小为 {file_size} 字节，用于测试转移功能！") # type: ignore 发送测试文件消息

            await file_upload.send(f"警告：群 {group_id} 中用户 {user_id} 上传的文件 {file_name} 大小为 {file_size} 字节，超过了当前群盘剩余空间！正在查找空闲群盘...") # type: ignore 发送警告消息
            free_group_id = await get_qpan_group_with_enough_space(bot, file_size) # type: ignore # 查找一个剩余空间足够的群盘
            if free_group_id:
                await file_upload.send(f"找到空闲群盘 {free_group_id}，正在转移文件 {file_name}...") # type: ignore 发送找到空闲群盘的消息
                await bot.send_group_msg(group_id=free_group_id, message=f"[CQ:file,file={file_name},url=,file_id={event.file.id},path=,file_size={file_size}]") # type: ignore # 发送初始通知消息
                await file_upload.send(f"已上传{file_name}至{free_group_id},正在转为永久文件") # type: ignore 发送转移中的消息

                if await set_qpan_file_forever(bot, event.file.id , file_name, free_group_id) :# type: ignore # 尝试设置新上传的文件为永久保存
                    await file_upload.send(f"已自动设置文件 {file_name} 为永久保存！") # type: ignore # 发送成功消息
                else:
                    await file_upload.send(f"自动设置文件 {file_name} 为永久保存失败，可能是因为未找到对应文件信息！") # type: ignore # 发送失败消息




        else:
            if await set_qpan_file_forever(bot, event.file.id , file_name, group_id) : # type: ignore # 尝试设置新上传的文件为永久保存
                await file_upload.send(f"已自动设置文件 {file_name} 为永久保存！") # type: ignore # 发送成功消息
            else:
                await file_upload.send(f"自动设置文件 {file_name} 为永久保存失败，可能是因为未找到对应文件信息！") # type: ignore # 发送失败消息


        # 在这里处理文件上传事件，例如记录日志或发送通知
        print(f"群 {group_id} 中用户 {user_id} 上传了文件 {file_name}，大小为 {file_size} 字节 ,file_id: {event.file.id}") # type: ignore # 打印文件信息以调试



qpan = on_command("qpan", aliases={"群盘"} , priority=5) # 定义一个命令处理器，监听 "qpan" 和 "群盘" 命令，优先级为 5

async def cmd_help(bot, event, sub_args):
    await qpan.finish("可用子命令：help, list, search ...")

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
    file_info_list = "\n".join(f"{file['file_name']} \n(大小: {file['file_size']/1024/1024:.2f} MB ，属于群 {file['group_name']} , 是否永久 {file['dead_time'] == 0} , file_id: {file['file_id']})" for file in paginated_files)

    await qpan.finish(f"文件列表（{filter_desc}）：\n{file_info_list}\n共 {len(file_list)} 个文件 \n 第 {page} / {all_page} 页")

async def cmd_search(bot, event, sub_args):
    keyword = sub_args[0] if sub_args else ""
    file_list = await get_qpan_files(bot) # type: ignore

    matching_files = [f for f in file_list if keyword in f["file_name"]]

    await qpan.finish(f"搜索：{keyword}，找到 {len(matching_files)} 个文件：\n" + "\n".join(f"{file['file_name']} (大小: {file['file_size']/1024/1024:.2f} MB，属于群 {file['group_name']} , 是否永久 {file['dead_time'] == 0} , file_id: {file['file_id']})" for file in matching_files))

async def cmd_info(bot, event, sub_args):
    qpan_info = await get_qpan_file_info(bot) # type: ignore
    # print(re)
    await qpan.finish(
        f"网盘总空间：{int(qpan_info.used_space/qpan_info.total_space * 100)}% ({qpan_info.total_space/1024/1024/1024:.2f} GB，已用空间：{qpan_info.used_space/1024/1024/1024:.2f} GB) " +
        f"\n共 {qpan_info.group_count} 个群盘，平均每个群盘使用空间：{(qpan_info.used_space/qpan_info.group_count)/1024/1024/1024:.2f} GB"
        )


SUB_COMMANDS = {
    "help": cmd_help, "帮助": cmd_help,
    "list": cmd_list, "列表": cmd_list,
    "search": cmd_search, "搜索": cmd_search,
    "info" : cmd_info, "总盘" : cmd_info ,
    "set" : None, "设置" : None, # 预留设置命令
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

# file_messages = []

@msg.handle()
async def handle_message(bot: Bot, event: Event):
    # if event.get_message()
    print(f"收到消息：{event.get_message()}") # 打印收到的消息内容以调试

    # if "file" in event.raw_message: # type: ignore

    #     await bot.forward_group_single_msg(group_id=event.group_id, message_id=event.message_id) # type: ignore # 尝试将消息转发到另一个群，替换为实际的目标群ID

