import random
import string
import subprocess
from pathlib import Path

# 直接定义需要打包的文件列表
TO_ZIP_FILES = [
    "tdx/*.dll",
    "tdx/*.tn6",
    "kt/*.dll",
    "kt/*.AKL",
    "dzh/*.dll",
    "dzh/*.FNC",
    "jzt/*.dll",
    "jzt/*.fla",
    "jzt32/*.dll",
    "jzt32/*.fla",
    "version.txt",
    "README.md",
]

def main():
    # Read version from version.txt
    with open('version.txt', 'r', encoding='utf-8') as f:
        date_str = f.readline().strip()
    password = ''.join(random.choice(
        string.ascii_letters.replace(' ', '') + string.digits
    ) for _ in range(32))
    
    # Create output filename
    filename = f'fqchan01-{date_str}.zip'
    
    # Delete existing zip files
    for f in Path('.').glob('*.zip'):
        f.unlink()
    
    # Build 7z command
    cmd = ['7z', 'a', filename] + TO_ZIP_FILES
    print(cmd)
    
    # Run 7z command
    subprocess.run(cmd, check=True)
    
    # Print results
    print(filename)
    print(password)

if __name__ == '__main__':
    main()
