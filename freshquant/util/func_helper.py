# -*- coding: utf-8 -*-


class RunOnce:
    def __init__(self, func):
        self.func = func
        self.has_run = False

    def __call__(self, *args, **kwargs):
        if not self.has_run:
            self.has_run = True
            return self.func(*args, **kwargs)
