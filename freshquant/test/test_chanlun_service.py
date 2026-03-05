# coding: utf-8

from freshquant import chanlun_service


def test_get_data_v2():
    data = chanlun_service.get_data_v2("sh600000", "60m")
    print(data)
