# -*- coding: utf-8 -*-
"""
联动变更操作引擎。

五种实体（运动类型 / 运动 group / 实时数据项 attr / 产品列 / 运动×产品矩阵）的
增删改。每个操作输出 ChangePlan（可 dry-run 预览 / apply 落盘）。

联动规则以 sport_gen.py 读取契约 + 飞书《运动配置 sports.xlsx 规则与约束（固件侧）》为准：
  * 矩阵表（sport sensor / distance fusion / code_attr_*）的【列】是 group 维度，
    顺序必须与 sport_group.A 一致；新增运动若复用已有 group 不需加列；
    新增 group 才需要给全部矩阵表在对应位置加列。
  * Sports 的【行】是运动维度，行序须按 fw sport id 升序（空洞保留）。
  * Sports 产品列 row1 从 'Lyon' 起连续，row2 为该列 Yes 计数（维护头）。
  * code_attr_* 每表以 product_start/product_end/attr_end 与 SPORT_ATTR_MAX 为界。
  * 产品支持列规范值 = 'Yes'（实时数据产品/运动列同为 Yes），sensor 用 'yes'。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

from .xlsx_model import (SHEET_ATTR_CATALOG, SHEET_DISTANCE, SHEET_GROUP, SHEET_SENSOR, SHEET_SPORTS, WorkbookModel)
from .xlsx_plan import (CellRangeClear, CellSet, ChangePlan, ColInsert, ColDelete,
                        RowInsert, RowDelete, SheetCopy)

YES = "Yes"          # 产品支持 / 实时数据开关
SENSOR_YES = "yes"   # sport sensor 专用（生成器只认小写）
GROUP_END = "sport_group_end"
ATTR_MAX = "SPORT_ATTR_MAX"


class OpError(Exception):
    """操作校验失败（阻断级）。"""


class Warn(Exception):
    """高优先级提示：不阻断，但随计划返回。"""


# ---------------------------------------------------------------- helpers
def norm_key(s) -> str:
    """group/运动名归一：小写、去首尾空格，用于跨表对位。"""
    if s is None:
        return ""
    return str(s).strip().lower()


def enum_norm(s) -> str:
    """模拟 sport_gen 枚举转换做对位：去空格与连字符并小写。
    'Cross-country skiing' 与 'cross country skiing' 归一后相等。"""
    if s is None:
        return ""
    return re.sub(r"[\s\-]+", "", str(s).strip().lower())


def en_to_enum(name: str) -> str:
    """镜像 sport_gen：去空格与连字符，转大写 → SPORT_TYPE_XXX。"""
    if name is None or not str(name).strip():
        raise OpError("运动英文名不能为空")
    n = str(name).strip()
    for ch in ("/", "(", ")", "+", ".", "&", "\\", ":"):
        if ch in n:
            raise OpError(f"英文名含生成器不支持字符 '{ch}'：{n!r}，请改用空格/连字符分隔")
    ident = re.sub(r"[ -]+", "_", n).upper()
    if not re.match(r"^[A-Z_][A-Z0-9_]*$", ident):
        raise OpError(f"英文名转换为枚举后非法 C 标识符：SPORT_TYPE_{ident}")
    return f"SPORT_TYPE_{ident}"


def group_to_enum(name) -> str:
    """group 名 → SPORT_GROUP_XXX。数值 < 0x20 走 SPORT_GROUP_n。"""
    try:
        v = int(str(name).strip())
        if v < 0x20:
            return f"SPORT_GROUP_{v}"
    except (ValueError, TypeError):
        pass
    s = str(name).strip()
    for ch in ("/", "(", ")", "+", ".", "&", "\\", ":"):
        if ch in s:
            raise OpError(f"group 名含不支持字符 '{ch}'：{s!r}")
    ident = re.sub(r"[ -]+", "_", s).upper()
    if not re.match(r"^[A-Z_][A-Z0-9_]*$", ident):
        raise OpError(f"group 名转换为枚举后非法 C 标识符：SPORT_GROUP_{ident}")
    return f"SPORT_GROUP_{ident}"


def _auto_id(model: WorkbookModel, sheet: str, col: int) -> int:
    """给定列现有数字的最大值 + 1。"""
    ws = model.ws(sheet)
    mx = 0
    for r in range(3, ws.max_row + 1):
        v = ws.cell(row=r, column=col).value
        if isinstance(v, (int, float)):
            mx = max(mx, int(v))
        elif isinstance(v, str) and v.strip().isdigit():
            mx = max(mx, int(v.strip()))
    return mx + 1


def _col(model: WorkbookModel, sheet: str, field: str) -> int:
    c = model.field_col(sheet, field)
    if not c:
        raise OpError(f"{sheet} 第 2 行缺少字段 {field!r}")
    return c


def _count_yes(ws, col: int, row_begin: int, row_end: int) -> int:
    n = 0
    for r in range(row_begin, row_end + 1):
        v = ws.cell(row=r, column=col).value
        if v is not None and str(v).strip() == YES:
            n += 1
    return n


def _set(model, sheet, row, col, new, reason) -> CellSet:
    old = model.ws(sheet).cell(row=row, column=col).value
    return CellSet(sheet=sheet, row=row, col=col, new=new, old=old, reason=reason)


# ---------------------------------------------------------------- 产品计数头(公式感知)
def _row2_count_value(model, col: int):
    """返回 (mode, value)。mode: 'num' 数值 / 'formula' COUNTIF 系公式 / 'none' 空。"""
    v = model.ws(SHEET_SPORTS).cell(row=2, column=col).value
    if v is None:
        return "none", None
    if isinstance(v, ArrayFormula):
        text = getattr(v, "text", "") or ""
        return ("formula", text) if text.strip().startswith("=") else ("other", v)
    if isinstance(v, str) and v.strip().startswith("="):
        return "formula", v.strip()
    if isinstance(v, (int, float)):
        return "num", int(v)
    return "other", v


def _count_formula_for(col: int, last_row: int) -> str:
    letter = get_column_letter(col)
    return f'=COUNTIF({letter}3:{letter}{last_row},"Yes")'


def count_head_update(model, col: int, *, last_row: int, delta: int = 0):
    """返回 CellSet(new) 用于更新 Sports 产品列 row2 计数头：
    - 原值公式(COUNTIF 系) → 重写公式范围到 last_row（保留动态特性）
    - 原值数值 → 数值 + delta（delta 用于增删运动/翻转）
    - 其它(含自定义公式) → None（不更新，返回 None）
    """
    mode, v = _row2_count_value(model, col)
    if mode == "formula":
        new = _count_formula_for(col, last_row)
    elif mode == "num":
        new = v + delta
    else:
        return None
    return CellSet(sheet=SHEET_SPORTS, row=2, col=col, new=new, old=model.ws(SHEET_SPORTS).cell(row=2, column=col).value,
                   reason="产品支持运动计数" if mode == "num" else "产品支持运动计数(公式)")


def sports_last_data_row(model) -> int:
    """Sports 最后一个含运动(en name of type)的数据行号。"""
    c = _col(model, SHEET_SPORTS, "en name of type")
    ws = model.ws(SHEET_SPORTS)
    last = 2
    for r in range(3, ws.max_row + 1):
        v = ws.cell(row=r, column=c).value
        if v is not None and str(v).strip():
            last = r
    return last


# ---------------------------------------------------------------- Sports 运动
@dataclass
class SportAddSpec:
    cn: str
    en: str
    fw_id: Optional[int] = None          # None=自动(max+1)
    app_value: Optional[object] = None   # B 列，None=留空待填
    sync_key: Optional[object] = None    # C 列
    group_en: Optional[str] = None       # 必填其一：复用已有 group（en 或 cn）
    group_cn: Optional[str] = None
    template_fw_id: Optional[int] = None # 模板运动：未提供的字段/开关列/产品列继承
    products: Optional[list] = None      # 产品支持列表（'copy'=随模板；None=全部空）
    hr_algo: Optional[object] = None     # 缺省取模板
    standup: Optional[object] = None
    wrist: Optional[object] = None


def sport_add(model: WorkbookModel, spec: SportAddSpec) -> ChangePlan:
    en_to_enum(spec.en)
    p = ChangePlan(title=f"新增运动: {spec.cn} / {spec.en}")
    rows = model.sports_rows()
    for s in rows:
        if norm_key(s.en_name) == norm_key(spec.en):
            raise OpError(f"运动英文名已存在：{s.en_name!r} (fw id={s.fw_id})")

    # group 解析
    if spec.group_cn and not spec.group_en:
        grp = next((g for g in model.group_rows() if norm_key(g.cn) == norm_key(spec.group_cn)), None)
        if grp is None:
            raise OpError(f"cn name of group {spec.group_cn!r} 在 sport_group 中不存在，请先新增该 group")
        spec.group_en = grp.en
    elif spec.group_en:
        grp = next((g for g in model.group_rows() if norm_key(g.en) == norm_key(spec.group_en)), None)
        if grp is None:
            raise OpError(f"en name of group {spec.group_en!r} 在 sport_group 中不存在，请先新增该 group")
    else:
        raise OpError("必须提供运动的 group（en 或 cn 名）")

    # 模板
    tmpl = None
    if spec.template_fw_id is not None:
        tmpl = model.find_sport_row(spec.template_fw_id)
        if tmpl is None:
            raise OpError(f"模板运动 fw sport id={spec.template_fw_id} 不存在")

    # 产品支持名校验
    if isinstance(spec.products, list):
        _, pn = model.sports_product_columns()
        bad = [x for x in spec.products if x not in pn]
        if bad:
            raise OpError(f"产品名不在 Sports 产品列中：{bad}（可用：{pn}）")

    fw_id = spec.fw_id if spec.fw_id is not None else model.sport_max_id() + 1
    if isinstance(fw_id, int) and fw_id <= 0:
        raise OpError("fw sport id 必须为正整数")
    if tmpl is None and fw_id <= model.sport_max_id():
        # 允许在空洞/中间插入：必须保持升序 → 检查是否比前一大
        pass
    if spec.fw_id is not None:
        if any(s.fw_id == fw_id for s in rows):
            raise OpError(f"fw sport id={fw_id} 已存在")
        if fw_id <= 0:
            raise OpError("fw sport id 必须为正整数")

    # 目标插入行：按 id 升序定位（生成器按行序对齐 sport_index，必须升序）
    last_row = rows[-1].row if rows else 3
    insert_at = last_row + 1
    if spec.fw_id is not None:
        # 找到第一个 fw_id 更大的行 → 插入其前
        for s in rows:
            if s.fw_id is not None and s.fw_id > fw_id:
                insert_at = s.row
                break
    if tmpl is not None and spec.fw_id is None:
        # 自动 id 默认排末尾
        insert_at = last_row + 1
    p.add(RowInsert(sheet=SHEET_SPORTS, at=insert_at, count=1, reason="插入运动数据行"))
    new_row = insert_at  # 插入后该行所在行号
    # 注：若下方又有 RowDelete 冲突不考虑（单计划单操作）。

    # 逐列填值（模板复制语义：G..W 能力列与其它扩展列继承模板）
    ws = model.ws(SHEET_SPORTS)
    max_col = ws.max_column
    tmpl_cells = {}
    if tmpl is not None:
        for c in range(1, max_col + 1):
            tmpl_cells[c] = ws.cell(row=tmpl.row, column=c).value

    col_id = _col(model, SHEET_SPORTS, "fw sport id")
    col_cn = _col(model, SHEET_SPORTS, "cn name of type")
    col_en = _col(model, SHEET_SPORTS, "en name of type")
    col_gcn = _col(model, SHEET_SPORTS, "cn name of group")
    col_gen = _col(model, SHEET_SPORTS, "en name of group")
    hr_col = model.field_col(SHEET_SPORTS, "type of hr algo")
    std_col = model.field_col(SHEET_SPORTS, "standup sensitivity")
    wr_col = model.field_col(SHEET_SPORTS, "wrist act type")
    pcols, pnames = model.sports_product_columns()

    # 该新运动在各产品列将写入的值（用于同步 row2 计数头）
    product_newvals = {}
    for i, c in enumerate(pcols):
        if spec.products == "copy":
            product_newvals[c] = tmpl_cells.get(c) if tmpl else None
        elif isinstance(spec.products, list):
            product_newvals[c] = YES if pnames[i] in spec.products else None
        else:
            product_newvals[c] = None

    for c in range(1, max_col + 1):
        new_val = None
        reason = "模板复制"
        if c == col_id:
            new_val, reason = fw_id, "新 fw sport id"
        elif c == col_cn:
            new_val, reason = spec.cn, "新运动中文名"
        elif c == col_en:
            new_val, reason = spec.en, "新运动英文名(研发)"
        elif c == col_gcn:
            new_val = grp.cn
            reason = "cn name of group"
        elif c == col_gen:
            new_val = grp.en
            reason = "en name of group"
        elif c in (2, 3):
            # B=app 值 / C=三方 key：仅显式给出时填写，不随模板复制（避免与既有运动标识冲突）
            if c == 2 and spec.app_value is not None:
                new_val, reason = spec.app_value, "App 运动类型值"
            elif c == 3 and spec.sync_key is not None:
                new_val, reason = spec.sync_key, "App 三方同步 Key"
        elif c == hr_col and spec.hr_algo is not None:
            new_val, reason = spec.hr_algo, "心率算法"
        elif c == std_col and spec.standup is not None:
            new_val, reason = spec.standup, "站立灵敏度"
        elif c == wr_col and spec.wrist is not None:
            new_val, reason = spec.wrist, "佩戴类型"
        elif c in pcols:
            new_val = product_newvals[c]
            reason = "产品支持"
        elif tmpl is not None:
            new_val = tmpl_cells.get(c)
        p.add(_set(model, SHEET_SPORTS, new_row, c, new_val, reason))

    # 同步产品计数头 row2（模板/列表 → 该产品列 Yes 数变化；公式/数值双模式）
    last_row_after = max((s.row for s in rows), default=3) + (1 if insert_at > rows[-1].row else 0) \
        if rows else new_row
    for i, c in enumerate(pcols):
        v = product_newvals[c]
        delta = 1 if (v is not None and str(v).strip() == YES) else 0
        cs = count_head_update(model, c, last_row=last_row_after, delta=delta)
        if cs is not None:
            p.add(cs)
    return p


# ---------------------------------------------------------------- 产品计数头重算
def sports_refresh_counts(model: WorkbookModel) -> ChangePlan:
    """重算 Sports 各产品列 row2 计数头（数值列直接重算；公式列重写范围）。"""
    p = ChangePlan(title="重算产品支持计数(Sports row2)")
    ws = model.ws(SHEET_SPORTS)
    pcols, pnames = model.sports_product_columns()
    last = sports_last_data_row(model)
    for c in pcols:
        mode, _ = _row2_count_value(model, c)
        if mode == "num":
            cnt = _count_yes(ws, c, 3, last)
            old = ws.cell(row=2, column=c).value
            if old != cnt:
                p.add(CellSet(sheet=SHEET_SPORTS, row=2, col=c, new=cnt, old=old,
                              reason="产品支持运动计数"))
        elif mode == "formula":
            cs = count_head_update(model, c, last_row=last, delta=0)
            if cs is not None and cs.new != cs.old:
                p.add(cs)
        # 'other'（自定义公式等）不动，避免误伤
    return p


def sport_delete(model: WorkbookModel, fw_id: int) -> ChangePlan:
    s = model.find_sport_row(fw_id)
    if s is None:
        raise OpError(f"fw sport id={fw_id} 不存在")
    p = ChangePlan(title=f"删除运动 fw id={fw_id} ({s.cn_name}/{s.en_name})")
    p.add(RowDelete(sheet=SHEET_SPORTS, at=s.row, count=1,
                    reason="删除运动数据行(保留 id 空洞，矩阵列为 group 维度不受影响)"))
    # 产品计数头：该运动支持的产品计数 -1（公式列自动随行数变化，此处只处理数值列与公式范围）
    last_after = sports_last_data_row(model)
    if s.row == last_after:
        last_after -= 1  # 删除的就是最后一行
    ws = model.ws(SHEET_SPORTS)
    pcols, _ = model.sports_product_columns()
    for c in pcols:
        v = ws.cell(row=s.row, column=c).value
        if v is None or str(v).strip() != YES:
            continue
        cs = count_head_update(model, c, last_row=last_after, delta=-1)
        if cs is not None:
            p.add(cs)
    return p


def sport_update(model: WorkbookModel, fw_id: int, *, cn=None, en=None, app_value=None,
                 sync_key=None, hr_algo=None, standup=None, wrist=None,
                 group_cn=None, group_en=None) -> ChangePlan:
    """None 表示不修改；如需清空某格请显式传空字符串。"""
    s = model.find_sport_row(fw_id)
    if s is None:
        raise OpError(f"fw sport id={fw_id} 不存在")
    p = ChangePlan(title=f"更新运动 fw id={fw_id}")
    if en is not None:
        en_to_enum(en)  # 校验
        for x in model.sports_rows():
            if x.row != s.row and norm_key(x.en_name) == norm_key(en):
                raise OpError(f"运动英文名冲突：{en!r}")
    hr_c = model.field_col(SHEET_SPORTS, "type of hr algo")
    std_c = model.field_col(SHEET_SPORTS, "standup sensitivity")
    wr_c = model.field_col(SHEET_SPORTS, "wrist act type")
    g_c = model.field_col(SHEET_SPORTS, "cn name of group")
    ge_c = model.field_col(SHEET_SPORTS, "en name of group")
    fields = {
        "cn name of type": (cn, _col(model, SHEET_SPORTS, "cn name of type")),
        "en name of type": (en, _col(model, SHEET_SPORTS, "en name of type")),
        "app_value": (app_value, 2), "sync_key": (sync_key, 3),
        "type of hr algo": (hr_algo, hr_c), "standup sensitivity": (standup, std_c),
        "wrist act type": (wrist, wr_c),
    }
    for fname, (val, c) in fields.items():
        if val is None:
            continue
        p.add(_set(model, SHEET_SPORTS, s.row, c, val, f"修改 {fname}"))
    if group_cn is not None or group_en is not None:
        en2 = group_en
        cn2 = group_cn
        if group_cn is not None and group_en is None:
            grp = next((g for g in model.group_rows() if norm_key(g.cn) == norm_key(group_cn)), None)
            if grp is None:
                raise OpError(f"group {group_cn!r} 不存在于 sport_group")
            en2, cn2 = grp.en, grp.cn
        if group_en is not None and group_cn is None:
            grp = next((g for g in model.group_rows() if norm_key(g.en) == norm_key(group_en)), None)
            if grp is None:
                raise OpError(f"group {group_en!r} 不存在于 sport_group")
            en2, cn2 = grp.en, grp.cn
        p.add(_set(model, SHEET_SPORTS, s.row, g_c, cn2, "cn name of group"))
        p.add(_set(model, SHEET_SPORTS, s.row, ge_c, en2, "en name of group"))
    return p


def _cell_text(ws, row, col):
    v = ws.cell(row=row, column=col).value
    return v


# ---------------------------------------------------------------- 运动×产品矩阵
def sport_product_set(model: WorkbookModel, fw_id: int, product: str, enable: bool) -> ChangePlan:
    """翻转某运动在某产品的支持。enable=True → 'Yes'；False → 清空。"""
    s = model.find_sport_row(fw_id)
    if s is None:
        raise OpError(f"fw sport id={fw_id} 不存在")
    pcols, pnames = model.sports_product_columns()
    if product not in pnames:
        raise OpError(f"产品 {product!r} 不在 Sports 产品列中")
    c = pcols[pnames.index(product)]
    new = YES if enable else None
    p = ChangePlan(title=f"运动 fw id={fw_id} × 产品 {product} → {'支持' if enable else '不支持'}")
    p.add(_set(model, SHEET_SPORTS, s.row, c, new, "运动×产品矩阵"))
    ws = model.ws(SHEET_SPORTS)
    cur = 1 if (ws.cell(row=s.row, column=c).value is not None
                and str(ws.cell(row=s.row, column=c).value).strip() == YES) else 0
    # 计数头：数值列 ±1；公式列无需改动（Excel 动态统计）；其它类型不动
    mode, _ = _row2_count_value(model, c)
    if mode == "num":
        delta = (1 if enable and not cur else (-1 if not enable and cur else 0))
        if delta:
            cs = count_head_update(model, c, last_row=sports_last_data_row(model), delta=delta)
            if cs is not None:
                p.add(cs)
    return p


# ---------------------------------------------------------------- group
def group_add(model: WorkbookModel, en: str, cn: str, *, code_attr_tables: Optional[list] = None,
              sensor=None, distance_algo=None) -> ChangePlan:
    """新增 group：sport_group 行 + 全部矩阵表加列（若这些表的列集与 sport_group 顺序对位）。"""
    if not en or not cn:
        raise OpError("group 的 en/cn 名均不能为空")
    if norm_key(en) in [norm_key(g.en) for g in model.group_rows()]:
        raise OpError(f"group 英文名已存在：{en!r}")
    group_to_enum(en)
    tbls = code_attr_tables if code_attr_tables is not None else model.code_attr_sheet_list()
    p = ChangePlan(title=f"新增 group: {en} / {cn}")

    # 在 sport_group 中确定插入位置（保持表序；默认末尾 end 前）
    groups = model.group_rows()
    end = model.sport_group_end_row()
    insert_row = end  # 默认 append 在 end 之前
    # 保持与矩阵列顺序一致：sensor/distance/code_attr 列序应与 sport_group 行序对位；
    # 若一致，插入位置 = sport_group 顺序中末尾 → 列插各表最末 group 列后。
    ws_g = model.ws(SHEET_GROUP)
    p.add(RowInsert(sheet=SHEET_GROUP, at=insert_row, count=1, reason="新增 group 行"))
    p.add(_set(model, SHEET_GROUP, insert_row, 1, en, "en group name"))
    p.add(_set(model, SHEET_GROUP, insert_row, 2, cn, "cn group name"))

    # sensor：D 列起连续列末+1 插入新列（row1 中文展示名 / row2 英文名）
    sl = model.sensor_layout()
    if sl["group_names"]:
        scols = sl["group_cols"]
        at_col = scols[-1] + 1
        if at_col <= model.ws(SHEET_SENSOR).max_column and \
                model.ws(SHEET_SENSOR).cell(row=1, column=at_col).value is not None:
            raise OpError("sport sensor 列集末尾非空，无法追加新 group 列（列序需与 sport_group 对位）")
        p.add(ColInsert(sheet=SHEET_SENSOR, at=at_col, count=1, reason="新增 group 列"))
        p.add(_set(model, SHEET_SENSOR, 1, at_col, cn, "sensor 列展示名"))
        p.add(_set(model, SHEET_SENSOR, 2, at_col, en, "sensor 列英文名"))
        vals = sensor or {}
        for row, key in ((3, "gps"), (4, "hr"), (5, "baro"), (6, "gyro")):
            v = vals.get(key)
            p.add(_set(model, SHEET_SENSOR, row, at_col,
                       SENSOR_YES if v is True else (None if v is False else None),
                       f"sensor {key}（yes=支持）"))
    # distance fusion：B 列起连续列末+1
    dl = model.distance_layout()
    if dl["group_cols"]:
        at_col = dl["group_cols"][-1] + 1
        ws_d = model.ws(SHEET_DISTANCE)
        if at_col <= ws_d.max_column and ws_d.cell(row=1, column=at_col).value is not None:
            raise OpError("distance fusion 列集末尾非空，无法追加新 group 列")
        p.add(ColInsert(sheet=SHEET_DISTANCE, at=at_col, count=1, reason="新增 group 列"))
        p.add(_set(model, SHEET_DISTANCE, 1, at_col, cn, "距离表列名"))
        for r in (2, 3, 4):
            p.add(_set(model, SHEET_DISTANCE, r, at_col, None, f"能力行{r}(留空待填)"))
        p.add(_set(model, SHEET_DISTANCE, 5, at_col, distance_algo,
                   "距离算法(如 ACC+GPS/NULL)"))
    # code_attr_*：group 列区(product_end+1..attr_end-1) 追加列。
    # 若最后一列与 attr_end 相邻，则在 attr_end 哨兵列位置插入（哨兵随之下移，仍在区末）。
    for t in tbls:
        if t not in model.wb.sheetnames:
            raise OpError(f"勾选的表 {t} 不存在")
        lay = model.code_attr_layout(t)
        gcols = lay["group_cols"]
        attr_end_col = model.field_col(t, "attr_end")
        if not gcols:
            continue
        at_col = gcols[-1] + 1
        # 对位校验：数量必须一致（append 到末尾即与 sport_group 行序同步）；
        # 名称个别差异不影响列序追加（生成器按列序映射），放行即可。
        expect = [enum_norm(g.en) for g in model.group_rows()]
        actual = [enum_norm(x) for x in lay["group_names"]]
        if actual and len(actual) != len(expect):
            raise OpError(f"{t} 的 group 列数({len(actual)})与 sport_group({len(expect)})不一致，"
                          "禁止自动追加列（先手工整理）")
        if at_col > attr_end_col:
            raise OpError(f"{t} group 列区异常（末尾越界 attr_end），先手工整理")
        # 允许 at_col == attr_end_col：在哨兵位置插入
        p.add(ColInsert(sheet=t, at=at_col, count=1, reason="新增 group 列"))
        p.add(_set(model, t, 1, at_col, cn, "attr 表 group 展示名"))
        p.add(_set(model, t, 2, at_col, en, "attr 表 group 列名(row2)"))
        # 若插在哨兵列，哨兵行其它行(第3行起每 attr 行的列值)自动下移保留
    return p


# ---------------------------------------------------------------- group rename
def group_rename(model: WorkbookModel, *, old_en: Optional[str] = None, old_cn: Optional[str] = None,
                 new_en: Optional[str] = None, new_cn: Optional[str] = None,
                 code_attr_tables: Optional[list] = None) -> ChangePlan:
    """group 改名联动：sport_group 行、Sports 中引用该 group 的所有行(U/V)、
    三张矩阵表中该 group 的展示/名称列。old_en/old_cn 至少给一个定位；new_en/new_cn 至少给一个。"""
    if not (old_en or old_cn):
        raise OpError("定位旧 group 需要 old_en 或 old_cn")
    if new_en is None and new_cn is None:
        raise OpError("至少提供一个新名称 new_en / new_cn")
    rows = model.group_rows()
    grp = None
    if old_en:
        grp = next((g for g in rows if norm_key(g.en) == norm_key(old_en)), None)
    if grp is None and old_cn:
        grp = next((g for g in rows if norm_key(g.cn) == norm_key(old_cn)), None)
    if grp is None:
        raise OpError(f"group {old_en or old_cn!r} 不存在")
    old_en_k = norm_key(grp.en)
    old_cn_k = norm_key(grp.cn)
    if new_en is not None:
        if norm_key(new_en) == old_en_k:
            new_en = None  # 未变化
        elif norm_key(new_en) in [norm_key(g.en) for g in rows if g.row != grp.row]:
            raise OpError(f"新 en group 名已存在：{new_en!r}")
        else:
            group_to_enum(new_en)
    if new_cn is not None and norm_key(new_cn) == old_cn_k:
        new_cn = None
    if new_en is None and new_cn is None:
        raise OpError("新名称与旧名称相同，无变更")
    p = ChangePlan(title=f"重命名 group: {grp.en}/{grp.cn} → {new_en or grp.en}/{new_cn or grp.cn}")

    # 1) sport_group 行
    ws = model.ws(SHEET_GROUP)
    if new_en is not None:
        p.add(_set(model, SHEET_GROUP, grp.row, 1, new_en, "group en 名"))
    if new_cn is not None:
        p.add(_set(model, SHEET_GROUP, grp.row, 2, new_cn, "group cn 名"))

    # 2) Sports 引用
    col_gcn = _col(model, SHEET_SPORTS, "cn name of group")
    col_gen = _col(model, SHEET_SPORTS, "en name of group")
    for s in model.sports_rows():
        if s.group_en is not None and norm_key(s.group_en) == old_en_k and new_en is not None:
            p.add(_set(model, SHEET_SPORTS, s.row, col_gen, new_en, "Sports en name of group"))
        if s.group_cn is not None and norm_key(s.group_cn) == old_cn_k and new_cn is not None:
            p.add(_set(model, SHEET_SPORTS, s.row, col_gcn, new_cn, "Sports cn name of group"))

    # 3) sport sensor：row2 列名 = group en 风格（原样）；row1 中文展示 = group cn
    sl = model.sensor_layout()
    for i, nm in enumerate(sl["group_names"]):
        if new_en is not None and norm_key(nm) == old_en_k:
            p.add(_set(model, SHEET_SENSOR, 2, sl["group_cols"][i], new_en, "sensor 列英文名"))
        if new_cn is not None:
            c1 = model.ws(SHEET_SENSOR).cell(row=1, column=sl["group_cols"][i]).value
            if c1 is not None and norm_key(c1) == old_cn_k:
                p.add(_set(model, SHEET_SENSOR, 1, sl["group_cols"][i], new_cn, "sensor 列展示名"))
    # 4) distance fusion：row1 中文
    dl = model.distance_layout()
    for i, nm in enumerate(dl["group_names"]):
        if new_cn is not None and norm_key(nm) == old_cn_k:
            p.add(_set(model, SHEET_DISTANCE, 1, dl["group_cols"][i], new_cn, "distance 列名"))
    # 5) code_attr_*：row2 en 列名 / row1 cn 展示
    tbls = code_attr_tables if code_attr_tables is not None else model.code_attr_sheet_list()
    for t in tbls:
        if t not in model.wb.sheetnames:
            continue
        lay = model.code_attr_layout(t)
        for i, nm in enumerate(lay["group_names"]):
            c = lay["group_cols"][i]
            if new_en is not None and norm_key(nm) == old_en_k:
                p.add(_set(model, t, 2, c, new_en, f"{t} 列英文名(row2)"))
            if new_cn is not None:
                c1 = model.ws(t).cell(row=1, column=c).value
                if c1 is not None and norm_key(c1) == old_cn_k:
                    p.add(_set(model, t, 1, c, new_cn, f"{t} 列展示名(row1)"))
    return p


# ---------------------------------------------------------------- group delete
def group_delete(model: WorkbookModel, *, en: Optional[str] = None, cn: Optional[str] = None,
                 code_attr_tables: Optional[list] = None) -> ChangePlan:
    """删除 group（联动：sport_group 行 + 全部矩阵表对应列）。
    安全规则：
      1) 仍有运动引用该 group（Sports 行 en name of group）→ 阻断，提示先迁移运动；
      2) 各矩阵表按 group 列序删除；该序号不存在则说明该表本来就缺列，跳过即可；
      3) 删除后以 sport_group 新序号作为后续矩阵对齐基准。
    """
    if not (en or cn):
        raise OpError("需要 en 或 cn 定位 group")
    rows = model.group_rows()
    grp = None
    if en:
        grp = next((g for g in rows if enum_norm(g.en) == enum_norm(en)), None)
    if grp is None and cn:
        grp = next((g for g in rows if norm_key(g.cn or "") == norm_key(cn)), None)
    if grp is None:
        raise OpError(f"group {en or cn!r} 不存在")
    # 1) 引用检查
    users = [s for s in model.sports_rows()
             if s.group_en is not None and enum_norm(s.group_en) == enum_norm(grp.en)]
    if users:
        names = "、".join(f"{s.fw_id}:{s.en_name}" for s in users[:5])
        more = f" 等 {len(users)} 个" if len(users) > 5 else ""
        raise OpError(f"group {grp.en!r} 仍被 {len(users)} 个运动引用（{names}{more}），"
                      "不能删除；请先在运动编辑中把这些运动改到其它分组")
    # 2) 对位：sport_group 中序号
    idx = next((i for i, g in enumerate(rows) if g.row == grp.row), None)
    if idx is None:
        raise OpError(f"group {grp.en!r} 定位序号失败")
    p = ChangePlan(title=f"删除 group: {grp.en} / {grp.cn}")

    # 3) 矩阵表按 group 序号取列。列数可能已因尾部孤立 group 缺失而不同：
    # 有该序号列时删除；没有则不操作，删除 sport_group 行后自然恢复对齐。
    sl = model.sensor_layout()
    dl = model.distance_layout()
    tbls = code_attr_tables if code_attr_tables is not None else model.code_attr_sheet_list()
    matrices = [(SHEET_SENSOR, sl["group_cols"],
                 "删除该 group 对应的传感器列"),
                (SHEET_DISTANCE, dl["group_cols"],
                 "删除该 group 对应的距离配置列")]
    for t in tbls:
        if t not in model.wb.sheetnames:
            raise OpError(f"勾选的表 {t} 不存在")
        lay = model.code_attr_layout(t)
        matrices.append((t, lay["group_cols"],
                         "删除该 group 对应的属性矩阵列"))
    p.add(RowDelete(sheet=SHEET_GROUP, at=grp.row, count=1, reason="删除 group 行"))
    for name, columns, reason in matrices:
        if idx < len(columns):
            p.add(ColDelete(sheet=name, at=columns[idx], count=1, reason=reason))
    return p


# ---------------------------------------------------------------- attr（实时数据项）
def attr_add(model: WorkbookModel, describe: str, en_attr_name: str,
             peripheral: Optional[str] = None, *, code_attr_tables: Optional[list] = None,
             attr_id: Optional[int] = None,
             products: Optional[list] = None, groups: Optional[list] = None) -> ChangePlan:
    """新增实时数据项：在每张勾选 code_attr 表的 SPORT_ATTR_MAX 行前插入行。"""
    if not describe or not en_attr_name:
        raise OpError("attr describe 与 en_attr_name 不能为空")
    if not re.match(r"^[a-z][a-z0-9_]*$", en_attr_name):
        raise OpError(f"en_attr_name 非法（须 snake_case 小写字母数字下划线）：{en_attr_name!r}")
    tbls = code_attr_tables if code_attr_tables is not None else model.code_attr_sheet_list()
    if not tbls:
        raise OpError("未勾选任何 code_attr 表")
    first = tbls[0]
    rows0 = model.attr_rows(first)
    for r in rows0:
        if norm_key(r.en_attr_name) == norm_key(en_attr_name):
            raise OpError(f"en_attr_name 已存在：{en_attr_name!r}")
    new_id = attr_id if attr_id is not None else _auto_id(model, first, 1)
    if attr_id is not None and any(r.attr_id == attr_id for r in rows0):
        raise OpError(f"attr id={attr_id} 已存在")
    p = ChangePlan(title=f"新增实时数据项: {describe} / {en_attr_name} (attr id={new_id})")
    for t in tbls:
        if t not in model.wb.sheetnames:
            raise OpError(f"勾选的表 {t} 不存在")
        ws = model.ws(t)
        lay = model.code_attr_layout(t)
        end = lay["attr_end"]  # SPORT_ATTR_MAX 行
        p.add(RowInsert(sheet=t, at=end, count=1, reason="SPORT_ATTR_MAX 前插入 attr 行"))
        # SPORT_ATTR_MAX 行内容保持原样(随插入下移)，哨兵仍在 end+1
        p.add(_set(model, t, end, 1, new_id, "attr id"))
        p.add(_set(model, t, end, 2, describe, "attr describe"))
        p.add(_set(model, t, end, 3, en_attr_name, "en_attr_name"))
        p.add(_set(model, t, end, 4, describe, "注释"))
        p.add(_set(model, t, end, 5, peripheral or "NO", "peripheral_attr"))
        for c, pn in zip(lay["product_cols"], lay["product_names"]):
            v = YES if (products and pn in products) else None
            p.add(_set(model, t, end, c, v, f"产品[{pn}]"))
        for c, gn in zip(lay["group_cols"], lay["group_names"]):
            v = YES if (groups and norm_key(gn) in [norm_key(x) for x in groups]) else None
            p.add(_set(model, t, end, c, v, f"group[{gn}]"))
    return p


def attr_update(model: WorkbookModel, en_attr_name: str, *, describe=None, peripheral=None,
                products: Optional[dict] = None, groups: Optional[dict] = None,
                code_attr_tables: Optional[list] = None) -> ChangePlan:
    """更新指定 en_attr_name 的字段/产品/group 开关。products/groups 形如 {名称: bool}。"""
    tbls = code_attr_tables if code_attr_tables is not None else model.code_attr_sheet_list()
    first = tbls[0]
    rows0 = model.attr_rows(first)
    hit = [r for r in rows0 if norm_key(r.en_attr_name) == norm_key(en_attr_name)]
    if not hit:
        raise OpError(f"en_attr_name={en_attr_name!r} 不存在于 {first}")
    p = ChangePlan(title=f"更新实时数据项: {en_attr_name}")
    for t in tbls:
        if t not in model.wb.sheetnames:
            raise OpError(f"勾选的表 {t} 不存在")
        # 每张表按 en_attr_name 找行（个别表可能缺该行 → 跳过并记录）
        rr = [r for r in model.attr_rows(t) if norm_key(r.en_attr_name) == norm_key(en_attr_name)]
        if not rr:
            p.add(_noop_note(t))
            continue
        row = rr[0].row
        lay = model.code_attr_layout(t)
        if describe is not None:
            p.add(_set(model, t, row, 2, describe, "attr describe"))
        if peripheral is not None:
            p.add(_set(model, t, row, 5, peripheral, "peripheral_attr"))
        if products:
            for c, pn in zip(lay["product_cols"], lay["product_names"]):
                if pn in products:
                    v = YES if products[pn] else None
                    p.add(_set(model, t, row, c, v, f"产品[{pn}]"))
        if groups:
            norm_map = {norm_key(k): v for k, v in groups.items()}
            for c, gn in zip(lay["group_cols"], lay["group_names"]):
                want = norm_map.get(norm_key(gn))
                if want is not None:
                    v = YES if want else None
                    p.add(_set(model, t, row, c, v, f"group[{gn}]"))
    return p


def attr_delete(model: WorkbookModel, en_attr_name: str,
                code_attr_tables: Optional[list] = None) -> ChangePlan:
    tbls = code_attr_tables if code_attr_tables is not None else model.code_attr_sheet_list()
    rows0 = model.attr_rows(tbls[0])
    hit = [r for r in rows0 if norm_key(r.en_attr_name) == norm_key(en_attr_name)]
    if not hit:
        raise OpError(f"en_attr_name={en_attr_name!r} 不存在")
    p = ChangePlan(title=f"删除实时数据项: {en_attr_name}（attr id 不回收）")
    for t in tbls:
        if t not in model.wb.sheetnames:
            raise OpError(f"勾选的表 {t} 不存在")
        rr = [r for r in model.attr_rows(t) if norm_key(r.en_attr_name) == norm_key(en_attr_name)]
        if not rr:
            continue
        p.add(RowDelete(sheet=t, at=rr[0].row, count=1, reason="删除 attr 行"))
    return p


def _noop_note(sheet: str):
    """用于跨表缺失时的占位说明，实际无操作。"""
    from .xlsx_plan import CellSet  # noqa
    raise OpError(f"表 {sheet} 中不存在该 en_attr_name；如需继续处理其余表请剔除该表")


# ---------------------------------------------------------------- 产品列
def _catalog_end_row(model: WorkbookModel) -> int:
    ws = model.ws(SHEET_ATTR_CATALOG)
    for row in range(1, ws.max_row + 1):
        if ws.cell(row=row, column=1).value == "code_attr_product_end":
            return row
    raise OpError("code_attr_product 未找到 code_attr_product_end")


def product_add(model: WorkbookModel, product: str, *,
                code_attr_tables: Optional[list] = None,
                new_code_attr_table: Optional[str] = None) -> ChangePlan:
    """新增产品：Sports 产品列 + 一个指定的 code_attr 表产品列，或新建对应表。"""
    if not product:
        raise OpError("产品名不能为空")
    if not re.match(r"^[A-Za-z][A-Za-z0-9_ -]*$", product):
        raise OpError(f"产品名须为字母开头（将用于生成 sport_type_in_<name>.h / sport_rt_attr_<name>.h）：{product!r}")
    pcols, pnames = model.sports_product_columns()
    if product.casefold() in [str(name).casefold() for name in pnames]:
        raise OpError(f"产品 {product!r} 已存在于 Sports")
    if new_code_attr_table:
        if code_attr_tables:
            raise OpError("新建 code_attr 表时不能同时选择既有表")
        if not re.fullmatch(r"code_attr_[A-Za-z0-9_]+", new_code_attr_table):
            raise OpError(f"新表名必须为 code_attr_ 开头的字母、数字或下划线：{new_code_attr_table!r}")
        if new_code_attr_table in model.wb.sheetnames:
            raise OpError(f"新表 {new_code_attr_table!r} 已存在")
        if new_code_attr_table in model.code_attr_sheet_list():
            raise OpError(f"新表 {new_code_attr_table!r} 已登记在 code_attr_product")
        tbls = [new_code_attr_table]
    else:
        tbls = code_attr_tables or []
        if len(tbls) != 1:
            raise OpError("新增产品时必须选择一个 code_attr_* 表，或选择新建表")
        if tbls[0] not in model.wb.sheetnames:
            raise OpError(f"选择的表 {tbls[0]!r} 不存在")
    p = ChangePlan(title=f"新增产品列: {product} → {tbls[0]}")

    # Sports：产品列区末尾追加
    at_col = pcols[-1] + 1
    ws = model.ws(SHEET_SPORTS)
    if at_col <= ws.max_column and ws.cell(row=1, column=at_col).value is not None:
        raise OpError("Sports 产品列后存在非空列，无法追加（第1行产品列须连续）")
    p.add(ColInsert(sheet=SHEET_SPORTS, at=at_col, count=1, reason="新增产品列"))
    p.add(_set(model, SHEET_SPORTS, 1, at_col, product, "产品名(row1)"))
    p.add(_set(model, SHEET_SPORTS, 2, at_col, 0, "产品支持运动数(row2)"))

    for t in tbls:
        if new_code_attr_table:
            template = "code_attr_sport"
            lay = model.code_attr_layout(template)
            groups = model.group_rows()
            if len(lay["group_cols"]) > len(groups):
                raise OpError(
                    f"模板 {template} 的 group 列数({len(lay['group_cols'])})"
                    f"大于 sport_group 数({len(groups)})，无法安全创建新表"
                )
            p.add(SheetCopy(source=template, target=t, reason="新 code_attr 表模板"))
            p.add(RowInsert(sheet=SHEET_ATTR_CATALOG, at=_catalog_end_row(model), count=1,
                            reason="登记新 code_attr 表"))
            p.add(_set(model, SHEET_ATTR_CATALOG, _catalog_end_row(model), 1, t,
                       "code_attr 表名"))
            p.add(ColDelete(sheet=t, at=lay["product_cols"][0], count=len(lay["product_cols"]),
                            reason="移除模板产品列"))
            at = model.field_col(template, "product_end") - len(lay["product_cols"])

            # 新项目不能继承模板项目已启用的 group 能力。产品列移除并新插入后，
            # 原 group 列会整体左移 len(product_cols)-1 列；CellSet 使用最终坐标。
            group_col_shift = len(lay["product_cols"]) - 1
            p.add(CellRangeClear(
                sheet=t,
                row_start=lay["attr_start"], row_end=lay["attr_end"] - 1,
                col_start=lay["group_cols"][0] - group_col_shift,
                col_end=lay["group_cols"][-1] - group_col_shift,
                reason="新项目默认关闭 group 能力",
            ))

            # 模板可能落后于当前 sport_group。只补齐模板末尾缺少的分组，避免新表
            # 因复制旧结构立即产生 group 列数不一致；已有的分组表头保持模板原样。
            missing_groups = groups[len(lay["group_cols"]):]
            if missing_groups:
                attr_end_col = model.field_col(template, "attr_end")
                p.add(ColInsert(sheet=t, at=attr_end_col, count=len(missing_groups),
                                reason="补齐当前 sport_group 列"))
                first_final_col = attr_end_col - group_col_shift
                for offset, group in enumerate(missing_groups):
                    p.add(CellSet(sheet=t, row=1, col=first_final_col + offset,
                                  new=group.cn, old=None, reason="新增 group 中文表头"))
                    p.add(CellSet(sheet=t, row=2, col=first_final_col + offset,
                                  new=group.en, old=None, reason="新增 group 英文表头"))
        else:
            lay = model.code_attr_layout(t)
            at = model.field_col(t, "product_end")
        p.add(ColInsert(sheet=t, at=at, count=1, reason="product_end 前插入产品列"))
        if new_code_attr_table:
            p.add(CellSet(sheet=t, row=1, col=at, new=product, old=None,
                          reason="产品展示名(row1)"))
            p.add(CellSet(sheet=t, row=2, col=at, new=product, old=None,
                          reason="产品名(row2)"))
        else:
            p.add(_set(model, t, 1, at, product, "产品展示名(row1)"))
            p.add(_set(model, t, 2, at, product, "产品名(row2)"))
    return p


def product_delete(model: WorkbookModel, product: str, *,
                   code_attr_tables: Optional[list] = None) -> ChangePlan:
    pcols, pnames = model.sports_product_columns()
    if product not in pnames:
        raise OpError(f"产品 {product!r} 不在 Sports 产品列中")
    at = pcols[pnames.index(product)]
    tbls = code_attr_tables if code_attr_tables is not None else model.code_attr_sheet_list()
    p = ChangePlan(title=f"删除产品列: {product}")
    p.add(ColDelete(sheet=SHEET_SPORTS, at=at, count=1, reason="删除产品列"))
    for t in tbls:
        if t not in model.wb.sheetnames:
            continue
        lay = model.code_attr_layout(t)
        matches = [i for i, name in enumerate(lay["product_names"])
                   if str(name).casefold() == product.casefold()]
        if not matches:
            continue
        c = lay["product_cols"][matches[0]]
        p.add(ColDelete(sheet=t, at=c, count=1, reason="删除产品列"))
    return p
