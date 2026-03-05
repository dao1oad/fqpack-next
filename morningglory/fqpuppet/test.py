# -*- coding: utf-8 -*-
"木偶测试文件，请直接在命令行执行 python puppet\test.py"

if __name__ == '__main__':

    import platform
    import time

    import fqpuppet

    print('\n{}\nPython Version: {}'.format(
        platform.platform(), platform.python_version()))
    print('默认使用百度云OCR进行验证码识别')
    print("\n注意！必须将client_path的值修改为你自己的交易客户端路径！\n")

    bdy = {
        'appId': '',
        'apiKey': '',
        'secretKey': ''
    } # 百度云 OCR https://cloud.baidu.com/product/ocr

    accinfos = {
        'account_no': '198800',
        'password': '123456',
        'comm_pwd': True,  # 模拟交易端必须为True
        'client_path': r'你的交易客户端目录\xiadan.exe'
    }

    # 自动登录交易客户端
    # acc = puppet.login(accinfos)
    # acc = puppet.Account(accinfos)

    # 绑定已经登录的交易客户端，旧版需要传入 title=''
    acc = fqpuppet.Client()

    print(acc.query())
    r = acc.buy('510500', 4.688, 100)
    print(r)
    r = acc.query('order')
    print(r)
    time.sleep(5)
    r = acc.cancel_buy('510550')
    print(r)
