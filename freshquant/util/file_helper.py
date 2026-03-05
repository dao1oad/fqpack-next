# -*- coding: utf-8 -*-
"""文件操作工具函数"""

import os


def write_file_with_mkdir(file_path: str, content: str, encoding: str = 'utf-8') -> None:
    """写入文件，如果目录不存在则自动创建

    Args:
        file_path: 文件路径
        content: 文件内容
        encoding: 文件编码，默认utf-8
    """
    dir_path = os.path.dirname(file_path)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path)
    with open(file_path, 'w', encoding=encoding) as f:
        f.write(content)
