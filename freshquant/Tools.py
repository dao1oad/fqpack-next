# -*- coding: utf-8 -*-


class Tools:
    def prn_obj(obj):
        print('\t'.join(['%s:%s' % item for item in obj.__dict__.items()]))
