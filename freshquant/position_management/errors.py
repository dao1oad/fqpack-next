# -*- coding: utf-8 -*-


class PositionManagementError(Exception):
    pass


class PositionManagementRejectedError(PositionManagementError):
    pass


class PositionManagementUnavailableError(PositionManagementError):
    pass
