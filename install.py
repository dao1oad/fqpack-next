import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import chardet
except ImportError:
    chardet = None


def run_command(cmd, check=True, shell=True):
    print(f"执行命令: {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=shell, check=check, capture_output=True, text=False
        )
        if result.stdout:
            if isinstance(result.stdout, bytes):
                if chardet:
                    detected = chardet.detect(result.stdout)
                    encoding = detected["encoding"] or "utf-8"
                    confidence = detected["confidence"] or 0

                    if confidence > 0.7:
                        try:
                            stdout_text = result.stdout.decode(encoding)
                        except UnicodeDecodeError:
                            try:
                                stdout_text = result.stdout.decode("utf-8")
                            except UnicodeDecodeError:
                                stdout_text = result.stdout.decode(
                                    "utf-8", errors="replace"
                                )
                    else:
                        try:
                            stdout_text = result.stdout.decode("utf-8")
                        except UnicodeDecodeError:
                            try:
                                stdout_text = result.stdout.decode("gbk")
                            except UnicodeDecodeError:
                                stdout_text = result.stdout.decode(
                                    "utf-8", errors="replace"
                                )
                else:
                    try:
                        stdout_text = result.stdout.decode("utf-8")
                    except UnicodeDecodeError:
                        try:
                            stdout_text = result.stdout.decode("gbk")
                        except UnicodeDecodeError:
                            stdout_text = result.stdout.decode("utf-8", errors="replace")
                print(f"输出: {stdout_text}")
            else:
                print(f"输出: {result.stdout}")
        return result
    except subprocess.CalledProcessError as exc:
        print(f"命令执行失败: {exc}")
        if exc.stderr:
            try:
                stderr_text = exc.stderr.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    stderr_text = exc.stderr.decode("gbk")
                except UnicodeDecodeError:
                    stderr_text = exc.stderr.decode("utf-8", errors="replace")
            print(f"错误输出: {stderr_text}")
        if check:
            raise
        return exc


def set_environment_variables():
    print("设置环境变量...")
    os.environ["PYTHONUTF8"] = "1"

    pip_vars = {
        "PIP_INDEX_URL": "https://mirrors.aliyun.com/pypi/simple",
        "PIP_TRUSTED_HOST": "mirrors.aliyun.com",
    }

    for var_name, var_value in pip_vars.items():
        os.environ[var_name] = var_value
        try:
            if sys.platform == "win32":
                run_command(f"setx {var_name} {var_value}", check=False)
            else:
                run_command(
                    f'echo "export {var_name}={var_value}" >> ~/.bashrc', check=False
                )
        except Exception:
            print(f"设置 {var_name} 失败，继续执行...")


def install_runtime_prerequisites():
    print("安装运行时前置依赖...")
    print("当前项目依赖已通过 wheel 提供 TA-Lib，跳过宿主机原生前置安装")


def build_project_extensions():
    print("构建项目扩展...")
    run_command(f'"{sys.executable}" script/build_extensions.py --target fullcalc')


def parse_arguments():
    parser = argparse.ArgumentParser(description="FreshQuant 安装脚本 - Python 3.12")
    parser.add_argument("--skip-env", action="store_true", help="跳过环境变量设置")
    parser.add_argument("--skip-packages", action="store_true", help="跳过运行时前置依赖安装")
    parser.add_argument("--skip-web", action="store_true", help="跳过 web 文件复制")
    parser.add_argument(
        "--runtime-prereqs-only",
        action="store_true",
        help="只安装运行时前置依赖",
    )
    parser.add_argument(
        "--nginx-dir",
        default="D:/fqpack/nginx/html",
        help="nginx html 目录路径 (默认: D:/fqpack/nginx/html)",
    )
    parser.add_argument(
        "--web-source",
        default="morningglory/fqwebui/web",
        help="web 源目录路径 (默认: morningglory/fqwebui/web)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干运行模式，仅显示步骤信息但不真正执行",
    )
    return parser.parse_args()


def copy_web_files(nginx_dir, web_source):
    print("检查并复制 web 文件到 nginx 目录...")

    nginx_html_dir = Path(nginx_dir)
    web_source_dir = Path(web_source)

    if not web_source_dir.exists():
        print(f"Web 源目录 {web_source_dir} 不存在，跳过复制")
        return

    if nginx_html_dir.exists():
        print("目录存在，正在清空并复制 web 文件...")
        try:
            shutil.rmtree(nginx_html_dir)
            nginx_html_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(web_source_dir, nginx_html_dir, dirs_exist_ok=True)
            print(f"Web 文件已成功复制到 {nginx_html_dir}")
        except Exception as exc:
            print(f"复制 web 文件失败: {exc}")
    else:
        print(f"{nginx_html_dir} 目录不存在，跳过 web 文件复制")


def main():
    args = parse_arguments()

    print("开始执行 FreshQuant 安装脚本...")
    print(f"工作目录: {os.getcwd()}")

    if args.dry_run:
        print("当前为 dry-run，仅输出步骤信息")

    try:
        if not args.skip_env:
            set_environment_variables()
        else:
            print("跳过环境变量设置")

        if not args.skip_packages:
            install_runtime_prerequisites()
        else:
            print("跳过运行时前置依赖安装")

        if args.runtime_prereqs_only:
            print("仅安装运行时前置依赖，提前结束")
            return 0

        if not args.skip_packages:
            build_project_extensions()

        if not args.skip_web:
            copy_web_files(args.nginx_dir, args.web_source)
        else:
            print("跳过 web 文件复制")

        print("安装完成")
    except Exception as exc:
        print(f"安装过程中出现错误: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
