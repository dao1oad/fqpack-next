import argparse
import os
import shutil
import subprocess
import time


def decode(line: bytes):
    try:
        for encoding in ['utf-8', 'gbk', 'gb2312']:
            try:
                return line.decode(encoding)
            except:
                pass
    except:
        pass
    return ""


def run(command, python, log_file_path, module, envs):
    if command is None:
        if python is None:
            print("python interpretor is not set")
            exit(1)
        if module is None:
            print("module name is not set")
            exit(1)
    if log_file_path is None:
        print("log file path is not set")
        exit(1)

    env = os.environ.copy()
    if envs is not None:
        for item in envs:
            env_name, env_value = item.split("=")
            env[env_name] = env_value

    max_file_size_in_mb = 10

    logfile = open(log_file_path, mode='a', newline='')
    lastCheckTime = None
    process = None
    if command is not None:
        process = subprocess.Popen(
            command.split(" "),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
    else:
        process = subprocess.Popen(
            [python, "-m", module],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
    for line in iter(process.stdout.readline, b''):
        log_line = decode(line)
        logfile.write(log_line)
        logfile.flush()
        print(log_line, end="")
        # check log file size
        if lastCheckTime is None or time.time() - lastCheckTime > 60:
            file_size_in_mb = os.path.getsize(log_file_path) / (1024 * 1024)
            if file_size_in_mb > max_file_size_in_mb:
                logfile.close()
                timestamp = time.strftime("%Y%m%d%H%M%S")
                rotate_log_file_path = log_file_path.replace(
                    ".log", f"_{timestamp}.log"
                )
                shutil.move(log_file_path, rotate_log_file_path)
                logfile = open(log_file_path, "a")
            lastCheckTime = time.time()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="freshquant run")
    parser.add_argument(
        "-c",
        "--command",
        type=str,
        required=False,
        help="command",
    )
    parser.add_argument(
        "-m",
        "--module",
        type=str,
        required=False,
        help="module name",
    )
    parser.add_argument(
        "-l",
        "--logfile",
        type=str,
        required=False,
        help="log file path",
    )
    parser.add_argument(
        "-p",
        "--python",
        type=str,
        required=False,
        help="python path",
    )
    # 添加设置环境变量的参数，可以添加多个环境变量
    parser.add_argument(
        "-e",
        "--env",
        type=str,
        required=False,
        help="env",
        action="append",
    )
    args = parser.parse_args()
    run(args.command, args.python, args.logfile, args.module, args.env)
