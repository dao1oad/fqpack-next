import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import chardet


def run_command(cmd, check=True, shell=True):
    """运行命令行命令"""
    print(f"执行命令: {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=shell, check=check, capture_output=True, text=False
        )
        if result.stdout:
            if isinstance(result.stdout, bytes):
                # 使用 chardet 检测编码
                if chardet:
                    detected = chardet.detect(result.stdout)
                    encoding = detected['encoding'] or 'utf-8'
                    confidence = detected['confidence'] or 0

                    if confidence > 0.7:  # 置信度较高时使用检测到的编码
                        try:
                            stdout_text = result.stdout.decode(encoding)
                        except UnicodeDecodeError:
                            # 如果检测的编码失败，尝试常见编码
                            try:
                                stdout_text = result.stdout.decode('utf-8')
                            except UnicodeDecodeError:
                                try:
                                    stdout_text = result.stdout.decode('gbk')
                                except UnicodeDecodeError:
                                    stdout_text = result.stdout.decode(
                                        'utf-8', errors='replace'
                                    )
                    else:
                        # 置信度较低时尝试常见编码
                        try:
                            stdout_text = result.stdout.decode('utf-8')
                        except UnicodeDecodeError:
                            try:
                                stdout_text = result.stdout.decode('gbk')
                            except UnicodeDecodeError:
                                stdout_text = result.stdout.decode(
                                    'utf-8', errors='replace'
                                )
                else:
                    # 没有 chardet 时使用常见编码尝试
                    try:
                        stdout_text = result.stdout.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            stdout_text = result.stdout.decode('gbk')
                        except UnicodeDecodeError:
                            stdout_text = result.stdout.decode(
                                'utf-8', errors='replace'
                            )
                print(f"输出: {stdout_text}")
            else:
                print(f"输出: {result.stdout}")
        return result
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {e}")
        if e.stderr:
            print(f"错误输出: {e.stderr}")
        if check:
            raise
        return e


def set_environment_variables():
    """设置环境变量"""
    print("设置环境变量...")

    # 设置PYTHONUTF8
    os.environ['PYTHONUTF8'] = '1'
    try:
        if sys.platform == 'win32':
            run_command('setx PYTHONUTF8 1', check=False)
        else:
            # 在Linux/macOS上设置环境变量
            run_command('echo "export PYTHONUTF8=1" >> ~/.bashrc', check=False)
    except Exception:
        print("设置PYTHONUTF8环境变量失败，继续执行...")

    # 设置PIP镜像和信任主机
    pip_vars = {
        'PIP_INDEX_URL': 'https://mirrors.aliyun.com/pypi/simple',
        'PIP_TRUSTED_HOST': 'mirrors.aliyun.com',
    }

    for var_name, var_value in pip_vars.items():
        os.environ[var_name] = var_value
        try:
            if sys.platform == 'win32':
                run_command(f'setx {var_name} {var_value}', check=False)
            else:
                run_command(
                    f'echo "export {var_name}={var_value}" >> ~/.bashrc', check=False
                )
        except Exception:
            print(f"设置{var_name}环境变量失败，继续执行...")


def install_packages():
    """安装Python包"""
    print("安装Python包...")

    # 安装TA-Lib
    run_command(
        f'msiexec /package {os.path.join("deps", "ta-lib-0.6.4-windows-x86_64.msi")} /quiet',
        check=False,
    )
    run_command('uv pip install ta-lib==0.6.4', check=False)

    # 安装pip包
    pip_packages = [
        'Cython',
        './morningglory/fqchan01/python',
        './morningglory/fqchan02/python',
        './morningglory/fqchan03/python',
        './morningglory/fqchan04/python',
        './morningglory/fqchan06/python',
        './morningglory/fqcopilot/python',
        './sunflower/xtquant',
        './sunflower/backtrader',
        './sunflower/pytdx',
        './sunflower/QUANTAXIS',
        '.',
        './morningglory/fqdagster',
        './morningglory/fqxtrade',
    ]

    for pkg in pip_packages:
        try:
            run_command(f'uv pip install {pkg}', check=False)
        except Exception:
            print(f"安装 {pkg} 失败，继续执行...")


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='FreshQuant 安装脚本 - Python版本')
    parser.add_argument('--skip-env', action='store_true', help='跳过环境变量设置')
    parser.add_argument('--skip-packages', action='store_true', help='跳过包安装')
    parser.add_argument('--skip-web', action='store_true', help='跳过web文件复制')
    parser.add_argument(
        '--nginx-dir',
        default='D:/fqpack/nginx/html',
        help='nginx html目录路径 (默认: D:/fqpack/nginx/html)',
    )
    parser.add_argument(
        '--web-source',
        default='morningglory/fqwebui/web',
        help='web源文件目录路径 (默认: morningglory/fqwebui/web)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='干运行模式，只显示将要执行的命令但不实际执行',
    )

    return parser.parse_args()


def copy_web_files(nginx_dir, web_source):
    """复制web文件到nginx目录"""
    print("检查并复制web文件到nginx目录...")

    nginx_html_dir = Path(nginx_dir)
    web_source_dir = Path(web_source)

    if not web_source_dir.exists():
        print(f"Web源目录 {web_source_dir} 不存在，跳过复制")
        return

    if nginx_html_dir.exists():
        print("目录存在，正在清空并复制web文件...")
        try:
            # 删除目标目录
            if nginx_html_dir.exists():
                shutil.rmtree(nginx_html_dir)

            # 创建目标目录
            nginx_html_dir.mkdir(parents=True, exist_ok=True)

            # 复制文件
            if web_source_dir.exists():
                shutil.copytree(web_source_dir, nginx_html_dir, dirs_exist_ok=True)
                print(f"Web文件已成功复制到 {nginx_html_dir}")
            else:
                print(f"Web源目录 {web_source_dir} 不存在")

        except Exception as e:
            print(f"复制web文件失败: {e}")
    else:
        print(f"{nginx_html_dir} 目录不存在，跳过web文件复制")


def main():
    """主函数"""
    args = parse_arguments()

    print("开始执行FreshQuant安装脚本...")
    print(f"工作目录: {os.getcwd()}")

    if args.dry_run:
        print("干运行模式 - 只显示命令，不实际执行")

    try:
        if not args.skip_env:
            set_environment_variables()
        else:
            print("跳过环境变量设置")

        if not args.skip_packages:
            install_packages()
        else:
            print("跳过包安装")

        if not args.skip_web:
            copy_web_files(args.nginx_dir, args.web_source)
        else:
            print("跳过web文件复制")

        print("安装完成！")

    except Exception as e:
        print(f"安装过程中出现错误: {e}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
