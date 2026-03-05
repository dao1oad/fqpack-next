# -*- coding: utf-8 -*-

from freshquant.Tools import Tools


class ToString:
    def getDescription(self):
        # 利用str的format格式化字符串
        # 利用生成器推导式去获取key和self中key对应的值的集合
        return ",".join(
            "{}={}".format(key, getattr(self, key)) for key in self.__dict__.keys()
        )

    # 重写__str__定义对象的打印内容
    # def __str__(self):
    #     return "{}->({})".format(self.__class__.__name__, self.getDescription())

    def __repr__(self):
        return "{}->({})\n".format(self.__class__.__name__, self.getDescription())


class Kline(ToString):
    # open = 0
    # high = 0
    # low = 0
    # close = 0
    def __init__(self):
        self.open = 0
        self.high = 0
        self.low = 0
        self.close = 0


class Test(ToString):
    classKlineList = []

    def __init__(self):
        self.klineList = []


test = Test()

kline = Kline()
kline.open = 1
kline.high = 2
kline.low = 3
kline.close = 4
test.klineList.append(kline)
test.classKlineList.append(kline)
kline = Kline()

kline.open = 5
kline.high = 6
kline.low = 7
kline.close = 8
test.klineList.append(kline)
test.classKlineList.append(kline)


# print(kline)
# print(test.klineList)
# print(test.classKlineList)
