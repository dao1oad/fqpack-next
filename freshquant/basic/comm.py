# -*- coding: utf-8 -*-

import pydash


def FindPrevEq(a, v, i):
    result = -1
    for x in range(i - 1, -1, -1):
        if a[x] == v:
            result = x
            break
    return result


def FindNextEq(a, v, i, end):
    result = -1
    for x in range(i, end):
        if a[x] == v:
            result = x
            break
    return result


def FindPrevGt(a, v, i):
    result = -1
    for x in range(i - 1, -1, -1):
        if a[x] > v:
            result = x
            break
    return result


def FindNextGt(a, v, i, end):
    result = -1
    for x in range(i, end):
        if a[x] > v:
            result = x
            break
    return result


def FindPrevLt(a, v, i):
    result = -1
    for x in range(i - 1, -1, -1):
        if a[x] < v:
            result = x
            break
    return result


def FindNextLt(a, v, i, end):
    result = -1
    for x in range(i, end):
        if a[x] < v:
            result = x
            break
    return result


def FindPrevEntanglement(e_list, t):
    for idx in range(len(e_list) - 1, -1, -1):
        if e_list[idx].endTime < t:
            return e_list[idx]
    return None
