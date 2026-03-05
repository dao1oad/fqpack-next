# -*- coding: utf-8 -*-
"""统一输出模块

提供数据库、文件、报表等多种输出方式
"""

from freshquant.screening.writers.database import DatabaseOutput
from freshquant.screening.writers.report import ReportOutput

__all__ = ["DatabaseOutput", "ReportOutput"]
