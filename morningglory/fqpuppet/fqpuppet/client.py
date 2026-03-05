# -*- coding: utf-8 -*-
"""
扯线木偶界面自动化应用编程接口 (Puppet UIAutomation API)
"""
__author__ = "Peony (https://github.com/freshtech2021)"
__project__ = "Puppet"
__version__ = "0.0.4"
__license__ = "MIT"

import ctypes
import io
import random
import re
import threading
import time
from functools import lru_cache, partial, reduce

from . import util

user32 = ctypes.windll.user32


def login(accinfos=None, **kwargs):
    return Account(accinfos, **kwargs)


class Ths:

    NODE = {
        "buy": 161,
        "sell": 162,
        "cancel": 163,
        "cancel_all": 163,
        "cancel_buy": 163,
        "cancel_sell": 163,
        "undone": 163,
        "order": 168,
        "trade": 512,
        "buy2": 512,
        "sell2": 512,
        "mkt": 165,
        "summary": 165,
        "balance": 165,
        "cash": 165,
        "position": 165,
        "account": 165,
        "equity": 165,
        "assets": 165,
        "deal": 167,
        "historical_deal": 510,
        "delivery_order": 176,
        "new": 554,
        "purchase_new": 554,
        "reverse_repo": 717,
        "purchase": 433,
        "redeem": 434,
        "margin": 454,  # 融资融券、保证金
        "margin_pos": 454,
        "buy_on_margin": 448,  # 融资买入
        "sell_for_repayment": 449,  # 卖券还款
        "discount": 466,  # 可充抵保证金证券折扣率
        "margin_cancel_all": 465,
        "margin_cancel_buy": 465,
        "margin_cancel_sell": 465,
        "batch": 5170,
        "bingo": 1070,
    }
    INIT = ("cancel", "deal", "order", "buy", "sell")
    LOGIN = (1011, 1012, 1001, 1003, 1499)
    ACCOUNT = (59392, 0, 1711)
    ACCNAME = (59392, 0, 2322)
    MKT = (59392, 0, 1003)
    TABLE = (1047, 200, 1047)
    SUMMARY_ = ("summary", "margin")
    SUMMARY = (
        ("cash", 1016),
        ("frozen", 1013),
        ("balance", 1012),
        ("market_value", 1014),
        ("equity", 1015),
        ("position_pct", 1019),
    )
    # symbol, price, max_qty, quantity, quote
    BUY = (1032, 1033, 1034, 0, 1018)
    SELL = (1032, 1033, 1034, 0, 1038)
    REVERSE_REPO = (1032, 1033, 1034, 0, 1018)
    BUY2 = (3451, 1032, 1541, 1033, 1018, 1034)
    SELL2 = (3453, 1035, 1542, 1058, 1019, 1039)
    CANCEL = (3348,)
    PURCHASE = (1032, 1034)
    REDEEM = (1032, 1034)
    PAGE = 59648, 59649
    FRESH = 32790
    QUOTE = 1024
    MARGIN = (
        ("id", 10001),
        ("guarantee_rate", 10003),
        ("margin", 10006),
        ("cash", 10008),
        ("frozen", 10009),
        ("balance", 10007),
        ("market_value", 10010),
        ("equity", 10032),
        ("debts", 10005),
        ("assets", 10004),
    )
    BUTTON = {
        "cancel_all": "全撤(Z /)",
        "cancel_buy": "撤买(X)",
        "cancel_sell": "撤卖(C)",
        "cancel": "撤单",
        "buy": "买入[B]",
        "sell": "卖出[S]",
        "reverse_repo": "确定",
        "margin_cancel_all": "全撤(Z /)",
        "margin_cancel_buy": "撤买(X)",
        "margin_cancel_sell": "撤卖(C)",
    }
    ERROR = ["无可撤委托", "提交失败", "当前时间不允许委托"]
    WAY = {
        0: "LIMIT              限价委托 沪深",
        1: "BEST5_OR_CANCEL    最优五档即时成交剩余撤销 沪深",
        2: "BEST5_OR_LIMIT     最优五档即时成交剩余转限价 上海",
        20: "REVERSE_BEST_LIMIT 对方最优价格 深圳",
        3: "FORWARD_BEST       本方最优价格 深圳",
        4: "BEST_OR_CANCEL     即时成交剩余撤销 深圳",
        5: "ALL_OR_CANCEL      全额成交或撤销 深圳",
    }


