import pyautogui
import subprocess
import time
from loguru import logger as log


def find_window(title='国金证券QMT交易端'):
    windows = pyautogui.getWindowsWithTitle(title)
    if len(windows) == 0:
        return None
    return windows[0]


def start(acc, pwd, command=r'D:\qmtmoni\bin.x64\XtItClient.exe'):
    qmt_windows = find_window(acc)
    if not qmt_windows:
        subprocess.Popen(command)
        time.sleep(10)
        qmt_windows = find_window()
        qmt_windows.activate()
        time.sleep(2)
        pyautogui.press('tab')
        time.sleep(2)
        pyautogui.typewrite(pwd)
        time.sleep(1)
        pyautogui.press('enter')
    qmt_windows.activate()


def close():
    """
    如启动与关闭间隔时间过短，会导致程序异常检测，忽略即可
    :return:
    """
    qmt_windows = find_window()
    if qmt_windows:
        qmt_windows.activate()
        time.sleep(2)
        qmt_windows.close()
        time.sleep(2)
        pyautogui.press('enter')
        log.debug("QMT已自动关闭，如不需要关闭，请禁用close()方法")

    else:
        log.error("没有找到QMT程序")


if __name__ == '__main__':
    account, password = "111", "111"
    start(account, password)
    time.sleep(10)
    print("执行完成，我要关闭了")
    close()
