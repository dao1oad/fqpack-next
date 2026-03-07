# -*- coding: utf-8 -*-


class PositionManagementError(Exception):
    pass


class PositionManagementRejectedError(ValueError, PositionManagementError):
    pass


class PositionManagementUnavailableError(PositionManagementError):
    pass
