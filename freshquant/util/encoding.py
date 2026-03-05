# -*- coding: utf-8 -*-

import chardet


def detectEncoding(file_path):
    with open(file_path, 'rb') as f:
        result = chardet.detect(f.read(1024 * 1024))
    return result['encoding']
