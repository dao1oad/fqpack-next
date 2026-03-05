"""给木偶写的一些工具函数
"""
import configparser
import ctypes
import datetime
import io
import os
import subprocess
import threading
import time
import winreg
from ctypes.wintypes import BOOL, HWND, LPARAM

import win32con
import win32gui
import win32process

try:
    import pandas as pd
except Exception as e:
    print(e)

try:
    import keyboard
except Exception as e:
    print(e)
    from pywinauto import keyboard

    keyboard.write = keyboard.send_keys


class Msg:

    WM_SETTEXT = 12
    WM_GETTEXT = 13
    WM_GETTEXTLENGTH = 14
    WM_CLOSE = 16
    WM_KEYDOWN = 256
    WM_KEYUP = 257
    WM_COMMAND = 273
    BM_GETCHECK = 240
    BM_SETCHECK = 241
    BM_GETSTATE = 242
    BM_CLICK = 245
    BST_CHECKED = 1
    CB_GETCOUNT = 326
    CB_GETCURSEL = 327
    CB_SETCURSEL = 334
    CB_SHOWDROPDOWN = 335
    CBN_SELCHANGE = 1
    CBN_SELENDOK = 9
    MOUSEEVENTF_LEFTDOWN = 2
    MOUSEEVENTF_LEFTUP = 4
    MOUSEEVENTF_RIGHTDOWN = 8
    MOUSEEVENTF_RIGHTUP = 16


COLNAMES = {
    "证券代码": "symbol",
    "证券名称": "name",
    "股票余额": "quantity",  # 海通证券
    "当前持仓": "quantity",  # 银河证券
    "可用余额": "leftover",
    "冻结数量": "frozen",
    "盈亏": "profit",
    "参考盈亏": "profit",  # 银河证券
    "浮动盈亏": "profit",  # 广发证券
    "市价": "price",
    "市值": "amount",
    "参考市值": "amount",  # 银河证券
    "最新市值": "amount",  # 国金|平安证券
    "成本价": "cost",
    "成交时间": "time",
    "成交日期": "date",
    "成交数量": "quantity",
    "成交均价": "price",
    "成交价格": "price",
    "成交金额": "amount",
    "成交编号": "id",
    "申报时间": "time",
    "委托日期": "date",
    "委托时间": "time",
    "委托价格": "order_price",
    "委托数量": "order_qty",
    "合同编号": "order_id",
    "委托编号": "order_id",  # 银河证券
    "委托状态": "status",
    "操作": "op",
    "发生金额": "total",
    "手续费": "commission",
    "印花税": "tax",
    "其他杂费": "fees",
    "资金余额": "balance",  # 银河证券
    "可用金额": "cash",
    "总市值": "market_value",
    "总资产": "equity",
}

OPTIONS = {
    "GUI_CHEDAN_CONFIRM": "no",
    "GUI_LOCK_TIMEOUT": "9999999999999999999999999999999999999999999999999999",
    "GUI_ORDER_CONFIRM": "no",
    "GUI_REFRESH_TIME": "2",
    "GUI_WT_YDTS": "yes",
    "SET_MCJG": "empty",
    "SET_MCSL": "empty",
    "SET_MRJG": "empty",
    "SET_MRSL": "empty",
    "SET_NOTIFY_DELAY": "1",
    "SET_POPUP_CJHB": "yes",
    # 'SET_TOP_MOST': 'yes',
    # 'SYS_ZCSX_ENABLE': 'yes' #    自动刷新资产数据 修改无效，会强制恢复为no！
}

user32 = ctypes.windll.user32


def capture_popup(time_interval=0.5):
    """弹窗截获"""

    def capture(time_interval):
        while True:
            # secs = random.uniform(remainder/2, remainder)
            # 若在休眠期间心跳印记没被修改，则刷新页面并修改心跳印记
            time.sleep(time_interval)

    threading.Thread(
        target=capture,
        kwargs={"time_interval": time_interval},
        name="capture_popup",
        daemon=True,
    ).start()


