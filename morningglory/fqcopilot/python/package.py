import random
import string
import subprocess
from pathlib import Path

# 直接定义需要打包的文件列表
TO_ZIP_FILES = [
    "dist/*.whl",
]

def main():
    # Generate date string and random password
    with open('../version.txt', 'r', encoding='utf-8') as f:
        date_str = f.readline().strip()
    password = ''.join(random.choice(
        string.ascii_letters.replace(' ', '') + string.digits
    ) for _ in range(32))
    
    # Create output filename
    filename = f'fqcopilot-python-{date_str}.zip'
    
    # Delete existing zip files
    for f in Path('.').glob('*.zip'):
        f.unlink()
    
    # Build 7z command
    cmd = ['C:/Program Files/7-Zip/7z', 'a', filename] + TO_ZIP_FILES
    print(cmd)
    
    # Run 7z command
    subprocess.run(cmd, check=True)
    
    # Print results
    print(filename)
    print(password)

if __name__ == '__main__':
    main()
