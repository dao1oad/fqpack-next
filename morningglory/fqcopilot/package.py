import os
import random
import string
import subprocess
from pathlib import Path

def generate_password(length=32):
    """生成随机密码"""
    chars = string.ascii_letters.replace(' ', '') + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def create_zip(filename, files):
    """创建带密码的zip文件"""
    if Path(filename).exists():
        os.remove(filename)
    
    # 使用7z命令行工具创建zip
    cmd = ['C:/Program Files/7-Zip/7z', 'a', filename] + files
    subprocess.run(cmd, check=True)

def main():
    # 删除当前目录下的所有.zip文件
    for file in Path('.').glob('*.zip'):
        file.unlink()
    
    # 生成日期字符串
    with open('version.txt', 'r', encoding='utf-8') as f:
        date_str = f.readline().strip()
    
    # 生成随机密码
    password = generate_password()
    
    # 设置zip文件名
    filename = f'fqcopilot-{date_str}.zip'
    
    # 读取要打包的文件列表
    with open('package_files.txt', 'r', encoding='utf-8') as f:
        files = [line.strip() for line in f if line.strip()]
    
    # 创建zip文件
    create_zip(filename, files)
    
    # 将密码写入文件
    with open('fqcopilot.txt', 'w', encoding='utf-8') as f:
        f.write(password)
    
    # 输出结果
    print(f'Created: {filename}')
    print(f'Password: {password}')

if __name__ == '__main__':
    main()