def normalize(string: str, to_dict=False):
    """标准化输出交易数据"""
    df = pd.read_csv(io.StringIO(string), sep="\t", dtype={"证券代码": str})
    df.drop(columns=[x for x in df.columns if x not in COLNAMES], inplace=True)
    df.columns = [COLNAMES.get(x) for x in df.columns]
    if "amount" in df.columns:
        df["ratio"] = (df["amount"] / df["amount"].sum()).round(2)
    return df.to_dict("list") if to_dict else df


def check_input_mode(h_edit, text="000001"):
    """获取 输入模式"""
    user32.SendMessageW(h_edit, 12, 0, text)
    time.sleep(0.3)
    return "WM" if user32.SendMessageW(h_edit, 14, 0, 0) == len(text) else "KB"


def find_one(keyword="股票交易系统", visible=True) -> int:
    """找到主窗口句柄
    keyword: str or list
    visible: {True, False, None}
    """
    if isinstance(keyword, str):
        keyword = [keyword]
    buf = ctypes.create_unicode_buffer(64)
    handle = ctypes.c_ulong()

    @ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)
    def callback(hwnd, lparam):
        user32.GetWindowTextW(hwnd, buf, 64)
        for s in keyword:
            if (
                s in buf.value
                and (visible is None or bool(user32.IsWindowVisible(hwnd))) is visible
            ):
                handle.value = hwnd
                return False
        return True

    user32.EnumWindows(callback)
    return handle.value


def curr_time():
    return time.strftime("%Y-%m-%d %X")  # backward


def get_today():
    return datetime.date.today()


def get_text(
    handle=None, h_parent=None, id_child=None, classname: str = None, num=32
) -> str:
    "获取控件文本内容"
    buf = ctypes.create_unicode_buffer(64)
    if isinstance(classname, str):
        handle: int = user32.FindWindowExW(h_parent, None, classname, None)
    if isinstance(handle, int):
        user32.SendMessageW(handle, Msg.WM_GETTEXT, num, buf)
    elif isinstance(id_child, int):
        user32.SendDlgItemMessageW(h_parent, id_child, Msg.WM_GETTEXT, num, buf)
    return buf.value.rstrip("%")


def check_config(folder=None, encoding="gb18030"):
    """检查客户端xiadan.ini文件是否符合木偶的要求"""
    with open("".join([folder or os.getcwd(), r"\xiadan.ini"]), encoding=encoding) as f:
        string = "".join(("[puppet]\n", f.read()))

    conf = configparser.ConfigParser()
    conf.read_string(string)
    section = conf["SYSTEM_SET"]

    print("推荐修改下列选项：")
    for key, value in OPTIONS.items():
        name, val = section.get(key).split(";")[3:5]
        if val != value:
            print(name, val, "改为", value, "\n")


def find_all():
    """获取全部已登录的客户端的根句柄"""

    def find(hwnd, extra):
        buf = ctypes.create_unicode_buffer(32)
        if user32.IsWindowVisible(hwnd):
            user32.GetWindowTextW(hwnd, buf, 32)
            if "交易系统" in buf.value:
                # h_acc = reduce(user32.GetDlgItem, (59392, 0, 1711), hwnd)
                # user32.SendMessageW(h_acc, 13, 32, buf)
                # extra.update({int(buf.value): hwnd})
                extra.append(hwnd)
        return True

    accounts = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, ctypes.py_object)
    user32.EnumChildWindows.argtypes = [HWND, WNDENUMPROC, ctypes.py_object]
    user32.EnumChildWindows(0, WNDENUMPROC(find), accounts)
    return accounts


def find_single_handle(h_dialog, keyword: str = "", classname="Static") -> int:
    from ctypes.wintypes import BOOL, HWND, LPARAM

    @ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)
    def callback(hwnd, lparam):
        user32.SendMessageW(hwnd, Msg.WM_GETTEXT, 64, buf)
        user32.GetClassNameW(hwnd, buf1, 64)
        if buf.value == keyword and buf1.value == classname:
            handle.value = hwnd
            return False
        return True

    buf = ctypes.create_unicode_buffer(64)
    buf1 = ctypes.create_unicode_buffer(64)
    handle = ctypes.c_ulong()
    user32.EnumChildWindows(h_dialog, callback)
    return handle.value


