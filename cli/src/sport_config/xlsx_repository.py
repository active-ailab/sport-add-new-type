# -*- coding: utf-8 -*-
"""保存与备份。

备份策略：写回原文件前，在 xlsx 同目录生成带时间戳的 .bak-<ts>.xlsx 副本，
保证 master 仓库内可 git 审阅；不默认创建新文件。
"""
from __future__ import annotations

import datetime
import os
import shutil


def make_backup(xlsx_path: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{xlsx_path}.bak-{ts}"
    shutil.copy2(xlsx_path, bak)
    return bak


def save_workbook(wb, xlsx_path: str, backup: bool = True) -> dict:
    """保存。backup=True 时先在同目录留时间戳副本。返回 {backup: path|None}"""
    result = {"backup": None}
    if backup:
        result["backup"] = make_backup(xlsx_path)
    wb.save(xlsx_path)
    return result
