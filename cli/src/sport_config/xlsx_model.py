# -*- coding: utf-8 -*-
"""
sports.xlsx 访问层。

区域识别严格镜像 sport_gen.py / sport_sensor.py 的实际读取契约
（另参考飞书文档《运动配置 sports.xlsx 规则与约束（固件侧）》），
以保证工具对表格的定位与生成器一致。本模块只读，不修改工作簿。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import openpyxl

SHEET_SPORTS = "Sports"
SHEET_SENSOR = "sport sensor"
SHEET_DISTANCE = "distance fusion"
SHEET_GROUP = "sport_group"
SHEET_ATTR_CATALOG = "code_attr_product"

# sport_gen.py 处理顺序（code_attr_product A 列清单），每张表行区相同
CODE_ATTR_SHEETS = [
    "code_attr_sport", "code_attr_youth", "code_attr_balance", "code_attr_matterhorn",
    "code_attr_c2u", "code_attr_munich", "code_attr_geneva", "code_attr_atlas",
    "code_attr_a3p", "code_attr_pike",
]
# sport_gen 逐 product 驱动；code_attr_sport 额外生成 peripheral 文件
CODE_ATTR_MASTER = "code_attr_sport"


class _NotFound(Exception):
    pass


def _first_non_empty_row(ws, col, start_row=1):
    for r in range(start_row, ws.max_row + 1):
        v = ws.cell(row=r, column=col).value
        if v is not None and str(v).strip() != "":
            return r
    raise _NotFound(f"{ws.title} 第 {col} 列无内容")


def _last_data_row(ws, col, start_row=1):
    last = None
    for r in range(start_row, ws.max_row + 1):
        v = ws.cell(row=r, column=col).value
        if v is not None and str(v).strip() != "":
            last = r
    return last


@dataclass
class SportRow:
    """Sports sheet 中的一个运动数据行。坐标均指原始行号。"""
    row: int
    fw_id: Optional[int]
    app_value: Optional[object]       # B 列 App 运动类型值
    sync_key: Optional[object]        # C 列 App 三方同步筛选 Key
    cn_name: Optional[str]            # D 列
    en_name: Optional[str]            # F 列（研发字段名，非 E 列展示名）
    group_cn: Optional[object]        # U 列 cn name of group
    group_en: Optional[object]        # V 列 en name of group
    product_support: dict = field(default_factory=dict)  # {产品名(第1行): 单元格值}


@dataclass
class GroupRow:
    row: int
    en: str
    cn: str


@dataclass
class AttrRow:
    row: int
    attr_id: Optional[int]
    describe: Optional[str]
    en_attr_name: Optional[str]
    peripheral: Optional[str]          # E 列 peripheral_attr
    product: dict = field(default_factory=dict)   # 产品列 → 值
    group: dict = field(default_factory=dict)     # group 列 → 值


class WorkbookModel:
    def __init__(self, path: str):
        self.path = path
        # 保留公式/样式：data_only=False
        self.wb = openpyxl.load_workbook(path, data_only=False)
        self._cache = {}

    def _cached(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    # ---------- 通用 ----------
    def ws(self, name: str):
        return self.wb[name]

    def field_col(self, sheet: str, field: str) -> Optional[int]:
        """row2 精确匹配字段名 → 列号（镜像 __get_column_by_content）。"""
        ws = self.ws(sheet)
        for c in range(1, ws.max_column + 1):
            if ws.cell(row=2, column=c).value == field:
                return c
        return None

    def cell(self, sheet, row, col):
        return self.ws(sheet).cell(row=row, column=col).value

    # ---------- Sports ----------
    def sports_product_columns(self):
        """产品列 = row1 从 'Lyon' 起连续非空至末尾（镜像 generate_default_map 的
        find_value_column(ws,1,1,'Lyon') + 空列截止，但此处对中间空列也报错，避免截断）。"""
        ws = self.ws(SHEET_SPORTS)
        start = None
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=1, column=c).value
            if v is not None and str(v).strip() == "Lyon":
                start = c
                break
        if start is None:
            raise _NotFound("Sports 第 1 行未找到产品列起点 'Lyon'")
        cols, names = [], []
        for c in range(start, ws.max_column + 1):
            v = ws.cell(row=1, column=c).value
            if v is None or str(v).strip() == "":
                break
            cols.append(c)
            names.append(str(v).strip())
        return cols, names

    def sports_rows(self) -> list[SportRow]:
        return self._cached("sports_rows", self._sports_rows_impl)

    def _sports_rows_impl(self) -> list[SportRow]:
        ws = self.ws(SHEET_SPORTS)
        col_id = self.field_col(SHEET_SPORTS, "fw sport id")
        col_app = 2
        col_key = 3
        col_cn = self.field_col(SHEET_SPORTS, "cn name of type")
        col_en = self.field_col(SHEET_SPORTS, "en name of type")
        col_gcn = self.field_col(SHEET_SPORTS, "cn name of group")
        col_gen = self.field_col(SHEET_SPORTS, "en name of group")
        pcols, pnames = self.sports_product_columns()
        rows = []
        for r in range(3, ws.max_row + 1):
            en = ws.cell(row=r, column=col_en).value
            if en is None or str(en).strip() == "":
                continue
            rows.append(SportRow(
                row=r,
                fw_id=_as_int(ws.cell(row=r, column=col_id).value),
                app_value=ws.cell(row=r, column=col_app).value,
                sync_key=ws.cell(row=r, column=col_key).value,
                cn_name=_as_str(ws.cell(row=r, column=col_cn).value),
                en_name=_as_str(en),
                group_cn=ws.cell(row=r, column=col_gcn).value,
                group_en=ws.cell(row=r, column=col_gen).value,
                product_support={pnames[i]: ws.cell(row=r, column=pcols[i]).value
                                 for i in range(len(pcols))},
            ))
        return rows

    def sport_max_id(self) -> int:
        ids = [s.fw_id for s in self.sports_rows() if s.fw_id is not None]
        return max(ids) if ids else 0

    # ---------- sport_group ----------
    def sport_group_end_row(self) -> int:
        """A 列出现 sport_group_end 的行（镜像 __get_row__column_by_content(...,1,1)）。"""
        ws = self.ws(SHEET_GROUP)
        for r in range(1, ws.max_row + 1):
            if ws.cell(row=r, column=1).value == "sport_group_end":
                return r
        raise _NotFound("sport_group 未找到 sport_group_end")

    def group_rows(self) -> list[GroupRow]:
        return self._cached("group_rows", self._group_rows_impl)

    def _group_rows_impl(self) -> list[GroupRow]:
        end = self.sport_group_end_row()
        ws = self.ws(SHEET_GROUP)
        out = []
        for r in range(2, end):
            en = ws.cell(row=r, column=1).value
            if en is None or str(en).strip() == "":
                continue
            out.append(GroupRow(row=r, en=str(en).strip(), cn=_as_str(ws.cell(row=r, column=2).value)))
        return out

    # ---------- code_attr catalog & sheets ----------
    def code_attr_sheet_list(self) -> list[str]:
        """code_attr_product A 列 product_start..product_end 之间的表名（镜像 preprocess）。"""
        ws = self.ws(SHEET_ATTR_CATALOG)
        s = e = None
        for r in range(1, ws.max_row + 1):
            v = ws.cell(row=r, column=1).value
            if v == "code_attr_product_start":
                s = r
            elif v == "code_attr_product_end":
                e = r
                break
        if s is None or e is None:
            raise _NotFound("code_attr_product 缺少 start/end 标记")
        out = []
        for r in range(s + 1, e):
            v = ws.cell(row=r, column=1).value
            if v is not None and str(v).strip():
                out.append(str(v).strip())
        return out

    def code_attr_layout(self, sheet: str):
        """返回 {product_cols, product_names, group_cols, group_names, attr_start_row, attr_end_row}"""
        ws = self.ws(sheet)
        c_ps = self.field_col(sheet, "product_start")
        c_pe = self.field_col(sheet, "product_end")
        c_ae = self.field_col(sheet, "attr_end")
        if not (c_ps and c_pe and c_ae):
            raise _NotFound(f"{sheet} 缺少 product_start/product_end/attr_end 标记列")

        # SPORT_ATTR_MAX：C 列定位行（镜像 __get_row_by_content，min_col=3）
        max_row_ = None
        for r in range(3, ws.max_row + 1):
            if ws.cell(row=r, column=3).value == "SPORT_ATTR_MAX":
                max_row_ = r
                break
        if max_row_ is None:
            raise _NotFound(f"{sheet} 缺少 SPORT_ATTR_MAX")

        pcols = list(range(c_ps + 1, c_pe))           # product_start 与 product_end 之间
        pnames = [str(ws.cell(row=2, column=c).value).strip() for c in pcols
                  if ws.cell(row=2, column=c).value is not None and str(ws.cell(row=2, column=c).value).strip()]
        # group 列区 = (product_end, attr_end)
        gcols = [c for c in range(c_pe + 1, c_ae)
                 if ws.cell(row=2, column=c).value is not None
                 and str(ws.cell(row=2, column=c).value).strip() != ""]
        gnames = [str(ws.cell(row=2, column=c).value).strip() for c in gcols]
        # row2 空列会在 group 区内断（生成器按 attrGroupStart..attrGroupEnd 全列读，空列值为 None）
        return {
            "product_cols": pcols, "product_names": pnames,
            "group_cols": gcols, "group_names": gnames,
            "attr_start": 3, "attr_end": max_row_,  # SPORT_ATTR_MAX 行（哨兵，不属数据）
        }

    def attr_rows(self, sheet: str) -> list[AttrRow]:
        return self._cached("attr_rows:" + sheet, lambda: self._attr_rows_impl(sheet))

    def _attr_rows_impl(self, sheet: str) -> list[AttrRow]:
        layout = self.code_attr_layout(sheet)
        ws = self.ws(sheet)
        rows = []
        for r in range(layout["attr_start"], layout["attr_end"]):
            en = ws.cell(row=r, column=3).value
            if en is None or str(en).strip() == "":
                continue
            rows.append(AttrRow(
                row=r,
                attr_id=_as_int(ws.cell(row=r, column=1).value),
                describe=_as_str(ws.cell(row=r, column=2).value),
                en_attr_name=_as_str(en),
                peripheral=_as_str(ws.cell(row=r, column=5).value),
                product={layout["product_names"][i]: ws.cell(row=r, column=layout["product_cols"][i]).value
                         for i in range(len(layout["product_names"]))},
                group={layout["group_names"][i]: ws.cell(row=r, column=layout["group_cols"][i]).value
                       for i in range(len(layout["group_names"]))},
            ))
        return rows

    # ---------- sport sensor ----------
    def sensor_layout(self):
        """sensor: row1 展示名/row2 英文名, 从第 4 列起连续（镜像 _fin_group_max(ws,1,4)）。
        返回 {group_cols, group_names(第2行英文), sensor_rows:{键:行号}}"""
        ws = self.ws(SHEET_SENSOR)
        gcols, gnames = [], []
        for c in range(4, ws.max_column + 1):
            v1 = ws.cell(row=1, column=c).value
            if v1 is None or str(v1).strip() == "":
                break
            gcols.append(c)
            gnames.append(_as_str(ws.cell(row=2, column=c).value))
        return {"group_cols": gcols, "group_names": gnames}

    # ---------- distance fusion ----------
    def distance_layout(self):
        """df: row1 名称, 从 B(2) 列起连续；行5 = 算法名（镜像 generate_distance_algo_attr_*）。"""
        ws = self.ws(SHEET_DISTANCE)
        gcols, gnames, algos = [], [], []
        for c in range(2, ws.max_column + 1):
            v1 = ws.cell(row=1, column=c).value
            if v1 is None or str(v1).strip() == "":
                break
            gcols.append(c)
            gnames.append(_as_str(v1))
            algos.append(ws.cell(row=5, column=c).value)
        return {"group_cols": gcols, "group_names": gnames, "algos": algos}

    # ---------- 便捷 ----------
    def find_sport_row(self, fw_id: int) -> Optional[SportRow]:
        for s in self.sports_rows():
            if s.fw_id == fw_id:
                return s
        return None

    def snapshot_for_reload(self):
        pass

    def close(self):
        self.wb.close()


def _as_str(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _as_int(v):
    if v is None:
        return None
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return None
