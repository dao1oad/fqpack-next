# -*- coding: utf-8 -*-

from setuptools import setup

from fqpuppet import __version__ as VERSION

REQUIRED = [
    'baidu-aip',
    'pydirectinput',
    'keyboard',
    'pyperclip',
    'pywin32',
    'pywinauto',
]
REQUIRES_PYTHON = '>=3.8.0'

setup(
    name='fqpuppet',
    version=VERSION,
    description=("一个用来交易沪深A股的应用编程接口"),
    license='MIT',
    author='freshtech2021',
    author_email='1106628276@qq.com',
    url='https://github.com/freshtech2021/fqpuppet',
    keywords="stock TraderApi Quant",
    python_requires=REQUIRES_PYTHON,
    install_requires=REQUIRED,
    packages=['fqpuppet'],
    # test_suite='tests',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Win32 (MS Windows)',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
)