class Account:
    """Puppet Trading Account API"""

    def __init__(
        self,
        accinfos=None,
        enable_heartbeat=True,
        to_dict=False,
        dirname="",
        keyboard=True,
        title=None,
        **kwargs,
    ):
        self.accinfos = accinfos
        self.enable_heartbeat = enable_heartbeat
        self.to_dict = to_dict
        self.dirname = dirname
        self.keyboard = keyboard
        self.title = title
        self.kwargs = kwargs
        self.location = True if dirname else False

        self._post_init()

    def _post_init(self):
        self.heartbeat_stamp = time.time()
        self.root = 0
        self.ctx = Ths
        self.filename = "{}\\table.xls".format(self.dirname or util.locate_folder())
        self.loginfile = "{}\\login.json".format(self.dirname or util.locate_folder())
        self.dxinput = __import__("pydirectinput")

        self.cancel_all = partial(self.cancel, action="cancel_all")
        self.cancel_buy = partial(self.cancel, action="cancel_buy")
        self.cancel_sell = partial(self.cancel, action="cancel_sell")
        self.cancel_buy.__doc__ = "撤销指定证券代码的买单"
        self.cancel_sell.__doc__ = "撤销指定证券代码的卖单"
        self.query = self.export_data if not self.kwargs.get("copy") else self.copy_data

        if self.accinfos:
            self.login(**self.accinfos)
        elif isinstance(self.title, str):
            self.bind(self.title, dirname=self.dirname)

    @property
    def status(self):
        return user32.IsWindowVisible(self.root)

    def login(self, account_no: str = "", password: str = "", **kwargs):
        from PIL.ImageGrab import grab

        pid = util.run_app(kwargs["client_path"])
        self.root = util.find_one(visible=False)
        id_proc = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(self.root, ctypes.byref(id_proc))
        if id_proc.value == pid:
            self.h_login = util.wait_for_popup(self.root)
            if util.go_to_top(self.h_login) and util.wait_for_view(self.h_login):
                time.sleep(1)  # ! WARNING: DON'T DELETE! Wait for focus.
                util.keyboard.send("up")  # * Jump to the account_no
                time.sleep(0.1)  # ! WARNING: DON'T DELETE! Wait for focus.
                [util.keyboard.send("backspace") for _ in range(16)]

                # TODO: 后续支持4K等分辨率
                captcha = kwargs.get("comm_pwd") or util.image_to_string(
                    grab(util.get_rect(user32.GetDlgItem(self.h_login, 1499)))
                )
                for text in (account_no, password, captcha):
                    util.keyboard.write(text)
                    time.sleep(0.5)  # ! Old processor should ask for more.
                    util.keyboard.send("enter")
                    time.sleep(0.02)

                print("{} 正在登录交易服务器...".format(util.curr_time()))

                if util.wait_for_view(self.root, timeout=9):
                    kwargs.update(account_no=account_no, password=password)
                    self.infos = kwargs
                    print("{} 已登入交易服务器。".format(util.curr_time()))
                    self.init()

        return {
            "puppet": "{} {}".format(
                util.curr_time(), "准备就绪！" if self.status else "登录失败！"
            )
        }

    def exit(self):
        "退出系统并关闭程序"
        if self.root:
            user32.PostMessageW(self.root, util.Msg.WM_CLOSE, 0, 0)
        return {"puppet": "{} 客户端已退出!".format(util.curr_time())}

    def fill_and_submit(self, *args, delay=0.1, label=""):
        util.ensureForegroundWindow(self._page)
        for text, handle in zip(args, self._handles):
            util.fill(str(text), handle)
            if delay:
                for _ in range(9):
                    max_qty = util.get_text(self._handles[-1])
                    if max_qty not in (""):
                        break
                    time.sleep(delay)
        time.sleep(0.1)
        util.click_button(h_dialog=self._page, label=label)
        return self

    @property
    def accno(self):
        return util.get_text(reduce(user32.GetDlgItem, self.ctx.ACCOUNT, self.root))

    def trade(self, action: str, *args) -> dict:
        """下单

        委托策略(注意个别券商自定义索引)
        0 LIMIT              限价委托 沪深
        1 BEST5_OR_CANCEL    最优五档即时成交剩余撤销 上海
        2 BEST5_OR_LIMIT     最优五档即时成交剩余转限价 上海
        1 REVERSE_BEST_LIMIT 对方最优价格 深圳
        2 FORWARD_BEST       本方最优价格 深圳
        3 BEST_OR_CANCEL     即时成交剩余撤销 深圳
        4 BEST5_OR_CANCEL    最优五档即时成交剩余撤销 深圳
        5 ALL_OR_CANCEL      全额成交或撤销 深圳
        """
        if util.go_to_top(self.root):
            self.switch(action)
            symbol, price, quantity = args
            ctrl = user32.GetDlgItem(self._page, 0x408)
            util.ensureForegroundWindow(ctrl)
            util.keyboard.write(str(symbol))
            util.keyboard.send("enter")
            h_name = user32.GetDlgItem(self._page, 0x40C)
            # 等待检索市场归属和中文简称完成
            for _ in range(99):
                time.sleep(0.1)
                if util.get_text(h_name) != "":
                    break
            time.sleep(0.1)
            ctrl = user32.GetDlgItem(self._page, 0x409)
            util.ensureForegroundWindow(ctrl)
            [util.keyboard.send("backspace") for _ in range(16)]
            time.sleep(0.1)
            util.keyboard.write("%.2f" % price)
            util.keyboard.send("enter")
            if action == "buy":
                # 确认实际可买数量
                h_name = user32.GetDlgItem(self._page, 0x3FA)
                for _ in range(99):
                    time.sleep(0.1)
                    num = util.get_text(h_name)
                    if num != "":
                        num = int(num)
                        if num == 0:
                            # 不能再买了
                            return {"puppet": (-1, "金额不足")}
                        elif num < quantity:
                            quantity = num
                        break
            elif action == "sell":
                # 确认可以卖的数量
                h_name = user32.GetDlgItem(self._page, 0x40E)
                for _ in range(99):
                    time.sleep(0.1)
                    num = util.get_text(h_name)
                    if num != "":
                        num = int(num)
                        if num == 0:
                            # 不能再卖了
                            return {"puppet": (-1, "数量不足")}
                        elif num < quantity:
                            quantity = num
                        break
            time.sleep(0.1)
            ctrl = user32.GetDlgItem(self._page, 0x40A)
            util.ensureForegroundWindow(ctrl)
            util.keyboard.write(str(quantity))
            util.keyboard.send("enter")
            time.sleep(0.1)
            return self.answer()

    def buy(self, symbol: str, price, quantity: int) -> dict:
        return self.trade("buy", symbol, price, quantity)

    def sell(self, symbol: str, price, quantity: int) -> dict:
        return self.trade("sell", symbol, price, quantity)

    def reverse_repo(self, symbol: str, price: float, quantity: int, delay=0.2) -> dict:
        """逆回购 R-001 SZ '131810'; GC001 SH '204001'"""
        return self.trade("reverse_repo", symbol, price, quantity, delay=delay)

    def cancel(self, symbol: str = None, action: str = "cancel") -> dict:
        """撤销指定证券代码的委托单。两融户需要在action参数加上前缀 margin_
        2020-12-08 重构撤单代码
        """
        util.go_to_top(self.root)
        self.switch("cancel")

        if isinstance(symbol, str):
            h_edit = util.get_child_handle(
                self._page, id_ctrl=3348, clsname="Edit", visible=None
            )
            util.fill(symbol, h_edit)
            h_button = util.get_child_handle(self._page, label="撤单", clsname="Button")

            for _ in range(9):
                if user32.SendMessageW(h_edit, util.Msg.WM_GETTEXTLENGTH, 0, 0) == len(
                    symbol
                ):
                    util.click_button(h_dialog=self._page, label="查询代码")
                    break
                time.sleep(0.05)
            for _ in range(9):
                if user32.IsWindowEnabled(h_button):  # 撤单按钮是否可用
                    break
                time.sleep(0.05)

        util.click_button(h_dialog=self._page, label=self.ctx.BUTTON[action])
        return self.answer()

    def purchase_new(self):
        "新股申购"

        def func(ipo):
            symbol = ipo.get("新股代码") or ipo.get("证券代码")
            price = ipo.get("申购价格") or ipo.get("发行价格")
            orders = self.query("order")
            had = [order["证券代码"] for order in orders]
            if symbol in had:
                r = (0, "%s 已经申购" % symbol)
            elif symbol not in had:
                r = self.buy(symbol, price, 0)
            else:
                r = (0, "不可预测的申购错误")
            return r

        target = self.query("new")
        if target:
            return {"puppet": [func(ipo) for ipo in target]}

    def fund_purchase(self, symbol: str, amount: int):
        """基金申购"""
        return self.trade("purchase", symbol, amount)

    def fund_redeem(self, symbol: str, share: int):
        """基金赎回"""
        return self.trade("redeem", symbol, share)

    def buy_on_margin(self, symbol: str, price, quantity: int) -> dict:
        """融资买入"""
        return self.trade("buy_on_margin", symbol, price, quantity)

    def sell_for_repayment(self, symbol: str, price, quantity: int) -> dict:
        """卖券还款"""
        return self.trade("sell_for_repayment", symbol, price, quantity)

    "Development"

    def __repr__(self):
        status = "on-line" if self.status else "off-line"
        return "<Puppet %s(%s | %s)>" % (self.__class__.__name__, __version__, status)

    def bind(self, arg="", dirname: str = "", **kwargs):
        """ "
        :arg: 客户端的标题或根句柄
        :mkt: 交易市场的索引值
        """
        if arg == "":
            self.root = util.find_one()
        elif "title" in kwargs or isinstance(arg, str):
            self.root = user32.FindWindowW(0, kwargs.get("title") or (arg or "股票交易系统"))
        elif "root" in kwargs or isinstance(arg, int):
            self.root = kwargs.get("root") or arg
        if self.visible(self.root):
            self.birthtime = time.ctime()
            self.title = util.get_text(self.root)
            self.idx = 0
            self.init()
            self.filename = "{}\\table.xls".format(dirname or util.locate_folder())
            self.location = True if dirname else False
            return {"puppet": (0, "{} 木偶准备就绪！".format(util.curr_time()))}
        return {"puppet": (-1, "标题错误或者客户端失联")}

    def visible(self, hwnd=None, times=0):
        for _ in range(times or 1):
            val = user32.IsWindowVisible(hwnd or self.root)
            if val:
                return True
            elif times > 0:
                time.sleep(0.5)
        return False

    def switch(self, name, delay=1):
        self.heartbeat_stamp = time.time()
        assert self.visible(), "客户端已关闭或账户已登出"
        node = name if isinstance(name, int) else self.ctx.NODE[name]
        if user32.SendMessageW(self.root, util.Msg.WM_COMMAND, 0x2000 << 16 | node, 0):
            self._page = reduce(user32.GetDlgItem, self.ctx.PAGE, self.root)
            time.sleep(delay)
            return True

    def init(self):
        if self.keyboard:

            def func(*args, **kwargs):
                util.ensureForegroundWindow(self._page)
                for text in args:
                    util.keyboard.write("{}\n".format(text))
                return self

            self.fill_and_submit = func

        time.sleep(5)  # 多等一会儿，等待窗口初始化完成

        util.closeStartupPopup(self.root)  # 关闭启动后的软件弹窗

        self.mkt = (
            (0, 1) if util.get_text(self.get_handle("mkt")).startswith("上海") else (1, 0)
        )
        # user32.ShowOwnedPopups(self.root, False)

        # 写入 table.xls 的绝对路径
        self.location = True if self.dirname else False

        # self.make_heartbeat()

        print("{} 木偶准备就绪！".format(util.curr_time()))
        return self

    def export_data(self, category: str = "summary") -> dict:
        """export latest trading data

        category: 'summary', 'position', 'order', 'deal', 'undone', 'historical_deal'
        'delivery_order', 'new', 'bingo', 'margin', 'margin_pos', 'discount' 其中之一
        """
        print("Querying {} on-line...".format(category))

        rtn = util.pd.Series({"puppet": False})
        if util.go_to_top(self.root):
            self.switch(category)
            _l, ypos, xpos, _b = util.get_rect(self.root)

            xpos -= 166
            ypos += 166 if category in self.ctx.SUMMARY_ else 332

            if category in self.ctx.SUMMARY_:
                time.sleep(1)  # temporary
                rtn = dict(
                    (x, float(util.get_text(h_parent=self._page, id_child=y)))
                    for x, y in getattr(self.ctx, category.upper())
                )
                rtn.update(login_id=self.accno, token=id(self))
            else:
                time.sleep(0.5)
                util.click_context_menu("s", xpos, ypos)
                string = util.export_data(
                    self.filename, self.root, location=self.location
                )
                if string != "":
                    rtn = util.normalize(string, self.to_dict)
        return rtn

    def copy_data(self, category: str = "summary"):
        """复制CVirtualGridCtrl|Custom<n>的文本数据到剪贴板
        广发
        """
        globals().update(pyperclip=__import__("pyperclip"))
        pyperclip.copy("")

        self.switch(category)
        user32.PostMessageW(
            self.get_handle(category), util.Msg.WM_COMMAND, util.Msg.COPY, 0
        )

        for _ in range(9):
            # 关闭验证码弹窗
            print("Removing copy protection...")
            time.sleep(0.1)  # have to
            h_popup = util.wait_for_popup(self.root)
            if util.wait_for_view(h_popup):
                text = self.verify(self.grab(h_popup))
                h_edit = user32.FindWindowExW(h_popup, None, "Edit", "")
                util.fill(text, h_edit)
                util.click_button(h_dialog=h_popup, label="确定")
                time.sleep(0.3)  # have to wait!
                break

        _replace = {"参考市值": "市值", "最新市值": "市值"}  # 兼容国金/平安"最新市值"、银河“参考市值”。
        ret = pyperclip.paste().splitlines()

        # 数据格式化
        temp = (x.split("\t") for x in ret)
        header = next(temp)
        for tag, value in _replace.items():
            if tag in header:
                header.insert(header.index(tag), value)
                header.remove(tag)
        return [dict(zip(header, x)) for x in temp]

    @lru_cache()
    def get_handle(self, action: str):
        """
        :action: 操作标识符
        """
        if action in ("cancel_all", "cancel_buy", "cancel_sell"):
            action = "cancel"
        self.switch(action)
        m = getattr(self.ctx, action.upper(), self.ctx.TABLE)
        if action in (
            "buy",
            "buy2",
            "sell",
            "sell2",
            "reverse_repo",
            "cancel",
            "purchase",
            "redeem",
        ):
            data = [user32.GetDlgItem(self._page, i) for i in m]
        else:
            data = reduce(
                user32.GetDlgItem,
                m,
                self.root if action in ("account", "mkt") else self._page,
            )
        return data

    def grab(self, hParent=None):
        "屏幕截图"
        from PIL import ImageGrab

        buf = io.BytesIO()
        rect = ctypes.wintypes.RECT()
        hImage = user32.FindWindowExW(hParent or self.hLogin, None, "Static", "")
        user32.GetWindowRect(hImage, ctypes.byref(rect))
        util.ensureForegroundWindow(hParent or self.hLogin)
        screenshot = ImageGrab.grab(
            (
                rect.left,
                rect.top,
                rect.right + (rect.right - rect.left) * 0.33,
                rect.bottom,
            )
        )
        screenshot.save(buf, "png")
        return buf.getvalue()

    def verify(self, image, ocr=None):
        try:
            from aip import AipOcr
        except Exception as e:
            print(e, "\n请在命令行下执行: pip install baidu-aip")

        conf = ocr or {
            "appId": "11645803",
            "apiKey": "RUcxdYj0mnvrohEz6MrEERqz",
            "secretKey": "4zRiYambxQPD1Z5HFh9VOoPXPK9AgBtZ",
        }

        ocr = AipOcr(**conf)
        try:
            r = ocr.basicGeneral(image).get("words_result")[0]["words"]
        except Exception as e:
            print(e, "\n验证码图片无法识别！")
            r = False
        return r

    def capture(self, root=None, label=""):
        """捕捉弹窗的文本内容"""
        buf = ctypes.create_unicode_buffer(64)
        root = root or self.root
        for _ in range(9):
            time.sleep(0.1)
            hPopup = user32.GetLastActivePopup(root)
            if hPopup != root:  # and self.visible(hPopup):
                hTips = user32.FindWindowExW(hPopup, 0, "Static", None)
                # print(hex(hPopup).upper(), hex(hTips).upper())
                hwndChildAfter = None
                for _ in range(9):
                    hButton = user32.FindWindowExW(hPopup, hwndChildAfter, "Button", 0)
                    user32.SendMessageW(hButton, util.Msg.WM_GETTEXT, 64, buf)
                    if buf.value in ("是(&Y)", "确定"):
                        label = buf.value
                        break
                    hwndChildAfter = hButton
                user32.SendMessageW(hTips, util.Msg.WM_GETTEXT, 64, buf)
                util.click_button(h_dialog=hPopup, label=label)
                break
        text = buf.value
        return text if text else "请按提示修改：系统设置->快速交易->委托成功后是否弹出提示对话框->是"

    def answer(self):
        """2020-2-10 修改逻辑确保回报窗口被关闭"""
        for _ in range(3):
            text = self.capture()
            if "编号" in text:
                return {"puppet": (re.findall(r"(\w*[0-9]+)\w*", text)[0], text)}
            for x in self.ctx.ERROR:
                if x in text:
                    return {"puppet": (0, text)}
        return {"puppet": (0, "弹窗捕获失败，请用check_config()检查设置")}

    def refresh(self):
        print("Refreshing page...")
        user32.PostMessageW(self.root, util.Msg.WM_COMMAND, self.ctx.FRESH, 0)
        return self if self.visible() else False

    def switch_mkt(self, symbol: str, handle: int):
        """
        :Prefix:上交所: '5'基, '6'A, '7'申购, '11'转债', 9'B
        适配银河|中山证券的默认值(0 ->上海Ａ股)。注意全角字母Ａ
        """
        index = self.mkt[0] if symbol.startswith(("6", "5", "7", "11")) else self.mkt[1]
        return util.switch_combobox(index, handle)

    def switch_way(self, index):
        """转为市价委托

        index: {1, 2, 3, 4, 5}, 留意沪深市价单有所不同。
        """
        if index in {1, 2, 3, 4, 5}:
            return util.switch_combobox(index, next(self.members))

    def if_fund(self, symbol, price):
        if symbol.startswith("5"):
            if len(str(price).split(".")[1]) == 3:
                self.capture()

    def make_heartbeat(self, time_interval=1680):
        """2019-6-6 新增方法制造心跳"""

        def refresh_page(time_interval):
            while self.enable_heartbeat:
                if not self.visible():
                    print("客户端离线(Off-line)!")
                    break
                stamp = self.heartbeat_stamp
                remainder = time_interval - (time.time() - stamp)
                secs = random.uniform(remainder / 2, remainder)
                print("Refreshing after {} minutes.".format(secs / 60))
                time.sleep(secs)

                # 若在休眠期间心跳印记没被修改，则刷新页面并修改心跳印记
                if self.visible() and stamp == self.heartbeat_stamp:
                    # print('Making heartbeat...')
                    self.refresh()
                    self.heartbeat_stamp = time.time()

        threading.Thread(
            target=refresh_page,
            kwargs={"time_interval": time_interval},
            name="heartbeat",
            daemon=True,
        ).start()

    def quote(self, codes, df_first=True):
        """有bug未修复！ get latest deal price"""
        self.switch("sell")
        code_h, *_, page_h = self.get_handle("sell")
        handle = user32.GetDlgItem(page_h, self.ctx.QUOTE)
        names = ["code", "price"]
        if isinstance(codes, str):
            codes = [codes]

        def _quote(code: str) -> float:
            util.fill(code, code_h)
            for _ in range(5):
                text = util.get_text(handle)
                if text != "-":
                    return float(text)
                time.sleep(0.1)

        data = [(code, _quote(code)) for code in codes]
        if df_first:
            data = util.pd.DataFrame(data, columns=names)
        return data

    def switch_account(self, serial_no: int):
        """切换账号

        serial_no: 登录账号的顺序号，从1开始。
        """
        cb = reduce(user32.GetDlgItem, self.ctx.ACCNAME, self.root)
        count = user32.SendMessageW(cb, util.Msg.CB_GETCOUNT, 0, 0)
        curr = user32.SendMessageW(cb, util.Msg.CB_GETCURSEL, 0, 0) + 1

        if 0 < serial_no < count and serial_no != curr and util.go_to_top(self.root):
            self.dxinput.keyDown("alt")
            self.dxinput.press(str(serial_no))
            self.dxinput.keyUp("alt")
            time.sleep(0.1)
            return self.accno, util.get_text(cb)
        return curr, count
