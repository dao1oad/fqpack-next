import subprocess
import psutil
import os
from freshquant.carnation.param import queryParam


def check_process(process_name):
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] == process_name:
            return True
    return False

def ensure_xt_mini_qmt():
    if not check_process('XtMiniQmt.exe'):
        path = os.path.dirname(queryParam("xtquant.path", ""))
        subprocess.Popen(os.path.join(path, 'bin.x64', 'XtItClient.exe'))
    else:
        print("XtMiniQmt.exe已经在运行了")

if __name__ == "__main__":
    ensure_xt_mini_qmt()
