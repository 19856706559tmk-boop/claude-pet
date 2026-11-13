# -*- coding: utf-8 -*-
"""
Claude 桌面宠物

- 平时在 Claude 桌面端窗口底部游荡，跟着窗口移动；窗口最小化时躲起来
- Claude 桌面端关闭后自己退出
- 左键拖动可以把它拖出 Claude 窗口（之后在屏幕底部游荡），拖回窗口里就回家
- 左键单击：看 5 小时 / 7 天额度；双击：摸摸头；右键：菜单
- 额度和 Claude 正在做什么由 desk-pet-bridge 插件写到 quota.json / activity.json

- 加 --watch 运行是监视模式：常驻后台，Claude 桌面端一启动就把宠物拉起来
  （--install-autostart / --uninstall-autostart 登记或取消"登录 Windows 时自动开监视模式"）

只用 Python 标准库（tkinter + ctypes），仅支持 Windows。
"""
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import random
import subprocess
import sys
import time
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
QUOTA_FILE = os.path.join(HERE, "quota.json")
ACTIVITY_FILE = os.path.join(HERE, "activity.json")
LOG_FILE = os.path.join(HERE, "pet.log")
MUTEX_NAME = "Local\\ClaudeDesktopPet_v1"
WATCH_MUTEX_NAME = "Local\\ClaudeDesktopPetWatcher_v1"
RUN_KEY = "Software\\Microsoft\\Windows\\CurrentVersion\\Run"
RUN_VALUE = "ClaudeDeskPetWatcher"

ARGS = set(sys.argv[1:])
DEMO = "--demo" in ARGS          # 依次演示所有动作
KEEP = "--keep" in ARGS or DEMO  # Claude 不在也不退出（调试用）


def log(msg):
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 256 * 1024:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


# ---------------------------------------------------------------- Win32 ----

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

HWND = wt.HWND
LONG_PTR = ctypes.c_ssize_t
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, HWND, wt.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wt.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260),
    ]


def _sig(fn, res, *args):
    fn.restype = res
    fn.argtypes = list(args)
    return fn


_sig(user32.EnumWindows, wt.BOOL, WNDENUMPROC, wt.LPARAM)
_sig(user32.GetWindowThreadProcessId, wt.DWORD, HWND, ctypes.POINTER(wt.DWORD))
_sig(user32.IsWindow, wt.BOOL, HWND)
_sig(user32.IsWindowVisible, wt.BOOL, HWND)
_sig(user32.IsIconic, wt.BOOL, HWND)
_sig(user32.GetWindowTextLengthW, ctypes.c_int, HWND)
_sig(user32.GetClassNameW, ctypes.c_int, HWND, wt.LPWSTR, ctypes.c_int)
_sig(user32.GetWindow, HWND, HWND, wt.UINT)
_sig(user32.GetWindowRect, wt.BOOL, HWND, ctypes.POINTER(RECT))
_sig(user32.SetWindowPos, wt.BOOL, HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT)
_sig(user32.GetWindowLongPtrW, LONG_PTR, HWND, ctypes.c_int)
_sig(user32.SetWindowLongPtrW, LONG_PTR, HWND, ctypes.c_int, LONG_PTR)
_sig(user32.GetParent, HWND, HWND)
_sig(user32.ShowWindow, wt.BOOL, HWND, ctypes.c_int)
_sig(user32.GetCursorPos, wt.BOOL, ctypes.POINTER(POINT))
_sig(user32.MonitorFromPoint, wt.HMONITOR, POINT, wt.DWORD)
_sig(user32.GetMonitorInfoW, wt.BOOL, wt.HMONITOR, ctypes.POINTER(MONITORINFO))
_sig(dwmapi.DwmGetWindowAttribute, ctypes.c_long, HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD)
_sig(kernel32.CreateMutexW, wt.HANDLE, ctypes.c_void_p, wt.BOOL, wt.LPCWSTR)
_sig(kernel32.OpenMutexW, wt.HANDLE, wt.DWORD, wt.BOOL, wt.LPCWSTR)
_sig(kernel32.CloseHandle, wt.BOOL, wt.HANDLE)
_sig(kernel32.CreateToolhelp32Snapshot, wt.HANDLE, wt.DWORD, wt.DWORD)
_sig(kernel32.Process32FirstW, wt.BOOL, wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
_sig(kernel32.Process32NextW, wt.BOOL, wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
_sig(kernel32.OpenProcess, wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
_sig(kernel32.QueryFullProcessImageNameW, wt.BOOL, wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD))

GW_OWNER, GW_HWNDPREV = 4, 3
GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x40000, 0x08000000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
HWND_TOP, HWND_TOPMOST, HWND_NOTOPMOST = 0, -1, -2
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
INVALID_HANDLE = ctypes.c_void_p(-1).value


def set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def system_dpi():
    try:
        return int(user32.GetDpiForSystem()) or 96
    except Exception:
        return 96


def is_desktop_claude_path(path):
    p = path.lower().replace("/", "\\")
    return p.endswith("\\claude.exe") and "\\claude-code\\" not in p and (
        "\\app\\claude.exe" in p or "anthropicclaude" in p or "\\windowsapps\\claude_" in p)


_path_cache = {}


def desktop_claude_pids():
    """Claude 桌面端（不是 Claude Code 命令行）的所有进程 id。"""
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == INVALID_HANDLE:
        return set()
    pids = set()
    seen = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == "claude.exe":
                pid = entry.th32ProcessID
                seen.add(pid)
                path = _path_cache.get(pid)
                if path is None:
                    path = ""
                    h = kernel32.OpenProcess(0x1000, False, pid)
                    if h:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wt.DWORD(1024)
                        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                            path = buf.value
                        kernel32.CloseHandle(h)
                    if path:  # 没查到就下次再查，不记住空结果
                        _path_cache[pid] = path
                if is_desktop_claude_path(path):
                    pids.add(pid)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    # 进程号会被系统重复使用：已经结束的进程不留在缓存里（监视模式会一直运行）
    for pid in [p for p in _path_cache if p not in seen]:
        del _path_cache[pid]
    return pids


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_bounds(hwnd):
    r = RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def is_cloaked(hwnd):
    v = wt.DWORD(0)
    if dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), ctypes.sizeof(v)) == 0:
        return v.value != 0
    return False


