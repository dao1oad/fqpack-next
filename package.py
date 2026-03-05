import subprocess
import sys
import random
import string
import argparse
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description='Package the project')
    parser.add_argument('--password', action='store_true', 
                       help='Enable password protection')
    return parser.parse_args()

def main():
    args = parse_args()
    try:
        # 生成日期字符串
        with open('version.txt', 'r', encoding='utf-8') as f:
            date_str = f.readline().strip()

        # 生成32位随机密码（排除空格）
        chars = string.ascii_letters.replace(' ', '') + string.digits
        password = ''.join(random.choices(chars, k=32))

        # 定义文件名
        zip_name = f"freshquant-{date_str}.zip"
        temp_zip = "freshquant.zip"
        password_file = "freshquant.txt"

        # 清理旧文件
        for f in Path('.').glob('*.zip'):
            f.unlink(missing_ok=True)
        if Path(password_file).exists():
            Path(password_file).unlink()

        # 创建git归档
        subprocess.run(
            ["git", "archive", "-o", temp_zip, "main"],
            check=True,
            capture_output=True,
            text=True
        )

        if args.password:
            # 使用7-zip加密压缩
            subprocess.run(
                ["7z", "a", zip_name, temp_zip, f"-p{password}"],
                check=True,
                capture_output=True,
                text=True
            )

            # 保存密码
            with open(password_file, "w") as f:
                f.write(password)

            # 输出密码
            print(f"Password: {password}")
        else:
            # 直接重命名临时zip文件
            Path(temp_zip).rename(zip_name)

        # 清理临时文件
        Path(temp_zip).unlink(missing_ok=True)

        # 输出结果
        print(f"Created: {zip_name}")
        return 0

    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {e.cmd}\n错误信息: {e.stderr}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"发生未知错误: {str(e)}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
