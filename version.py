import time
import re
from pathlib import Path

def update_version():
    # 获取当前日期作为版本号
    current_time = time.localtime()
    version = f"{current_time.tm_year}.{current_time.tm_mon}.{current_time.tm_mday}"
    
    # 写入version.txt
    with open('version.txt', 'w') as f:
        f.write(version)
    
    # 更新pyproject.toml
    pyproject_toml = Path('pyproject.toml')
    if pyproject_toml.exists():
        content = pyproject_toml.read_text(encoding='utf-8')
        content = re.sub(r'version = ".*?"', f'version = "{version}"', content)
        pyproject_toml.write_text(content, encoding='utf-8')

if __name__ == '__main__':
    update_version()