def find_claude_window(pids):
    found = []

    def cb(hwnd, _):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and not user32.GetWindow(hwnd, GW_OWNER) \
                and user32.GetWindowTextLengthW(hwnd) > 0 \
                and window_class(hwnd).startswith("Chrome_WidgetWin"):
            r = window_bounds(hwnd)
            area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
            found.append((bool(user32.IsWindowVisible(hwnd)), area, hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][2]


def work_area_at(x, y):
    mon = user32.MonitorFromPoint(POINT(int(x), int(y)), 2)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(mon, ctypes.byref(info))
    return info.rcWork


def cursor_pos():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def toplevel_hwnd(widget):
    return user32.GetParent(widget.winfo_id()) or widget.winfo_id()


def make_tool_window(hwnd):
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    ex = (ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)


def is_topmost(hwnd):
    return bool(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


# ------------------------------------------------------- single instance ----

def already_running():
    h = kernel32.OpenMutexW(0x00100000, False, MUTEX_NAME)
    if h:
        kernel32.CloseHandle(h)
        return True
    return False


def pythonw_exe():
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        alt = exe[:-10] + "pythonw.exe"
        if os.path.exists(alt):
            exe = alt
    return exe


def spawn_detached():
    """插件和监视模式调用：后台启动宠物后立刻返回。"""
    if already_running():
        return
    if not desktop_claude_pids():
        return
    base = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    errors = []
    for flags in (base | 0x01000000, base):  # 先尝试 CREATE_BREAKAWAY_FROM_JOB，不允许就退回普通方式
        try:
            subprocess.Popen([pythonw_exe(), os.path.abspath(__file__)], cwd=HERE, creationflags=flags,
                             close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError as e:
            errors.append(f"{flags:#x}: {e}")
    log("spawn failed: " + "; ".join(errors))


# ------------------------------------------------------------ watch mode ----
# 插件只有在打开对话时才运行，所以单靠它，宠物要等第一个对话才出现。
# 监视模式随 Windows 登录启动，常驻后台，发现 Claude 桌面端启动就把宠物拉起来。

def is_new_claude_run(prev_pids, cur_pids):
    """Claude 是不是刚启动：现在有进程，而且和上一次看到的没有任何重合。

    同一次运行里主进程一直都在，所以前后两次总有重合；退出再打开后进程全是新的。
    只在"刚启动"时拉起宠物，这样用右键"退出宠物"后，它不会马上又被拉回来。
    """
    return bool(cur_pids) and not (set(cur_pids) & set(prev_pids))


def claude_window_visible(pids):
    hwnd = find_claude_window(pids)
    return bool(hwnd) and bool(user32.IsWindowVisible(hwnd))


def watch(poll_secs=2.0, window_wait_secs=20.0):
    kernel32.CreateMutexW(None, False, WATCH_MUTEX_NAME)
    if ctypes.get_last_error() == 183:  # 已经有一个监视进程了
        return
    prev = set()
    while True:
        try:
            cur = desktop_claude_pids()
            if is_new_claude_run(prev, cur):
                # 等 Claude 的窗口出来再启动，宠物才有地方落脚；等不到（比如启动到托盘）也照常启动
                deadline = time.time() + window_wait_secs
                while time.time() < deadline and not claude_window_visible(cur):
                    time.sleep(0.5)
                    cur = desktop_claude_pids() or cur
                spawn_detached()
            prev = cur
        except Exception:
            log("watch error:\n" + traceback.format_exc())
        time.sleep(poll_secs)


def autostart_command():
    return f'"{pythonw_exe()}" "{os.path.abspath(__file__)}" --watch'


def install_autostart():
    """登记到"当前用户登录时启动"，以后每次登录 Windows 都会在后台开着监视模式。"""
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())


def uninstall_autostart():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE)
    except FileNotFoundError:
        pass


# ------------------------------------------------------------- palette ----

BODY = "#D97757"
SHADE = "#BE684D"  # 身体背光的一面、握笔的手
MOUTH = "#7A2E1D"
EYE = "#1F1E1D"
BLUSH = "#F4A7A0"
INK = "#3D3929"
PAPER = "#FAF9F5"
KEY = "#010203"   # 透明色
GREEN, AMBER, RED = "#22A06B", "#E2A03F", "#E5484D"

FRAME_MS = 33
GW, GH = 64, 38                 # 画布大小（像素格）
OX, OY = (GW - 14) // 2, GH - 9  # 宠物左上角在画布里的位置（格）

LEG_COLS = (3, 5, 8, 10)

KIND_LABEL = {"five_hour": "5 小时额度", "seven_day": "7 天额度（周）",
              "seven_day_opus": "7 天 Opus 额度", "spend_limit": "消费上限"}
KIND_SHORT = {"five_hour": "5小时", "seven_day": "周", "seven_day_opus": "周(Opus)", "spend_limit": "消费"}

CHEERS = ["搞定！", "完成啦~", "好耶！", "收工！", "交给我没问题"]
OOPS = ["诶？", "被打断了…", "呜…出错了"]


def tool_category(name):
    """Claude 正在用的工具 -> 宠物做哪个动作。"""
    n = name or ""
    low = n.lower()
    if n in ("Bash", "PowerShell", "BashOutput", "KillShell", "Monitor", "KillBash"):
        return "type"       # 跑命令：敲终端
    if n in ("AskUserQuestion", "ExitPlanMode"):
        return "ask"        # 在等你回答：举问号牌
    if n in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "code"       # 写代码：握笔写字
    if n in ("Agent", "Task", "Workflow", "SendMessage"):
        return "summon"     # 派子代理：召唤分身
    if n in ("TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "EnterPlanMode") \
            or low.endswith("update_plan"):
        return "plan"       # 列计划：写字板打勾
    if n == "Skill":
        return "magic"      # 用技能：巫师帽 + 魔杖
    if n in ("WebFetch", "WebSearch") or "browser" in low or "chrome" in low:
        return "surf"       # 上网：冲浪
    if n in ("Grep", "Glob", "LS", "ToolSearch") or low.endswith("__find") or "search" in low:
        return "search"     # 搜索：放大镜
    if n in ("Read", "NotebookRead") or "get_page_text" in low or "read_page" in low or low.endswith("__read"):
        return "read"       # 读文件：看书
    return "tinker"         # 其他工具：敲齿轮


# 宠物说的话、头顶的标签一律用中文 -----------------------------------------
TOOL_LABEL = {
    "Bash": "运行命令", "PowerShell": "运行命令", "BashOutput": "看命令输出", "KillShell": "停止命令",
    "KillBash": "停止命令", "Monitor": "盯着进度",
    "Read": "读文件", "NotebookRead": "读笔记本",
    "Edit": "改代码", "MultiEdit": "改代码", "Write": "写文件", "NotebookEdit": "改笔记本",
    "Grep": "搜内容", "Glob": "找文件", "LS": "看目录", "ToolSearch": "找工具",
    "WebSearch": "上网搜索", "WebFetch": "打开网页",
    "Agent": "派出分身", "Task": "派出分身", "Workflow": "编排分身", "SendMessage": "给分身传话",
    "Skill": "使用技能",
    "TodoWrite": "列计划", "TaskCreate": "列计划", "TaskUpdate": "更新计划", "TaskList": "看计划",
    "TaskGet": "看计划", "EnterPlanMode": "做计划",
    "AskUserQuestion": "等你回答", "ExitPlanMode": "等你确认计划",
}
CATEGORY_LABEL = {"type": "运行命令", "ask": "等你回答", "code": "写代码", "summon": "派出分身",
                  "plan": "列计划", "magic": "使用技能", "surf": "上网", "search": "搜索",
                  "read": "读取", "tinker": "使用工具"}
ACTION_LABEL = {
    "idle": "发呆", "walk": "散步", "sit": "坐下", "look": "东张西望", "wave": "挥手", "hop": "蹦一下",
    "dance": "跳舞", "stretch": "伸懒腰", "yawn": "打哈欠", "spin": "转圈", "juggle": "抛球",
    "butterfly": "追蝴蝶", "coffee": "喝咖啡", "cool": "墨镜太空步", "think": "思考", "type": "运行命令",
    "read": "读文件", "search": "搜索", "surf": "上网冲浪", "code": "写代码", "plan": "列计划",
    "magic": "使用技能", "ask": "等你回答", "summon": "派出分身", "tinker": "使用工具", "cheer": "完成",
    "oops": "出错", "eat": "吃额度", "refresh": "额度恢复", "alert": "额度提醒", "pat": "摸摸头",
    "sleep": "睡觉",
}


def tool_label(name):
    """工具名 -> 头顶标签上显示的中文。没单独起名的工具（比如各种 MCP 工具）按类别说。"""
    n = name or ""
    if n in TOOL_LABEL:
        return TOOL_LABEL[n]
    low = n.lower()
    if low.endswith("update_plan"):
        return "列计划"
    if "browser" in low or "chrome" in low:
        return "操作浏览器"
    if "computer" in low:
        return "操作电脑"
    return CATEGORY_LABEL.get(tool_category(n), "使用工具") if n else ""


def stamp(props, rows, c0, r0, colors):
    """把一小块点阵图贴到道具层。rows 是一行行字符，colors 是 字符 -> 颜色，没列出的字符留空。"""
    for dr, line in enumerate(rows):
        for dc, ch in enumerate(line):
            col = colors.get(ch)
            if col:
                props.append((c0 + dc, r0 + dr, col))


def greeting():
    h = datetime.now().hour
    if h < 5 or h >= 23:
        return "夜深啦，还在忙？"
    if h < 11:
        return "早上好！我来啦"
    if h < 14:
        return "中午好~我来啦"
    if h < 18:
        return "下午好！我来啦"
    return "晚上好~我来啦"


def is_night():
    h = datetime.now().hour
    return h >= 22 or h < 7


def parse_iso(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def fmt_duration(sec):
    sec = max(0, int(sec))
    m = sec // 60
    if m < 1:
        return "不到 1 分钟"
    if m < 60:
        return f"{m} 分钟"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h} 小时 {m} 分"
    d, h = divmod(h, 24)
    return f"{d} 天 {h} 小时"


def load_config():
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def cfg_float(cfg, key, default):
    try:
        return min(3.0, max(0.3, float(cfg.get(key, default))))
    except (TypeError, ValueError):
        return default


def remaining_color(left):
    return GREEN if left > 50 else AMBER if left > 20 else RED


# ------------------------------------------------------------------ pet ----

class Pet:
    IDLE_ACTIONS = {"idle", "walk", "sit", "look", "wave", "hop", "dance", "stretch", "yawn", "spin",
                    "juggle", "butterfly", "coffee", "cool"}
    WORK_ACTIONS = {"think", "type", "read", "search", "surf", "code", "plan", "magic", "ask",
                    "summon", "tinker"}

    def __init__(self, root):
        import tkinter as tk
        self.tk = tk
        self.root = root
        cfg = load_config()
        dk = system_dpi() / 96
        # S：一个像素格占多少屏幕像素；k：动作幅度随大小缩放；fk：文字随系统缩放
        self.S = max(2, round(2.67 * cfg_float(cfg, "pet_size", 1.0) * dk))
        self.k = self.S / 4
        self.dk = dk
        self.fk = dk * cfg_float(cfg, "panel_size", 1.0)
        S = self.S
        root.overrideredirect(True)
        root.config(bg=KEY)
        root.attributes("-transparentcolor", KEY)
        self.canvas = tk.Canvas(root, width=GW * S, height=GH * S, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        root.geometry(f"{GW * S}x{GH * S}+-3000+-3000")
        root.update_idletasks()
        self.hwnd = toplevel_hwnd(root)
        make_tool_window(self.hwnd)

        self.f_bubble = ("Microsoft YaHei UI", -round(11 * dk))
        self.f_fx = ("Segoe UI Symbol", -round(10 * dk), "bold")
        self.f_tag = ("Microsoft YaHei UI", -round(9.5 * dk), "bold")

        # 位置与模式
        self.mode = "home"           # home: 在 Claude 窗口里；free: 被拖出去了
        self.x = self.y = 0.0        # 脚底中心的屏幕坐标
        self.rx = None               # home 模式下相对 Claude 窗口左边的位置
        self.vy = 0.0
        self.air = False
        self.facing = 1
        self.shown = None
        self.topmost = None
        self.last_place = None

        # Claude 窗口
        self.claude_pids = set()
        self.claude = None
        self.crect = None
        self.claude_visible = False
        self.missing_checks = 0

        # 动作
        self.t = 0
        self.act, self.at, self.dur = "idle", 0, 60
        self.target_x = 0.0
        self.pose = {}
        self.queue = []
        self.particles = []
        self.bubble = None           # (text, until, kind)
        self.blink_left = 0
        self.last_interaction = time.time()
        self.demo_i = 0

        # 拖动
        self.press = None
        self.dragging = False
        self.click_job = None

        # 数据
        self.limits = {}
        self.reset_seen = {}         # kind -> 已经处理过"到点重置"的那个 resetsAt
        self.quota_at = 0
        self.quota_mtime = None
        self.activity_mtime = None
        self.last_act_key = None
        self.busy_since = 0
        self.tool_at = 0
        self.tool = ""
        self.tool_cat = "tinker"

        self.panel = QuotaPanel(self)
        self.popup = PopupMenu(self)

        c = self.canvas
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_motion)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Double-Button-1>", self.on_double)
        c.bind("<Button-3>", self.on_menu)

        self.poll_files(first=True)
        self.check_claude(initial=True)
        self.enter_home(drop=True)
        for a in ARGS:
            if a.startswith("--demo-start="):
                self.demo_i = int(a.split("=", 1)[1])
        if "--show-panel" in ARGS:
            root.after(2500, self.panel.show)
        root.after(FRAME_MS, self.tick)

    # ------------------------------------------------------------ helpers --

    def say(self, text, secs=2.5, kind="speech"):
        self.bubble = (text, time.time() + secs, kind)

    def fx(self, text, color, dx=0.0, dy=-2.0, vx=0.0, vy=-0.12, life=40, font=None):
        self.particles.append({"text": text, "color": color, "x": OX + 7 + dx, "y": OY + dy,
                               "vx": vx, "vy": vy, "life": life, "font": font or self.f_fx})

    def start(self, name, dur):
        self.act, self.at, self.dur = name, 0, dur

    def react(self, name, dur):
        if self.dragging:
            self.queue.append((name, dur))
        else:
            self.start(name, dur)

    def used(self, l, now=None):
        """这个窗口现在用了多少。过了重置时间就是 0：文件里的数字是重置前的，不能再照着显示。"""
        reset = parse_iso(l.get("resetsAt") or "")
        if reset is not None and reset <= (now or time.time()):
            return 0.0
        try:
            return float(l.get("percentUsed", 0))
        except (TypeError, ValueError):
            return 0.0

    def max_used(self):
        now = time.time()
        vals = [self.used(l, now) for k, l in self.limits.items() if k in ("five_hour", "seven_day")]
        return max(vals) if vals else 0

    def exhausted(self):
        now = time.time()
        return any(k in ("five_hour", "seven_day") and self.used(l, now) >= 100
                   for k, l in self.limits.items())

    def check_resets(self, first=False):
        """到了重置时间：不等下一次回复，直接按"已恢复"显示。"""
        now = time.time()
        changed = False
        for k, l in self.limits.items():
            stamp = l.get("resetsAt")
            reset = parse_iso(stamp or "")
            if reset is None or reset > now or self.reset_seen.get(k) == stamp:
                continue
            self.reset_seen[k] = stamp
            changed = True
            try:
                before = float(l.get("percentUsed", 0))
            except (TypeError, ValueError):
                before = 0.0
            # 只为刚刚发生的重置欢呼；启动时读到的早就过期的数据不算
            if not first and k in ("five_hour", "seven_day") and before > 2 and now - reset < 120:
                self.queue.append(("refresh", 80))
        if changed and self.panel.win:
            self.panel.render()

    def busy(self, now):
        return self.busy_since and now - self.busy_since < 600

    # ------------------------------------------------------------- claude --

    def check_claude(self, initial=False):
        self.claude_pids = desktop_claude_pids()
        if not self.claude_pids:
            self.missing_checks += 1
            if not KEEP and (initial or self.missing_checks >= 2):
                log("Claude desktop is not running; exiting")
                self.quit()
            return
        self.missing_checks = 0
        if not (self.claude and user32.IsWindow(self.claude)):
            self.claude = find_claude_window(self.claude_pids)
        elif not user32.IsWindowVisible(self.claude):
            better = find_claude_window(self.claude_pids)
            if better:
                self.claude = better

    def update_claude_rect(self):
        if self.claude and user32.IsWindow(self.claude):
            self.crect = window_bounds(self.claude)
            self.claude_visible = bool(user32.IsWindowVisible(self.claude)) \
                and not user32.IsIconic(self.claude) and not is_cloaked(self.claude) \
                and self.crect.right - self.crect.left > 200
        else:
            self.claude = None
            self.claude_visible = False

    def enter_home(self, drop=False):
        self.update_claude_rect()
        self.mode = "home"
        if self.crect and self.claude_visible:
            r = self.crect
            w = r.right - r.left
            self.rx = random.uniform(0.25, 0.75) * w if self.rx is None or drop else self.rx
            self.x = r.left + self.rx
            if drop:
                self.y = r.top + 60 * self.k
                self.vy = 0
                self.air = True
                self.queue.append(("hello", 50))
        self.last_interaction = time.time()

    # --------------------------------------------------------------- data --

    def _read_json(self, path, attr):
        try:
            m = os.path.getmtime(path)
        except OSError:
            return None
        if m == getattr(self, attr):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None  # 可能正写到一半，下次再读
        setattr(self, attr, m)
        return data

    def poll_files(self, first=False):
        q = self._read_json(QUOTA_FILE, "quota_mtime")
        if isinstance(q, dict):
            self.on_quota(q, first)
        self.check_resets(first)
        a = self._read_json(ACTIVITY_FILE, "activity_mtime")
        if isinstance(a, dict):
            self.on_activity(a, first)

    def on_quota(self, data, first):
        new = {}
        for l in data.get("rateLimits") or []:
            if isinstance(l, dict) and "kind" in l:
                new[l["kind"]] = l
        if not new:
            return
        if not first and self.limits:
            eaten, refreshed, alert = [], False, None
            for k, l in new.items():
                old = self.limits.get(k)
                if not old:
                    continue
                # 旧窗口已经到点重置的话，是从 0 开始算，而且"恢复"在到点时已经庆祝过了
                before, after = self.used(old), self.used(l)
                d = after - before
                if d < -2:
                    refreshed = True
                elif d > 0.04:
                    eaten.append((k, d))
                    for th in (50, 80, 90, 100):
                        if before < th <= after:
                            alert = (k, th)
            if refreshed:
                self.queue.append(("refresh", 80))
            if eaten:
                eaten.sort(key=lambda e: e[0] != "five_hour")
                self.eat_text = "  ".join(f"{KIND_SHORT.get(k, k)} -{d:.1f}%" for k, d in eaten[:2])
                self.queue.append(("eat", 64))
            if alert:
                k, th = alert
                label = KIND_LABEL.get(k, k)
                msg = f"{label}用光啦！" if th >= 100 else f"{label}已用 {th}%"
                self.queue.append(("alert:" + msg, 90))
        self.limits = new
        self.quota_at = (data.get("at") or 0) / 1000
        if self.panel.win:
            self.panel.render()

    def on_activity(self, d, first):
        key = (d.get("at"), d.get("seq"), d.get("kind"))
        if key == self.last_act_key:
            return
        self.last_act_key = key
        now = time.time()
        if first or now - (d.get("at") or 0) / 1000 > 60:
            return
        self.last_interaction = now
        kind = d.get("kind")
        if self.act in ("sleep",):
            self.fx("!", RED, dy=-3, vy=-0.05, life=30)
        if kind == "prompt":
            self.busy_since, self.tool_at = now, 0
        elif kind == "tool":
            self.busy_since = self.busy_since or now
            self.tool_at, self.tool = now, str(d.get("tool") or "")
            self.tool_cat = tool_category(self.tool)
        elif kind == "done":
            self.busy_since = self.tool_at = 0
            self.react("cheer", 70)
        elif kind == "stopped":
            self.busy_since = self.tool_at = 0
            self.react("oops", 60)

    # -------------------------------------------------------------- input --

    def on_press(self, e):
        self.press = (e.x_root, e.y_root, self.x - e.x_root, self.y - e.y_root)
        self.dragging = False

    def on_motion(self, e):
        if not self.press:
            return
        px, py, _, _ = self.press
        if not self.dragging and abs(e.x_root - px) + abs(e.y_root - py) > 5:
            self.dragging = True
            self.air = False
            self.panel.hide()
            self.start("held", 10 ** 9)
            self.last_interaction = time.time()

    def on_release(self, e):
        if self.dragging:
            self.dragging = False
            self.press = None
            self.drop(e.x_root, e.y_root)
            return
        self.press = None
        if self.click_job:
            self.root.after_cancel(self.click_job)
        self.click_job = self.root.after(260, self.on_single_click)

    def on_single_click(self):
        self.click_job = None
        self.last_interaction = time.time()
        if self.act in ("sleep", "exhausted"):
            if self.act == "exhausted":
                self.say(self.exhausted_text(), 3.5)
            else:
                self.start("wake", 30)
        self.panel.toggle()

    def on_double(self, e):
        if self.click_job:
            self.root.after_cancel(self.click_job)
            self.click_job = None
        self.last_interaction = time.time()
        self.start("pat", 70)

    def on_menu(self, e):
        items = [("查看额度", self.panel.show)]
        if self.mode == "free":
            items.append(("回到 Claude 窗口", lambda: self.enter_home(drop=True)))
        if self.act == "sleep":
            items.append(("叫醒它", lambda: self.start("wake", 30)))
        else:
            items.append(("哄它睡觉", lambda: self.start("sleep", 10 ** 9)))
        items.append(("跳支舞", lambda: self.start("dance", 180)))
        items.append(None)
        items.append(("退出宠物", self.quit))
        self.panel.hide()
        self.popup.show(e.x_root, e.y_root, items)

    def drop(self, cx, cy):
        self.update_claude_rect()
        r = self.crect
        inside = r is not None and self.claude_visible and r.left <= cx <= r.right and r.top <= cy <= r.bottom
        if inside:
            self.mode = "home"
            self.rx = self.x - r.left
        else:
            self.mode = "free"
        self.air = True
        self.vy = 0
        self.start("fall", 10 ** 9)

    # ---------------------------------------------------------------- loop --

    def tick(self):
        try:
            self._tick()
        except Exception:
            if self.t % 300 == 0:
                log("tick error:\n" + traceback.format_exc())
        self.root.after(FRAME_MS, self.tick)

    def _tick(self):
        now = time.time()
        self.t += 1
        if self.t % 15 == 0:
            self.poll_files()
        if self.t % 60 == 0:
            self.check_claude()
        self.update_claude_rect()

        visible = self.mode == "free" or self.dragging or self.claude_visible
        if not visible:
            self.set_shown(False)
            self.panel.hide()
            return
        S = self.S
        if self.mode == "home" and self.crect:
            r = self.crect
            floor = r.bottom - 2
            lo, hi = r.left + 9 * S, r.right - 9 * S
            if not self.dragging:
                if self.rx is None:
                    self.rx = (r.right - r.left) / 2
                self.x = r.left + self.rx
        else:
            wa = work_area_at(self.x, self.y - 5)
            floor = wa.bottom
            lo, hi = wa.left + 9 * S, wa.right - 9 * S
        if hi < lo:
            hi = lo

        if self.dragging:
            cx, cy = cursor_pos()
            _, _, ox, oy = self.press
            self.x, self.y = cx + ox, cy + oy
        elif self.air:
            self.vy += 0.38 * self.k
            self.y += self.vy
            if self.y >= floor:
                self.y = floor
                self.air = False
                hard = self.vy > 6 * self.k
                self.vy = 0
                if self.act == "fall":
                    self.start("land", 14 if hard else 8)
                    if hard:
                        for dx in (-5, 5):
                            self.fx("·", "#B8B0A0", dx=dx, dy=8, vx=dx * 0.03, vy=-0.05, life=14)
        else:
            self.y = floor
        if not self.dragging:
            self.x = min(max(self.x, lo), hi)
        if self.mode == "home" and self.crect and not self.dragging:
            self.rx = self.x - self.crect.left
        self.lo, self.hi = lo, hi

        self.behave(now)
        self.at += 1
        self.update_particles()
        self.draw(now)
        self.set_shown(True)
        self.place()
        self.panel.follow()
        self.popup.poll()

    # ----------------------------------------------------------- behavior --

    def choose_idle(self, now):
        if DEMO:
            seq = ["walk", "sit", "look", "wave", "hop", "dance", "stretch", "yawn", "spin",
                   "juggle", "butterfly", "coffee", "cool", "think", "type", "read", "search", "surf",
                   "code", "plan", "magic", "ask", "summon", "tinker", "cheer", "oops", "eat",
                   "refresh", "alert", "pat", "sleep"]
            name = seq[self.demo_i % len(seq)]
            self.demo_i += 1
            self.eat_text = "5小时 -0.6%"
            if name == "walk":
                self.target_x = random.uniform(self.lo, self.hi)
            self.say(ACTION_LABEL.get(name, name), 1.2, "tag")
            self.start(name, 200 if name == "butterfly" else 110)
            if name == "hop":
                self.air, self.vy = True, -4.2 * self.k
            return
        if self.exhausted():
            self.start("exhausted", 300)
            return
        if now - self.last_interaction > 600 and not self.busy(now):
            self.start("sleep", 10 ** 9)
            return
        tired = self.max_used() >= 80
        weights = {"idle": 28, "walk": 28, "sit": 9, "look": 7, "wave": 4, "hop": 4,
                   "dance": 3, "stretch": 4, "yawn": 3, "spin": 2,
                   "juggle": 3, "butterfly": 3, "coffee": 2, "cool": 2}
        if tired:  # 额度快用完了：没力气玩，靠咖啡续命
            weights.update(sit=25, dance=0, hop=1, spin=0, yawn=8, juggle=0, cool=0, butterfly=1, coffee=12)
        name = random.choices(list(weights), list(weights.values()))[0]
        durs = {"idle": (60, 160), "walk": (400, 400), "sit": (120, 260), "look": (80, 80),
                "wave": (60, 60), "hop": (40, 40), "dance": (160, 160), "stretch": (64, 64),
                "yawn": (60, 60), "spin": (56, 56), "juggle": (144, 144), "butterfly": (200, 200),
                "coffee": (130, 130), "cool": (170, 170)}
        a, b = durs[name]
        self.start(name, random.randint(a, b))
        if name == "walk":
            cx, cy = cursor_pos()
            if self.lo <= cx <= self.hi and random.random() < 0.25:
                self.target_x = cx
            else:
                span = max(60 * self.k, (self.hi - self.lo) * 0.4)
                self.target_x = min(max(self.x + random.uniform(-span, span), self.lo), self.hi)
        if name == "hop":
            self.air, self.vy = True, -4.2 * self.k
        if tired and random.random() < 0.15:
            self.say(random.choice(["有点累了…", "额度不多了，省着点用~"]), 2.5)

    def behave(self, now):
        if self.dragging or self.act in ("fall",):
            pass
        else:
            # 1) Claude 在干活
            work = None
            if self.busy(now) and not DEMO:
                # 工具停了 8 秒就回到"思考"；但"等你回答"要一直举着牌子，直到你回了为止
                waiting = self.tool_cat == "ask" and self.tool_at
                work = self.tool_cat if waiting or now - self.tool_at < 8 else "think"
            if work:
                if self.act != work and self.act not in ("cheer", "oops", "land", "wake", "pat", "hello"):
                    self.start(work, 10 ** 9)
            elif self.act in self.WORK_ACTIONS and not DEMO:
                self.start("idle", 30)
            # 2) 排队的反应（吃额度、提醒等）
            if self.queue and not self.air and self.act in self.IDLE_ACTIONS | {"sleep", "land", "exhausted"} | (
                    self.WORK_ACTIONS if work else set()):
                name, dur = self.queue.pop(0)
                if name.startswith("alert:"):
                    self.say(name[6:], 3.5)
                    name = "alert"
                self.start(name, dur)
            # 3) 当前动作结束，挑下一个
            if self.at >= self.dur and not self.air:
                self.choose_idle(now)

        P = {"dy": 0, "top": 0, "eyes": "open", "lx": 0, "ly": 0, "la": "mid", "ra": "mid",
             "legs": "stand", "blush": False, "props": []}
        self.pose = P
        t = self.at
        # 默认：眨眼 + 看鼠标
        if self.blink_left > 0:
            self.blink_left -= 1
        elif random.random() < 0.012:
            self.blink_left = 5
        cx, cy = cursor_pos()
        if abs(cx - self.x) < 320 * self.k and abs(cy - self.y) < 260 * self.k:
            d = 0 if abs(cx - self.x) < 20 * self.k else (1 if cx > self.x else -1)
            P["lx"] = d * self.facing
            P["ly"] = -1 if cy < self.y - 70 * self.k else 0
        if (self.t // 45) % 2 and self.act in ("idle", "sit", "think"):
            P["la"] = P["ra"] = "mid2"

        getattr(self, "b_" + self.act.split(":")[0], self.b_idle)(P, t, now)
        if self.air and self.act not in ("held",):
            P["legs"] = "tuck"
        if self.blink_left and P["eyes"] == "open":
            P["eyes"] = "closed"

    # 各个动作 ------------------------------------------------------------
    def b_idle(self, P, t, now):
        if self.max_used() >= 80 and t % 240 == 120:
            self.fx("💧", "#7FB8F0", dx=6, dy=-1, vy=0.06, life=30)

    def b_hello(self, P, t, now):
        P["ra"] = "up" if (t // 8) % 2 else "mid"
        P["eyes"] = "happy"
        if t == 1:
            self.say(greeting(), 2.4)

    def b_walk(self, P, t, now):
        speed = 1.6 * self.k * (0.6 if self.max_used() >= 80 else 1.0)
        dx = self.target_x - self.x
        if abs(dx) <= speed:
            self.x = self.target_x
            self.start("idle", random.randint(40, 120))
            return
        self.facing = 1 if dx > 0 else -1
        self.x += speed * self.facing
        P["legs"] = "walk0" if (t // 5) % 2 else "walk1"
        P["lx"] = 1

    def b_sit(self, P, t, now):
        P["dy"], P["legs"] = 2, "none"
        P["la"] = P["ra"] = "down"

    def b_look(self, P, t, now):
        P["lx"] = -1 if (t // 20) % 2 else 1
        if t == 40:
            self.fx("?", INK, dy=-3, vy=-0.04, life=30)

    def b_wave(self, P, t, now):
        P["ra"] = "up" if (t // 8) % 2 else "mid"
        P["eyes"] = "happy"

    def b_hop(self, P, t, now):
        P["la"] = P["ra"] = "up"

    def b_dance(self, P, t, now):
        P["eyes"] = "happy"
        if (t // 10) % 2:
            P["la"], P["ra"] = "up", "mid"
        else:
            P["la"], P["ra"] = "mid", "up"
        if t % 20 == 0:
            self.facing *= -1
        P["top"] = 1 if (t // 5) % 2 else 0   # 跟着拍子一蹲一起
        P["legs"] = "walk0" if (t // 5) % 2 else "walk1"
        if t % 25 == 0:
            self.fx(random.choice("♪♫"), "#9B7BD4", dx=random.uniform(-6, 6), dy=-2, vx=random.uniform(-0.05, 0.05), life=45)

    def b_stretch(self, P, t, now):
        if t < 34:
            P["top"], P["la"], P["ra"], P["eyes"] = -1, "up", "up", "closed"
        else:
            P["top"], P["eyes"] = 1, "happy"

    def b_yawn(self, P, t, now):
        """打哈欠：仰头张大嘴，打完挤出一滴眼泪。"""
        P["eyes"] = "closed"
        if 10 < t < 40:
            P["la"] = P["ra"] = "up"
            P["top"] = -1
            P["props"] += [(c, r, MOUTH) for c in (6, 7) for r in (4, 5)]
        elif 40 <= t < 47:
            P["props"] += [(6, 5, MOUTH), (7, 5, MOUTH)]
        if t == 6:
            self.say("哈啊~", 1.4)
        if t == 44:
            self.fx("💧", "#7FB8F0", dx=5 * self.facing, dy=1, vy=0.05, life=24)

    # 转一圈时两只眼睛依次出现在哪几列：滑到一边 -> 转到背面看不见 -> 从另一边转回来
    SPIN_EYES = ((4, 9), (7, 11), (10,), (), (), (3,), (2, 6), (4, 9))

    def b_spin(self, P, t, now):
        """原地转一圈，转完晕一下。"""
        if t < 40:
            P["eyes"] = "none"
            P["la"] = P["ra"] = "up"
            for c in self.SPIN_EYES[(t // 5) % 8]:
                P["props"] += [(c, 2, EYE), (c, 3, EYE)]
            if t == 1 and not self.air:
                self.air, self.vy = True, -2.6 * self.k
        else:
            P["eyes"] = "x"
            P["la"], P["ra"] = ("mid2", "mid") if (t // 6) % 2 else ("mid", "mid2")
            if t in (40, 52):
                self.fx("💫", "#FFD166", dx=random.uniform(-4, 4), dy=-3, vy=-0.03, life=22)

    def b_juggle(self, P, t, now):
        """抛接三个小球，最后一把全接住。"""
        if t >= self.dur - 16:
            P["eyes"], P["la"], P["ra"] = "happy", "up", "up"
            if t == self.dur - 16:
                self.fx("✦", "#FFD166", dx=0, dy=-4, vy=-0.08, life=22)
            return
        P["ly"] = -1
        P["la"], P["ra"] = ("up", "mid") if (t // 8) % 2 else ("mid", "up")
        for i, col in enumerate(("#E5484D", "#F2C94C", "#4A90D9")):
            ph = (t / 48.0 + i / 3.0) % 1.0
            if ph < 0.75:    # 高抛：从一只手划弧线到另一只手
                u = ph / 0.75
                bx, by = 12.5 - 12.5 * u, -2 - 26 * u * (1 - u)
            else:            # 低传：贴着头顶传回去
                u = (ph - 0.75) / 0.25
                bx, by = 12.5 * u, -2
            c, r = round(bx), round(by)
            P["props"] += [(c, r, col), (c + 1, r, col), (c, r - 1, col), (c + 1, r - 1, col)]

    def b_butterfly(self, P, t, now):
        """追蝴蝶：眼睛跟着蝴蝶转，扑两下没扑到，最后蝴蝶自己停到头顶上。"""
        t0 = self.dur - 60

        def flight(tt):
            return 6.5 + 11 * math.sin(tt / 17.0), -4.5 + 2.5 * math.sin(tt / 6.0)

        if t < t0:
            bx, by = flight(t)
            P["lx"] = 0 if abs(bx - 6.5) < 3 else (1 if bx > 6.5 else -1)
            P["ly"] = -1
            if t % 55 == 40 and not self.air:
                self.air, self.vy = True, -3.6 * self.k
                self.jump_from = self.y
            if self.air:
                P["la"] = P["ra"] = "up"
                # 蝴蝶不跟着宠物一起跳：把跳起来的高度补回去
                by += (getattr(self, "jump_from", self.y) - self.y) / self.S
        else:
            u = min(1.0, (t - t0) / 18.0)
            fx0, fy0 = flight(t0)
            bx, by = fx0 + (6.5 - fx0) * u, fy0 + (-1 - fy0) * u
            P["ly"], P["lx"] = -1, 0
            if u >= 1.0:
                P["blush"] = True
                if t == t0 + 24:
                    self.fx("♥", "#E5484D", dx=5 * self.facing, dy=-4, vy=-0.07, life=30)
        c, r = round(bx), round(by)
        wing = "#9B7BD4"
        if (t // (10 if t >= t0 + 18 else 4)) % 2:
            P["props"] += [(c - 1, r, wing), (c + 1, r, wing), (c - 1, r - 1, wing), (c + 1, r - 1, wing)]
        else:
            P["props"] += [(c - 1, r - 1, wing), (c + 1, r - 1, wing)]
        P["props"].append((c, r, EYE))

    def b_coffee(self, P, t, now):
        """喝咖啡：捧着杯子，凑到嘴边喝一口，再舒一口气。"""
        cycle = t % 65
        sipping = 46 <= cycle < 60
        P["lx"] = 1
        mug = {"m": "#4A90D9", "c": "#6B4226", "h": "#3A78BD"}
        shape = ["cccc.", "mmmmh", "mmmmh", "mmmm."]
        if sipping:
            P["eyes"], P["ra"] = "closed", "mid2"
            stamp(P["props"], shape, 10, 1, mug)
        else:
            P["ra"] = "hold"
            stamp(P["props"], shape, 14, 2, mug)
            if t >= 60 and cycle < 14:
                P["eyes"] = "happy"
            if cycle % 22 == 8:
                self.fx("~", "#B8B0A0", dx=8 * self.facing, dy=0, vy=-0.07, life=26)
        if t == 62:
            self.say("续命咖啡…" if self.max_used() >= 80 else "呼~", 1.8)

    def b_cool(self, P, t, now):
        """戴上墨镜，倒着走一段太空步。"""
        drop = min(2, -4 + t // 3)                  # 墨镜从头顶落到眼睛上
        if drop >= 2:
            P["eyes"] = "none"
        shades = [(c, drop + r, EYE) for c in (3, 4, 5, 8, 9, 10) for r in (0, 1)]
        shades += [(c, drop, EYE) for c in (2, 6, 7, 11)]
        if drop >= 2 and (t // 24) % 3 == 0:
            shades += [(4, 2, "#FFFFFF"), (9, 2, "#FFFFFF")]   # 镜片反光
        P["props"] += shades
        if 30 <= t < self.dur - 24:
            # 脸朝前，身体往后滑
            self.x -= 0.8 * self.k * self.facing
            if self.x <= self.lo or self.x >= self.hi:
                self.facing *= -1
            P["legs"] = "walk0" if (t // 6) % 2 else "walk1"
            P["la"], P["ra"] = "mid2", "mid"
            if t % 40 == 30:
                self.fx(random.choice("♪♫"), "#9B7BD4", dx=random.uniform(-6, 6), dy=-2, vy=-0.08, life=40)
        elif t >= self.dur - 24:
            P["ra"] = "up"
            if t == self.dur - 24:
                self.fx("✦", "#FFD166", dx=7 * self.facing, dy=-2, vy=-0.06, life=22)

    def b_sleep(self, P, t, now):
        P["dy"], P["legs"], P["eyes"] = 2, "none", "closed"
        P["la"] = P["ra"] = "down"
        P["lx"] = P["ly"] = 0
        if is_night():  # 夜里睡觉戴睡帽
            stamp(P["props"], ["...nnnnnn...",
                               "..nnnnnnnn..",
                               "wwwwwwwwwwnn",
                               "...........w"], 1, -1, {"n": "#5B7FD1", "w": "#F2F2F2"})
        if t % 45 == 0:
            self.fx("呼" if (t // 45) % 2 == 0 else "噜", "#8AB4F8", dx=5, dy=-1, vx=0.05, vy=-0.07, life=50)

    def b_wake(self, P, t, now):
        P["eyes"] = "wide"
        if t == 1:
            self.fx("!", RED, dy=-3, vy=-0.05, life=26)
        self.last_interaction = now

    def b_exhausted(self, P, t, now):
        self.b_sleep(P, t, now)
        if t % 150 == 75:
            self.fx("💧", "#7FB8F0", dx=6, dy=0, vy=0.06, life=30)

    def b_think(self, P, t, now):
        """思考：抬眼望天，一会儿挠头，一会儿脚尖点地，时不时冒个问号，想通了亮一下灯泡。"""
        P["ly"] = -1
        P["lx"] = -1 if (t // 50) % 2 else 1
        phase = (t // 90) % 3
        if phase == 1:
            P["ra"] = "up" if (t // 6) % 2 else "mid2"      # 挠头
        elif phase == 2:
            P["legs"] = "tap" if (t // 6) % 2 else "stand"  # 脚尖点地
        if t % 120 == 60:
            self.fx("?", INK, dx=10 * self.facing, dy=-1, vy=-0.05, life=34)
        if 300 <= t % 360 < 326:
            P["eyes"], P["ra"] = "wide", "up"
            if t % 360 == 300:
                self.fx("💡", "#FFD166", dx=10 * self.facing, dy=-1, vy=-0.04, life=30)
        dots = "." * (1 + (t // 12) % 3)
        self.bubble = ("思考中" + dots, now + 0.2, "thought")

    def b_type(self, P, t, now):
        """跑命令：敲一台小终端，黑底绿字一行行往外冒，行尾有个闪烁的光标。"""
        P["lx"] = 1
        P["ra"] = "tap" if (t // 4) % 2 else "mid"
        P["la"] = "down"
        screen, frame, green = "#1F2430", "#45423B", "#5AD17A"
        props = P["props"]
        for c in range(16, 22):
            for r in range(2, 8):
                edge = c in (16, 21) or r in (2, 7)
                props.append((c, r, frame if edge else screen))
        done = (t // 8) % 4                    # 已经打完几行
        for i in range(done):
            w = 2 + (i * 7 + t // 32) % 3
            props += [(c, 3 + i, green) for c in range(17, 17 + w)]
        typed = (t % 8) // 2                   # 当前这一行打了几个字
        props += [(c, 3 + done, green) for c in range(17, 17 + typed)]
        if (t // 3) % 2:
            props.append((17 + typed, 3 + done, "#FFFFFF"))
        for c in range(13, 23):
            props.append((c, 8, frame))
        self.tag_text = tool_label(self.tool)

    def b_read(self, P, t, now):
        """读文件：举着一页文件，一行一行往下读（读到的那行会亮），读完换下一页。"""
        P["lx"] = 1
        P["ra"] = "hold"
        props = P["props"]
        step = (t // 14) % 5                   # 0..2 正在读第几行，3 读完了，4 换页
        if step == 4:                          # 换页：新的一页从上面滑下来
            slide = -2 + (t % 14) // 5
            P["ly"] = -1
        else:
            slide = 0
            P["ly"] = 0 if step == 0 else 1
        stamp(props, ["bbbbb..",
                      "bwwwbb.",
                      "bwwwwwb",
                      "bwwwwwb",
                      "bwwwwwb",
                      "bwwwwwb",
                      "bwwwwwb",
                      "bwwwwwb",
                      "bbbbbbb"], 14, -1 + slide, {"b": "#5A564C", "w": "#FFFFFF"})
        for i, width in enumerate((3, 3, 2)):
            if step == 4:
                color = "#C9C2B2"
            else:
                color = BODY if i == step else ("#5A564C" if i < step else "#C9C2B2")
            props += [(16 + c, 2 + 2 * i + slide, color) for c in range(width)]
        self.tag_text = tool_label(self.tool)

    def b_search(self, P, t, now):
        """搜索：举着放大镜来回扫，扫到东西眼睛一亮。"""
        P["lx"] = 1
        P["ra"] = "hold"
        sweep = (0, 1, 2, 3, 2, 1)[(t // 8) % 6]
        bob = -1 if (t // 14) % 2 else 0
        ring = [(17, -2), (18, -2), (16, -1), (19, -1), (16, 0), (19, 0), (17, 1), (18, 1)]
        glass = [(17, -1), (18, -1), (17, 0), (18, 0)]
        props = P["props"]
        props += [(c + sweep, r + 2 + bob, "#5A564C") for c, r in ring]
        props += [(c + sweep, r + 2 + bob, "#CFE8FF") for c, r in glass]
        props += [(c, 3 + bob, "#8B5A2B") for c in range(15, 17 + sweep)]
        P["ly"] = -1 if bob else 0
        if t % 96 >= 80:
            P["eyes"] = "wide"
            if t % 96 == 80:
                self.fx("!", RED, dx=12 * self.facing, dy=-2, vy=-0.05, life=22)
        self.tag_text = tool_label(self.tool)

    def b_surf(self, P, t, now):
        """上网：踩着冲浪板在浪上起伏（上网冲浪）。"""
        bob = (t // 10) % 2
        P["dy"] = -3 + bob
        P["lx"] = 1
        P["la"], P["ra"] = ("up", "mid") if (t // 20) % 2 else ("mid", "up")   # 张开手保持平衡
        if (t // 60) % 3 == 2:
            P["eyes"] = "happy"
        props = P["props"]
        water, foam = "#4AA3DF", "#BFE6FA"
        # 身后追上来的一道浪
        stamp(props, ["..f..",
                      ".fww.",
                      "fwwww"], -7, 5, {"w": water, "f": foam})
        for c in range(-7, 21):
            crest = (c + t // 4) % 6 < 3
            props.append((c, 8, water))
            if crest:
                props.append((c, 7, foam if (c + t // 4) % 6 == 0 else water))
        # 冲浪板垫在脚下
        board = 6 + bob
        props += [(c, board, "#F2C94C") for c in range(-1, 16)]
        props += [(6, board, RED), (7, board, RED), (16, board - 1, "#F2C94C")]
        if t % 30 == 12:
            self.fx("·", foam, dx=-9 * self.facing, dy=4, vx=-0.06 * self.facing, vy=-0.1, life=18)
        self.tag_text = tool_label(self.tool)

    def b_plan(self, P, t, now):
        """列计划：举着写字板，一项一项打勾。"""
        P["lx"] = 1
        P["ra"] = "hold"
        props = P["props"]
        stamp(props, ["..ggg..",
                      "bbbbbbb",
                      "bpppppb",
                      "bpppppb",
                      "bpppppb",
                      "bpppppb",
                      "bpppppb",
                      "bbbbbbb"], 14, -1, {"g": "#9AA0A6", "b": "#8B5A2B", "p": "#FFFFFF"})
        step = (t // 18) % 5                   # 0..3 是已经勾了几项，4 是全勾完后停一下
        done = min(step, 3)
        for i in range(3):
            r = 1 + 2 * i
            props.append((15, r, GREEN if i < done else "#B8B0A0"))
            props += [(c, r, "#D8D2C4" if i < done else "#8A8580") for c in (17, 18, 19)]
        if step >= 3:
            P["eyes"] = "happy"
        if t % 18 == 0 and 1 <= step <= 3:
            self.fx("✓", GREEN, dx=11 * self.facing, dy=-2, vy=-0.07, life=20)
        self.tag_text = tool_label(self.tool)

    def b_magic(self, P, t, now):
        """用技能：戴上巫师帽，挥魔杖，杖尖冒星星。"""
        P["la"], P["ra"] = "mid", "up"
        if (t // 30) % 2:
            P["eyes"] = "happy"
        props = P["props"]
        stamp(props, [".....hhh....",
                      "....hhhhh...",
                      "...bbbbbbb..",
                      "hhhhhhhhhhhh"], 1, -4, {"h": "#6C4AB6", "b": "#F2C94C"})
        up = (t // 9) % 2
        wand = [(14, -1), (15, -2), (16, -3)] if up else [(14, 0), (15, 0), (16, 0)]
        tip = (17, -4) if up else (17, 0)
        props += [(c, r, "#8B5A2B") for c, r in wand]
        props.append((tip[0], tip[1], "#FFD166"))
        if t % 9 == 0:
            self.fx(random.choice("✦✧"), random.choice(["#FFD166", "#9B7BD4", "#7FC8F8"]),
                    dx=(tip[0] - 7) * self.facing + random.uniform(-1, 1), dy=tip[1] - 1,
                    vx=0.06 * self.facing, vy=-0.08, life=24)
        self.tag_text = tool_label(self.tool)

    def b_ask(self, P, t, now):
        """Claude 在等你回答：旁边插一块问号牌，朝你挥手，隔一会儿蹦一下。眼睛照常跟着鼠标看你。"""
        P["la"] = "up" if (t // 8) % 2 else "mid"
        if t % 90 == 45 and not self.air:
            self.air, self.vy = True, -3.0 * self.k
            self.jump_from = self.y
        # 牌子是插在地上的：宠物蹦起来时牌子留在原地
        sink = round((getattr(self, "jump_from", self.y) - self.y) / self.S) if self.air else 0
        props = P["props"]
        props += [(18, r + sink, "#8B5A2B") for r in range(4, 9)]
        stamp(props, ["bbbbbbb",
                      "bwqqqwb",
                      "bqwwwqb",
                      "bwwwwqb",
                      "bwwwqwb",
                      "bwwqwwb",
                      "bwwwwwb",
                      "bwwqwwb",
                      "bbbbbbb"], 15, -5 + sink, {"b": "#5A564C", "w": "#FFFFFF", "q": RED})
        self.bubble = ("等你回答~", now + 0.2, "speech")

    def b_code(self, P, t, now):
        """写代码：侧过身，伸手握着铅笔在地上一行一行地写。"""
        P["la"] = P["ra"] = "hide"
        P["lx"] = 2                                # 侧着身子：眼睛靠向写字的那一边
        P["ly"] = 0 if (t // 45) % 4 == 3 else 1   # 大多数时候低头盯着笔尖，偶尔抬一下眼
        props = P["props"]
        # 背光的一面颜色深一点，看起来是侧着身子
        props += [(c, r, SHADE) for c in (2, 3) for r in range(0, 7)]
        props += [(3, 7, SHADE), (3, 8, SHADE)]
        # 一行分 4 步写完，然后抬笔回到行首
        step = (t // 5) % 6
        reach, lift = ((0, 0), (1, 0), (2, 0), (3, 0), (2, 1), (0, 1))[step]
        # 手臂：一截粗短的上臂贴着身体，前臂跟着手伸出去
        props += [(c, r, BODY) for c in (12, 13) for r in (3, 4, 5)]
        props += [(c, r, BODY) for c in range(14, 14 + reach) for r in (4, 5)]
        hand = 13 + reach
        props += [(c, r - lift, SHADE) for c in (hand, hand + 1) for r in (6, 7)]
        # 写出来的那一行
        tip = hand + 2
        written = range(15, tip if not lift else 19)
        props += [(c, 8, "#A3A3A3") for c in written]
        # 铅笔：笔尖点地，笔杆向外斜
        props.append((tip, 8 - lift, "#5A564C"))
        props += [(tip + i, 8 - lift - i, "#8B8B8B") for i in (1, 2, 3)]
        if t % 50 == 25:
            self.fx(random.choice(["{ }", "</>", "( )", "=>", ";"]), "#5E9BE0",
                    dx=10 * self.facing, dy=0, vx=0.04 * self.facing, vy=-0.1, life=34)
        self.tag_text = tool_label(self.tool)

    GEAR = (["..g..", ".ggg.", "ggogg", ".ggg.", "..g.."],
            ["g...g", ".ggg.", ".gog.", ".ggg.", "g...g"])

    def b_tinker(self, P, t, now):
        """别的工具：抡锤子敲一个齿轮，敲一下齿轮转一格，溅出火花。"""
        down = (t // 9) % 2 == 1
        props = P["props"]
        stamp(props, self.GEAR[((t + 9) // 18) % 2], 17, 4, {"g": "#9AA0A6", "o": "#5A564C"})
        handle, head = "#8B5A2B", "#6F757B"
        if down:
            P["ra"] = "hold"
            props += [(15, 3, handle), (16, 3, handle), (17, 3, handle)]
            props += [(c, r, head) for c in (18, 19) for r in (2, 3)]
            if t % 18 == 9:
                self.fx("✦", "#FFD166", dx=12 * self.facing, dy=3, vx=0.08 * self.facing, vy=-0.1, life=16)
        else:
            P["ra"] = "up"
            props += [(13, -2, handle), (13, -3, handle)]
            props += [(c, r, head) for c in (12, 13, 14) for r in (-5, -4)]
        P["lx"] = 1
        self.tag_text = tool_label(self.tool)

    def b_summon(self, P, t, now):
        P["eyes"] = "happy"
        P["la"], P["ra"] = ("up", "mid") if (t // 12) % 2 else ("mid", "up")
        props = P["props"]
        for ox, phase in ((-10, 0), (18, 1)):
            bob = 1 if ((t // 8) + phase) % 2 else 0
            for c in range(1, 6):
                for r in range(0, 3):
                    props.append((ox + c, 5 + r - bob, BODY))
            props += [(ox, 6 - bob, BODY), (ox + 6, 6 - bob, BODY)]
            props += [(ox + 2, 6 - bob, EYE), (ox + 4, 6 - bob, EYE)]
            props += [(ox + 2, 8, BODY), (ox + 4, 8, BODY)]
        self.tag_text = tool_label(self.tool)

    def b_cheer(self, P, t, now):
        P["eyes"] = "happy"
        P["la"] = P["ra"] = "up"
        P["blush"] = True
        if t == 1:
            self.air, self.vy = True, -4.6 * self.k
            self.say(random.choice(CHEERS), 2.0)
        if t in (1, 12, 24):
            for _ in range(2):
                self.fx("✦", "#FFD166", dx=random.uniform(-8, 8), dy=random.uniform(-4, 0),
                        vx=random.uniform(-0.1, 0.1), vy=-0.1, life=30)

    def b_oops(self, P, t, now):
        P["eyes"] = "x"
        P["la"] = P["ra"] = "up"
        if t == 1:
            self.say(random.choice(OOPS), 2.0)
            self.fx("💧", "#7FB8F0", dx=6, dy=-1, vy=0.06, life=30)

    COOKIE = ["ooo", "oxo", "oox"]

    def b_eat(self, P, t, now):
        """用掉了一点额度：天上掉下一块饼干，接住，三口吃掉，然后报出吃了多少。"""
        props = P["props"]
        colors = {"o": "#C68642", "x": "#5A3A1A"}
        if t < 20:       # 饼干落下来，伸手去接
            stamp(props, self.COOKIE, 14, round(-12 + t * 0.75), colors)
            P["lx"], P["ly"], P["eyes"] = 1, -1, "wide"
            P["la"] = P["ra"] = "up"
        elif t < 44:     # 一口一口啃：每 8 帧少一列
            bites = (t - 20) // 8
            P["lx"], P["ra"] = 1, "mid"
            P["top"] = 1 if (t // 4) % 2 else 0
            stamp(props, [row[bites:] for row in self.COOKIE], 14 + bites, 3, colors)
            if (t - 20) % 8 == 0:
                self.fx("·", "#C68642", dx=8 * self.facing, dy=5, vx=0.05 * self.facing, vy=0.06, life=14)
        else:
            P["eyes"] = "happy"
            P["blush"] = True
            if t == 44:
                self.fx(getattr(self, "eat_text", "-1%"), "#D97757", dy=-3, vy=-0.07, life=60,
                        font=("Microsoft YaHei UI", -round(10 * self.dk), "bold"))
            if t == 48:
                self.fx("♥", "#E5484D", dx=5, dy=-2, vy=-0.08, life=30)

    def b_refresh(self, P, t, now):
        """额度恢复：头顶的电池一格一格充满，充满后跳起来欢呼。"""
        if t < 40:
            P["eyes"] = "closed"
            P["la"] = P["ra"] = "mid2"
            cells = min(6, t // 6)
            props = P["props"]
            stamp(props, ["bbbbbbbb.",
                          "bwwwwwwbb",
                          "bwwwwwwbb",
                          "bbbbbbbb."], 3, -5, {"b": "#5A564C", "w": "#FFFFFF"})
            props += [(4 + i, r, GREEN) for i in range(cells) for r in (-4, -3)]
            return
        self.b_cheer(P, t - 39, now)
        if t == 41:
            self.say("额度恢复啦！满血复活~", 3.0)

    def b_alert(self, P, t, now):
        """额度提醒：瞪大眼睛，举起一面小红旗使劲摇。"""
        P["eyes"] = "wide"
        P["ra"] = "up"
        props = P["props"]
        props += [(13, r, "#8B5A2B") for r in (-5, -4, -3, -2)]
        if (t // 6) % 2:
            props += [(c, r, RED) for c in (14, 15, 16) for r in (-5, -4)]
        else:
            props += [(14, -5, RED), (15, -5, RED), (14, -4, RED), (15, -4, RED), (16, -4, RED), (16, -3, RED)]
        if t == 1:
            self.fx("!", RED, dx=-8 * self.facing, dy=-2, vy=-0.04, life=40)

    def b_pat(self, P, t, now):
        P["eyes"] = "happy"
        P["blush"] = True
        P["top"] = 1 if (t // 10) % 2 else 0
        if t % 18 == 1:
            self.fx("♥", "#E5484D", dx=random.uniform(-6, 6), dy=-2, vy=-0.08, life=34)
        if t == 1:
            self.say(random.choice(["嘿嘿~", "好舒服~", "再摸摸！"]), 1.8)

    def b_held(self, P, t, now):
        P["legs"] = "dangle0" if (t // 6) % 2 else "dangle1"
        P["eyes"] = "x" if t < 24 else "wide"
        P["la"] = P["ra"] = "up"
        P["lx"] = P["ly"] = 0

    def b_fall(self, P, t, now):
        P["legs"] = "dangle0"
        P["eyes"] = "wide"
        P["la"] = P["ra"] = "up"

    def b_land(self, P, t, now):
        P["top"] = 1
        P["eyes"] = "closed" if self.dur > 10 else "open"
        P["la"] = P["ra"] = "down"

    def exhausted_text(self):
        now = time.time()
        waits = []
        for k in ("five_hour", "seven_day"):
            l = self.limits.get(k)
            if l and l.get("percentUsed", 0) >= 100:
                r = parse_iso(l.get("resetsAt") or "")
                if r:
                    waits.append(r - now)
        if waits:
            return f"额度用光了…{fmt_duration(max(waits))}后恢复"
        return "额度用光了…"

    # ------------------------------------------------------------ drawing --

    def compose(self):
        P = self.pose
        top, dy = P["top"], P["dy"]
        out = []
        for r in range(top, 7):
            for c in range(2, 12):
                out.append((c, r + dy, BODY))
        arm_rows = {"mid": (3, 4), "mid2": (4, 5), "up": (-1, 0), "down": (5, 6)}
        for side, kind in (("l", P["la"]), ("r", P["ra"])):
            cols = (0, 1) if side == "l" else (12, 13)
            if kind == "hide":  # 这只手由动作自己画，或者被身体挡住了
                continue
            if kind == "tap" and side == "r":
                out += [(12, 5 + dy, BODY), (13, 5 + dy, BODY), (14, 5 + dy, BODY)]
            elif kind == "hold" and side == "r":
                out += [(12, 3 + dy, BODY), (13, 3 + dy, BODY), (14, 3 + dy, BODY),
                        (12, 4 + dy, BODY), (13, 4 + dy, BODY)]
            else:
                rows = arm_rows.get(kind, (3, 4))
                if kind == "up":
                    rows = (top - 1, top)
                for c in cols:
                    for r in rows:
                        out.append((c, r + dy, BODY))
        legs = P["legs"]
        if legs != "none":
            for i, c in enumerate(LEG_COLS):
                even = i in (0, 2)
                if legs == "stand":
                    rows = (7, 8)
                elif legs in ("walk0", "walk1"):
                    rows = (7, 8) if even == (legs == "walk0") else (7,)
                elif legs == "tuck":
                    rows = (7,)
                elif legs == "tap":  # 前脚抬起来点地
                    rows = (7,) if i == 3 else (7, 8)
                elif legs in ("dangle0", "dangle1"):
                    rows = (7, 8, 9) if even == (legs == "dangle0") else (7, 8)
                else:
                    rows = (7, 8)
                for r in rows:
                    out.append((c, r + dy, BODY))
        if P["blush"]:
            out += [(3, 4 + dy + max(top, 0), BLUSH), (10, 4 + dy + max(top, 0), BLUSH)]
        r0 = 2 + dy + top
        lx, ly = P["lx"], P["ly"]
        style = P["eyes"]
        for idx, base in enumerate((4, 9)):
            c = base + (lx if style in ("open", "wide") else 0)
            r = r0 + (ly if style in ("open",) else 0)
            if style == "open":
                out += [(c, r, EYE), (c, r + 1, EYE)]
            elif style == "wide":
                out += [(c, r - 1, EYE), (c, r, EYE), (c, r + 1, EYE)]
            elif style == "closed":
                out += [(c - 1, r + 1, EYE), (c, r + 1, EYE), (c + 1, r + 1, EYE)]
            elif style == "happy":
                out += [(c - 1, r + 1, EYE), (c, r, EYE), (c + 1, r + 1, EYE)]
            elif style == "x":
                if idx == 0:
                    out += [(c - 1, r - 1, EYE), (c, r, EYE), (c - 1, r + 1, EYE)]
                else:
                    out += [(c + 1, r - 1, EYE), (c, r, EYE), (c + 1, r + 1, EYE)]
        out += P["props"]
        return out

    def draw(self, now):
        c = self.canvas
        S = self.S
        c.delete("all")
        for gx, gy, col in self.compose():
            mx = gx if self.facing > 0 else 13 - gx
            X, Y = (OX + mx) * S, (OY + gy) * S
            c.create_rectangle(X, Y, X + S, Y + S, fill=col, outline="")
        for p in self.particles:
            c.create_text(p["x"] * S, p["y"] * S, text=p["text"], fill=p["color"], font=p["font"])
        cx = (OX + 7) * S
        if self.bubble and self.bubble[1] > now:
            text, _, kind = self.bubble
            if kind == "tag":
                self.draw_tag(cx, (OY - 4) * S, text)
            else:
                self.draw_bubble(cx, (OY - 5) * S, text, thought=(kind == "thought"))
        else:
            self.bubble = None
            tag = getattr(self, "tag_text", "")
            if tag and self.act in self.WORK_ACTIONS and self.act != "think":
                self.draw_tag(cx, (OY - 4) * S, tag)
        self.tag_text = ""

    def draw_tag(self, cx, bottom, text):
        """头顶的小标签（正在用的工具名）。"""
        c = self.canvas
        S = self.S
        text = text if len(text) <= 22 else text[:21] + "…"
        tid = c.create_text(cx, bottom - S, text=text, fill="#FFFFFF", font=self.f_tag, anchor="s")
        x1, y1, x2, y2 = c.bbox(tid)
        pad = S
        shift = 0
        if x1 - pad < 2:
            shift = 2 - (x1 - pad)
        elif x2 + pad > GW * S - 2:
            shift = GW * S - 2 - (x2 + pad)
        c.move(tid, shift, 0)
        c.create_rectangle(x1 - pad + shift, y1 - 1, x2 + pad + shift, y2 + 1, fill="#5E5A50", outline="")
        c.tag_raise(tid)

    def draw_bubble(self, cx, bottom, text, thought=False):
        c = self.canvas
        S = self.S
        tid = c.create_text(cx, bottom - S * 2, text=text, fill=INK, font=self.f_bubble, anchor="s")
        x1, y1, x2, y2 = c.bbox(tid)
        pad = S * 2
        x1, x2 = x1 - pad, x2 + pad
        shift = 0
        if x1 < 2:
            shift = 2 - x1
        elif x2 > GW * S - 2:
            shift = GW * S - 2 - x2
        x1, x2 = x1 + shift, x2 + shift
        c.move(tid, shift, 0)
        y1 -= S
        y2 += S
        c.create_rectangle(x1, y1, x2, y2, fill="#FFFFFF", outline=INK, width=max(1, S // 2))
        if thought:
            c.create_rectangle(cx - S, y2 + S, cx + S // 2, y2 + S * 2.5, fill="#FFFFFF", outline=INK, width=1)
        else:
            c.create_polygon(cx - S, y2 - 1, cx + S, y2 - 1, cx, y2 + S * 1.5, fill="#FFFFFF", outline=INK)
            c.create_line(cx - S + 1, y2 - 1, cx + S - 1, y2 - 1, fill="#FFFFFF", width=max(1, S // 2))
        c.tag_raise(tid)

    def update_particles(self):
        alive = []
        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["life"] -= 1
            if p["life"] > 0:
                alive.append(p)
        self.particles = alive[-30:]

    # ---------------------------------------------------------- placement --

    def set_shown(self, show):
        if show == self.shown:
            return
        self.shown = show
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE if show else SW_HIDE)
        self.last_place = None

    def place(self):
        S = self.S
        wx = round(self.x) - (OX + 7) * S
        wy = round(self.y) - GH * S
        want_top = self.mode == "free" or self.dragging or self.air and self.act == "fall"
        insert = None
        if want_top:
            if self.topmost is not True:
                insert = HWND_TOPMOST
                self.topmost = True
        else:
            if self.topmost is not False:
                user32.SetWindowPos(self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                self.topmost = False
            if self.claude:
                prev = user32.GetWindow(self.claude, GW_HWNDPREV)
                while prev and prev == self.panel.hwnd:
                    prev = user32.GetWindow(prev, GW_HWNDPREV)
                if prev != self.hwnd:
                    insert = HWND_TOP if (not prev or is_topmost(prev)) else prev
        if insert is None and (wx, wy) == self.last_place:
            return
        flags = SWP_NOSIZE | SWP_NOACTIVATE | (SWP_NOZORDER if insert is None else 0)
        user32.SetWindowPos(self.hwnd, insert or 0, wx, wy, 0, 0, flags)
        self.last_place = (wx, wy)

    def quit(self):
        try:
            self.root.destroy()
        except Exception:
            pass


# --------------------------------------------------------------- panel ----

class QuotaPanel:
    def __init__(self, pet):
        self.pet = pet
        self.win = None
        self.hwnd = None
        self.until = 0
        self.last_pos = None
        self.size = (0, 0)

    def toggle(self):
        if self.win:
            self.hide()
        else:
            self.show()

    def show(self):
        tk = self.pet.tk
        if not self.win:
            self.win = tk.Toplevel(self.pet.root)
            self.win.overrideredirect(True)
            self.win.attributes("-topmost", True)
            self.canvas = tk.Canvas(self.win, bg=PAPER, highlightthickness=0, bd=0)
            self.canvas.pack()
            self.canvas.bind("<Button-1>", lambda e: self.hide())
            self.win.update_idletasks()
            self.hwnd = toplevel_hwnd(self.win)
            make_tool_window(self.hwnd)
            self.last_pos = None
        self.render()
        self.until = time.time() + 15
        self.follow()

    def hide(self):
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
        self.win = None
        self.hwnd = None

    def render(self):
        if not self.win:
            return
        pet = self.pet
        f = pet.fk  # 以 100% 缩放下的像素为单位，乘上系统缩放
        c = self.canvas
        c.delete("all")
        W = round(196 * f)
        pad = round(9 * f)
        f_title = ("Microsoft YaHei UI", -round(12 * f), "bold")
        f_body = ("Microsoft YaHei UI", -round(11 * f))
        f_num = ("Microsoft YaHei UI", -round(11 * f), "bold")
        f_small = ("Microsoft YaHei UI", -round(9.5 * f))
        y = pad
        c.create_text(pad, y, text="Claude 额度", anchor="nw", font=f_title, fill=INK)
        now = time.time()
        if pet.quota_at:
            age = now - pet.quota_at
            ago = "刚刚更新" if age < 60 else f"{fmt_duration(age)}前更新"
            c.create_text(W - pad, y + round(2 * f), text=ago, anchor="ne", font=f_small,
                          fill=RED if age > 6 * 3600 else "#8A8580")
        y += round(22 * f)
        kinds = [k_ for k_ in ("five_hour", "seven_day") if k_ in pet.limits] + \
                [k_ for k_ in pet.limits if k_ not in ("five_hour", "seven_day")]
        if not kinds:
            for line in ("还没有额度数据。", "在 Claude 里发一条消息，", "回复之后这里就会显示。"):
                c.create_text(pad, y, text=line, anchor="nw", font=f_body, fill=INK)
                y += round(16 * f)
            y += round(4 * f)
        for kind in kinds:
            l = pet.limits[kind]
            used = pet.used(l, now)
            left = max(0.0, round(100 - used, 1))
            c.create_text(pad, y, text=KIND_LABEL.get(kind, kind), anchor="nw", font=f_body, fill=INK)
            c.create_text(W - pad, y, text=f"剩 {left:g}%", anchor="ne", font=f_num, fill=remaining_color(left))
            y += round(17 * f)
            bx1, bx2, bh = pad, W - pad, max(3, round(6 * f))
            c.create_rectangle(bx1, y, bx2, y + bh, fill="#ECE8DD", outline="")
            fill_w = (bx2 - bx1) * min(100.0, left) / 100
            if fill_w > 0:
                c.create_rectangle(bx1, y, bx1 + fill_w, y + bh, fill=remaining_color(left), outline="")
            # 像素刻度
            step = (bx2 - bx1) / 20
            for i in range(1, 20):
                x = bx1 + step * i
                c.create_line(x, y, x, y + bh, fill=PAPER)
            y += bh + round(3 * f)
            reset = parse_iso(l.get("resetsAt") or "")
            if reset:
                txt = f"{fmt_duration(reset - now)}后重置" if reset > now else "已重置，下次用到时开始新一轮"
            else:
                txt = "重置时间未知"
            c.create_text(pad, y, text=txt, anchor="nw", font=f_small, fill="#8A8580")
            y += round(18 * f)
        c.create_line(pad, y, W - pad, y, fill="#E3DED2")
        y += round(5 * f)
        c.create_text(pad, y, text="拖动我 · 双击摸摸 · 右键菜单", anchor="nw", font=f_small, fill="#8A8580")
        y += round(14 * f) + pad // 2
        c.create_rectangle(0, 0, W - 1, y - 1, outline=BODY, width=max(1, round(1.5 * f)))
        c.config(width=W, height=y)
        self.size = (W, y)
        self.win.geometry(f"{W}x{y}")
        self.last_pos = None

    def follow(self):
        if not self.win:
            return
        now = time.time()
        if now > self.until:
            self.hide()
            return
        if self.pet.t % 30 == 0:
            self.render()
        pet = self.pet
        W, H = self.size
        x = round(pet.x - W / 2)
        y = round(pet.y - 11 * pet.S - H - 4 * pet.dk)
        wa = work_area_at(pet.x, pet.y - 5)
        x = min(max(x, wa.left + 4), wa.right - W - 4)
        if y < wa.top + 4:
            y = round(pet.y + 4 * pet.k)
        if (x, y) != self.last_pos:
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
            self.last_pos = (x, y)


# ---------------------------------------------------------------- menu ----

class PopupMenu:
    """右键小菜单：和额度面板同一风格，大小随 panel_size 缩放。

    点菜单外面（失去焦点）、按 Esc、鼠标移开一会儿、或 10 秒没操作都会自动关上。
    """

    def __init__(self, pet):
        self.pet = pet
        self.win = None
        self.rect = None
        self.opened = 0
        self.away_ticks = 0

    def show(self, x, y, items):
        self.hide()
        tk = self.pet.tk
        f = self.pet.fk
        font = ("Microsoft YaHei UI", -round(10.5 * f))
        win = tk.Toplevel(self.pet.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        border = max(1, round(1.5 * f))
        win.config(bg=BODY)
        box = tk.Frame(win, bg=PAPER)
        box.pack(padx=border, pady=border)
        tk.Frame(box, bg=PAPER, height=round(3 * f)).pack(fill="x")
        for item in items:
            if item is None:
                tk.Frame(box, bg="#E3DED2", height=1).pack(fill="x", padx=round(6 * f), pady=round(3 * f))
                continue
            label, cmd = item
            danger = label.startswith("退出")
            w = tk.Label(box, text=label, font=font, bg=PAPER, fg=RED if danger else INK,
                         anchor="w", padx=round(10 * f), pady=round(2 * f), cursor="hand2")
            w.pack(fill="x")
            w.bind("<Enter>", lambda e, w=w: w.config(bg="#F3E3DA"))
            w.bind("<Leave>", lambda e, w=w: w.config(bg=PAPER))
            w.bind("<ButtonRelease-1>", lambda e, cmd=cmd: self.choose(cmd))
        tk.Frame(box, bg=PAPER, height=round(3 * f)).pack(fill="x")
        win.update_idletasks()
        W, H = win.winfo_reqwidth(), win.winfo_reqheight()
        wa = work_area_at(x, y)
        x = min(max(x, wa.left), wa.right - W)
        y = min(max(y, wa.top), wa.bottom - H)
        win.geometry(f"{W}x{H}+{x}+{y}")
        win.bind("<FocusOut>", lambda e: self.hide())
        win.bind("<Escape>", lambda e: self.hide())
        self.win = win
        self.rect = (x, y, x + W, y + H)
        self.opened = time.time()
        self.away_ticks = 0
        win.focus_force()

    def choose(self, cmd):
        self.hide()
        self.pet.last_interaction = time.time()
        cmd()

    def hide(self):
        if self.win:
            try:
                self.win.destroy()
            except Exception:
                pass
        self.win = None

    def poll(self):
        if not self.win:
            return
        if time.time() - self.opened > 10:
            self.hide()
            return
        cx, cy = cursor_pos()
        x1, y1, x2, y2 = self.rect
        m = round(40 * self.pet.dk)
        if x1 - m <= cx <= x2 + m and y1 - m <= cy <= y2 + m:
            self.away_ticks = 0
        else:
            self.away_ticks += 1
            if self.away_ticks > 45:  # 鼠标离开 1.5 秒
                self.hide()


# ---------------------------------------------------------------- main ----

def main():
    if "--spawn" in ARGS:
        spawn_detached()
        return
    if "--install-autostart" in ARGS:
        install_autostart()
        return
    if "--uninstall-autostart" in ARGS:
        uninstall_autostart()
        return
    if "--watch" in ARGS:
        try:
            watch()
        except Exception:
            log("watch fatal:\n" + traceback.format_exc())
        return
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return
    set_dpi_awareness()
    import tkinter as tk
    root = tk.Tk()
    root.title("Claude Pet")
    try:
        Pet(root)
        root.mainloop()
    except Exception:
        log("fatal:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