def go_to_top(
    h_root: int, timeout: float = 1.0, interval: float = 0.01, delay: float = 0.5
):
    """窗口置顶"""
    keyboard.send("alt")  # ! enables calls to SwitchToThisWindow
    time.sleep(0.5)
    if user32.SwitchToThisWindow(h_root, True) != 0:
        stop = int(timeout / interval)
        for _ in range(stop):
            if user32.GetForegroundWindow() == h_root:
                time.sleep(delay)
                return True
            time.sleep(0.5 if user32.IsIconic(h_root) else interval)  # ! DON'T REMOVE!


def image_to_string(
    image,
    token={
        "appId": "11645803",
        "apiKey": "RUcxdYj0mnvrohEz6MrEERqz",
        "secretKey": "4zRiYambxQPD1Z5HFh9VOoPXPK9AgBtZ",
    },
):
    if not isinstance(image, bytes):
        buf = io.BytesIO()
        image.save(buf, "png")
        image = buf.getvalue()
    return (
        __import__("aip")
        .AipOcr(**token)
        .basicGeneral(image)
        .get("words_result")[0]["words"]
    )


def locate_folder(name="Personal"):
    """Personal Recent"""
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
    )
    return winreg.QueryValueEx(key, name)[0]  # dir, type


def simulate_shortcuts(key1, key2=None):
    """
    VK_CONTROL = 17
    VK_ALT = 18
    VK_S = 83
    """
    KEYEVENTF_KEYUP = 2
    scan1 = user32.MapVirtualKeyW(key1, 0)
    user32.keybd_event(key1, scan1, 0, 0)
    if key2:
        scan2 = user32.MapVirtualKeyW(key2, 0)
        user32.keybd_event(key2, scan2, 0, 0)
        user32.keybd_event(key2, scan2, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(key1, scan1, KEYEVENTF_KEYUP, 0)


def click_key(self, keyCode, param=0):  # 单击按键
    if keyCode:
        user32.PostMessageW(self._page, Msg.WM_KEYDOWN, keyCode, param)
        user32.PostMessageW(self._page, Msg.WM_KEYUP, keyCode, param)
    return self


def get_rect(obj_handle):
    """locate the control"""
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(obj_handle, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def click_context_menu(text: str, x: int = 0, y: int = 0, delay: float = 0.5):
    """点选右键菜单"""
    user32.SetCursorPos(x, y)
    user32.mouse_event(Msg.MOUSEEVENTF_RIGHTDOWN | Msg.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    time.sleep(delay)
    keyboard.write(text)


def wait_for_popup(
    root: int, popup_title=None, timeout: float = 3.0, interval: float = 0.01
):
    buf = ctypes.create_unicode_buffer(64)
    start = time.time()
    while True:
        time.sleep(interval)  # DON'T REMOVE
        h_popup: int = user32.GetLastActivePopup(root)
        if h_popup != root:
            user32.SendMessageW(h_popup, Msg.WM_GETTEXT, 64, buf)
            if popup_title is None or buf.value in popup_title:
                return h_popup
        if time.time() - start >= timeout:
            break


def wait_for_view(handle: int, timeout: float = 3, interval: float = 0.1):
    for _ in range(int(timeout / interval)):
        if user32.IsWindowVisible(handle):
            return True
        time.sleep(interval)
    return False


def get_child_handle(
    h_parent=None, label=None, clsname=None, id_ctrl=None, visible=None
):
    """获取子窗口句柄

    h_parent: None 表示桌面
    """
    assert isinstance(h_parent, int), "Wrong data type."

    if isinstance(id_ctrl, int):
        return user32.GetDlgItem(h_parent, id_ctrl)

    hwndChildAfter = None
    group = []
    for _ in range(9):
        handle: int = user32.FindWindowExW(h_parent, hwndChildAfter, clsname, label)
        if visible is None or bool(user32.IsWindowVisible(handle)) is visible:
            return handle
        if handle in group:
            break
        group.append(handle)
        hwndChildAfter = handle


def click_button(h_button=None, h_dialog=None, label=None):
    if isinstance(h_dialog, int):
        h_button = get_child_handle(h_dialog, label, "Button")
    assert isinstance(h_button, int), TypeError("Must be a integer!", h_button)
    user32.PostMessageW(h_button, Msg.BM_CLICK, 0, 0)


def fill(text: str, h_edit: int):
    """填写字符串"""
    assert isinstance(text, str), TypeError("Must be a string!", text)
    assert isinstance(h_edit, int), TypeError("Must be a integer!", h_edit)
    user32.SendMessageW(h_edit, Msg.WM_SETTEXT, 0, text)


def export_data(path: str, root=None, label="另存为", location=False):
    if os.path.isfile(path):
        os.remove(path)

    if user32.IsIconic(root):
        print('如果返回空值，请先查一下"order"或"deal"，再查其他的。')

    h_popup = wait_for_popup(root, label)
    if wait_for_view(h_popup):
        if location:
            fill(path, get_child_handle(h_popup, clsname="Edit"))
            time.sleep(0.1)
        click_button(h_dialog=h_popup, label="保存(&S)")

    string = ""
    for _ in range(60):
        time.sleep(1)
        if os.path.isfile(path):
            try:
                with open(path) as f:  # try to acquire file lock and read file content
                    string = f.read()
            except Exception:
                continue
            else:
                break
    for _ in range(3):
        keyboard.send("esc")
    return string


def switch_combobox(index: int, handle: int):
    user32.SendMessageW(handle, Msg.CB_SETCURSEL, index, 0)
    time.sleep(0.5)
    user32.SendMessageW(
        user32.GetParent(handle),
        Msg.WM_COMMAND,
        Msg.CBN_SELCHANGE << 16 | user32.GetDlgCtrlID(handle),
        handle,
    )


def run_app(path: str):
    """运行应用程序"""
    assert os.path.exists(path), '客户端路径("%s")错误' % path
    # print('{} 正在尝试运行客户端("{}")...'.format(curr_time(), path))
    pid = subprocess.Popen(path).pid
    OpenProcess = ctypes.windll.kernel32.OpenProcess
    CloseHandle = ctypes.windll.kernel32.CloseHandle
    PROCESS_QUERY_INFORMATION = 1024
    h_proc = OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    ret = user32.WaitForInputIdle(h_proc, -1)
    CloseHandle(h_proc)

    if ret == 0:
        return pid


def closeStartupPopup(root: int):
    def enum_children(hwnd, results):
        try:
            if user32.IsWindowVisible(hwnd) and user32.IsWindowEnabled(hwnd):
                win32gui.EnumChildWindows(hwnd, handler, results)
        except Exception:
            return

    def handler(hwnd, results):
        if win32gui.GetClassName(hwnd) == "Static":
            results.append(hwnd)
            return False
        enum_children(hwnd, results)
        return len(results) == 0

    dialog = 0
    popups = []
    tid, _ = win32process.GetWindowThreadProcessId(root)
    windows = []
    win32gui.EnumThreadWindows(tid, lambda hwnd, l: l.append(hwnd), windows)
    for hwnd in windows:
        if not handler(hwnd, popups):
            break

    for ctrl in popups:
        text = get_text(ctrl)
        if "新股申购" in text or "营业部公告" in text:
            if "新股申购" in text:
                dialog = ctypes.windll.user32.GetParent(ctrl)
                if dialog > 0:
                    go_to_top(dialog)
                    keyboard.send("esc")
                    time.sleep(1)
                    closeStartupPopup(root)
            if "营业部公告" in text:
                dialog = ctypes.windll.user32.GetParent(ctrl)
                if dialog > 0:
                    go_to_top(dialog)
                    confirmButton = win32gui.FindWindowEx(dialog, None, "Button", "确定")
                    if confirmButton > 0:
                        win32gui.SendMessage(
                            dialog, win32con.WM_COMMAND, 1, confirmButton
                        )
                        time.sleep(1)
                        closeStartupPopup(root)
        time.sleep(1)


def ensureForegroundWindow(
    handle: int, timeout: float = 1, interval: float = 0.1, delay: float = 0.1
):
    win32gui.SetForegroundWindow(handle)
    stop = int(timeout / interval)
    for _ in range(stop):
        if user32.GetForegroundWindow() == handle:
            time.sleep(delay)
            return True
        time.sleep(interval)
