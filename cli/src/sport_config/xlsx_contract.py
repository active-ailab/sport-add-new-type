# -*- coding: utf-8 -*-
"""
只读规则检查器。

校验等级（参考《运动配置 sports.xlsx 规则与约束（固件侧）》第 9 节）：
  error    阻断级：会导致生成失败 / 非法 C 标识 / 数组错位 / 跨表引用缺失
  warning  高优先级：可能造成实际能力错误（大小写、单侧矩阵、空格误判）
  info     提示人工确认（保留位、特殊文本、accel ignore 等）
每条输出 rule_id / sheet / cell / 当前值 / 说明 / 影响产物。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from . import xlsx_editor as ops
from .xlsx_model import WorkbookModel

OK = set()  # 便于后续引用


@dataclass
class Finding:
    rule_id: str
    severity: str          # error | warning | info
    sheet: str
    cell: str              # 坐标或 '-'
    value: str
    message: str

    def line(self):
        return f"[{self.severity.upper():7}] {self.rule_id} {self.sheet}!{self.cell} 值={self.value!r}  {self.message}"


RULES_PATH = Path(__file__).resolve().parent / "rules" / "sports_xlsx_rules.yaml"


class Checker:
    def __init__(self, model: WorkbookModel, rules):
        self.m = model
        self.rules = rules.get("contract_rules", {})
        self.findings: list[Finding] = []

    def add(self, rule_id, severity, sheet, cell, value, message):
        spec = self.rules.get(rule_id)
        if spec is None:
            return
        configured_severity = spec["severity"]
        self.findings.append(Finding(
            rule_id,
            severity if configured_severity == "inherit" else configured_severity,
            sheet,
            cell,
            "" if value is None else str(value),
            message,
        ))

    # ---------- Sports ----------
    def _check_sports(self):
        m = self.m
        rows = m.sports_rows()
        seen_id, seen_enum, seen_cn = {}, {}, {}
        last_id = 0
        for s in rows:
            tag = f"row{s.row}"
            if s.fw_id is None:
                self.add("SPT-002", "error", "Sports", f"A{s.row}", s.en_name,
                         "存在英文名但 fw sport id 缺失（生成器按行序对齐会错位）")
                continue
            if s.fw_id <= 0:
                self.add("SPT-002", "error", "Sports", f"A{s.row}", s.fw_id, "fw sport id 必须为正整数")
            if s.fw_id in seen_id:
                self.add("SPT-001", "error", "Sports", f"A{s.row}", s.fw_id,
                         f"fw sport id 重复（首次见于 {seen_id[s.fw_id]}）")
            else:
                seen_id[s.fw_id] = tag
            if s.fw_id is not None and s.fw_id < last_id:
                self.add("SPT-003", "error", "Sports", f"A{s.row}", s.fw_id,
                         f"行序未按 fw sport id 升序（前一行 {last_id}），sport_index 对齐将错位")
            if s.fw_id is not None:
                last_id = max(last_id, s.fw_id)
            if not s.en_name:
                self.add("SPT-005", "error", "Sports", f"F{s.row}", s.en_name, "en name of type 为空")
                continue
            try:
                enum = ops.en_to_enum(s.en_name)
            except ops.OpError as e:
                self.add("SPT-004", "error", "Sports", f"F{s.row}", s.en_name, str(e))
                continue
            if enum in seen_enum:
                self.add("SPT-004", "error", "Sports", f"F{s.row}", s.en_name,
                         f"英文名转枚举与 {seen_enum[enum]} 冲突 → {enum}")
            else:
                seen_enum[enum] = tag
            if not s.cn_name:
                self.add("SPT-006", "warning", "Sports", f"D{s.row}", s.cn_name, "cn name of type 为空")
            elif s.cn_name in seen_cn:
                self.add("SPT-006", "warning", "Sports", f"D{s.row}", s.cn_name,
                         f"cn 名重复（首次见于 {seen_cn[s.cn_name]}）")
            else:
                seen_cn[s.cn_name] = tag
            # group 引用：用枚举归一比对（sport_gen 会把空格/'-' 同化为 '_'）
            ge = m.field_col("Sports", "en name of group")
            gc = m.field_col("Sports", "cn name of group")
            gval = m.cell("Sports", s.row, ge)
            gcn = m.cell("Sports", s.row, gc)
            if gval is not None and gcn is not None:
                grps = {ops.enum_norm(g.en): g for g in m.group_rows()}
                if ops.enum_norm(gval) not in grps:
                    self.add("GRP-004", "error", "Sports", f"V{s.row}", gval,
                             f"en name of group 不存在于 sport_group.A（含 {gcn!r}）")
        # 产品列检查
        try:
            pcols, pnames = m.sports_product_columns()
        except Exception:
            return
        ws = m.ws("Sports")
        for i, c in enumerate(pcols):
            cnt = 0
            for r in range(3, ws.max_row + 1):
                if ws.cell(row=r, column=3).value is None and ws.cell(row=r, column=1).value is None:
                    continue
                v = ws.cell(row=r, column=c).value
                if v is None:
                    continue
                sv = str(v)
                if sv.strip() != sv:
                    self.add("PROD-001", "warning", "Sports", f"{chr(64 + c)}{r}", sv,
                             "产品列含首尾空白，生成器按真值判断会误视为支持")
                if sv == "Yes":
                    cnt += 1
                else:
                    self.add("PROD-002", "warning", "Sports", f"{chr(64 + c)}{r}", sv,
                             "产品列非规范值(应为 Yes 或空)，当前脚本按真值判定可能误支持")
            hdr = ws.cell(row=2, column=c).value
            try:
                hcnt = int(hdr)
            except (TypeError, ValueError):
                hcnt = None
            if hcnt is not None and hcnt != cnt:
                self.add("PROD-003", "error", "Sports", f"{chr(64 + c)}2", hdr,
                         f"产品列计数头={hdr} 与实际 Yes 数 {cnt} 不一致（影响 sport_type_in_{pnames[i]}.h 自查）")

    # ---------- sport_group ----------
    def _check_group(self):
        m = self.m
        rows = m.group_rows()
        seen_en, seen_cn = {}, {}
        for g in rows:
            tag = f"row{g.row}"
            if not g.en:
                self.add("GRP-002", "error", "sport_group", f"A{g.row}", g.en, "英文 group 名为空")
                continue
            try:
                enum = ops.group_to_enum(g.en)
            except ops.OpError as e:
                self.add("GRP-002", "error", "sport_group", f"A{g.row}", g.en, str(e))
                continue
            if enum in seen_en:
                self.add("GRP-002", "error", "sport_group", f"A{g.row}", g.en,
                         f"group 转枚举与 {seen_en[enum]} 重复 → {enum}")
            else:
                seen_en[enum] = tag
            if not g.cn:
                self.add("GRP-003", "error", "sport_group", f"B{g.row}", g.cn, "中文 group 名为空")
            elif g.cn in seen_cn:
                self.add("GRP-005", "warning", "sport_group", f"B{g.row}", g.cn,
                         f"同一英文 group 对应多个中文名（首见 {seen_cn[g.cn]}）")
            else:
                seen_cn[g.cn] = tag

    # ---------- 矩阵对位 ----------
    def _check_matrix_alignment(self):
        m = self.m
        try:
            group_keys = [ops.enum_norm(g.en) for g in m.group_rows()]
        except Exception:
            return
        # sport sensor
        sl = m.sensor_layout()
        if sl["group_cols"]:
            actual = [ops.enum_norm(x) for x in sl["group_names"]]
            self._align("sport sensor", actual, group_keys)
        # code_attr_*（group 列区）
        for t in m.code_attr_sheet_list():
            if t not in m.wb.sheetnames:
                self.add("CAT-001", "error", "code_attr_product", "-", t,
                         f"清单中的表 {t} 在工作簿中不存在（生成脚本将 KeyError）")
                continue
            lay = m.code_attr_layout(t)
            actual = [ops.enum_norm(x) for x in lay["group_names"]]
            self._align(t, actual, group_keys)

    def _align(self, sheet, actual, expect):
        if actual == expect:
            return
        if len(actual) != len(expect):
            self.add("ALN-001", "error", sheet, "-",
                     f"{len(actual)}列 vs sport_group {len(expect)}行",
                     "矩阵列数量与 sport_group 行数不一致，生成器按列序映射 group 将错位。")
            return
        diff = [f"{a}?={e}" for a, e in zip(actual, expect) if a != e]
        if diff:
            self.add("ALN-001", "info", sheet, "-", "；".join(diff[:5]),
                     "列数量一致但个别列名与 sport_group 不对应（生成器按列序工作，仅提示名称规范化）。")

    # ---------- sensor ----------
    def _check_sensor(self):
        m = self.m
        ws = m.ws("sport sensor")
        for r, key in ((3, "gps"), (4, "hr"), (5, "baro"), (6, "gyro")):
            for c in range(4, ws.max_column + 1):
                if ws.cell(row=1, column=c).value is None:
                    break
                v = ws.cell(row=r, column=c).value
                if v is not None and str(v).strip() != "" and str(v).strip() != "yes":
                    self.add("SEN-001", "warning", "sport sensor", f"{chr(64 + c)}{r}", v,
                             f"{key} 列值建议统一为小写 'yes'（当前生成器会先 lower() 再比较，大写不报错但不符合规范）")

    # ---------- distance fusion ----------
    def _check_distance(self):
        m = self.m
        ws = m.ws("distance fusion")
        for c in range(2, ws.max_column + 1):
            if ws.cell(row=1, column=c).value is None:
                break
            v = ws.cell(row=5, column=c).value
            if v is None or str(v).strip() == "":
                self.add("DST-001", "info", "distance fusion", f"{chr(64 + c)}5", v,
                         "算法名空（不产生枚举；若属说明性文本请确认）")

    # ---------- code_attr_* ----------
    def _check_code_attr(self):
        m = self.m
        for t in m.code_attr_sheet_list():
            if t not in m.wb.sheetnames:
                continue
            try:
                lay = m.code_attr_layout(t)
            except Exception as e:
                self.add("ATTR-004", "error", t, "-", "-", f"边界识别失败：{e}")
                continue
            rows = m.attr_rows(t)
            seen_id, seen_en = {}, {}
            for a in rows:
                tag = f"row{a.row}"
                if a.en_attr_name is None or not ops.norm_key(a.en_attr_name):
                    self.add("ATTR-002", "error", t, f"C{a.row}", a.en_attr_name, "en_attr_name 为空")
                else:
                    k = ops.norm_key(a.en_attr_name)
                    if k in seen_en:
                        self.add("ATTR-002", "error", t, f"C{a.row}", a.en_attr_name,
                                 f"en_attr_name 重复（首见 {seen_en[k]}）")
                    else:
                        seen_en[k] = tag
                if a.attr_id is None:
                    self.add("ATTR-003", "warning", t, f"A{a.row}", a.attr_id, "attr id 缺失")
                elif a.attr_id in seen_id:
                    self.add("ATTR-001", "error", t, f"A{a.row}", a.attr_id,
                             f"attr id 重复（首见 {seen_id[a.attr_id]}）")
                else:
                    seen_id[a.attr_id] = tag
                if not a.describe:
                    self.add("ATTR-003", "warning", t, f"B{a.row}", a.describe, "attr describe 为空")
                # 单侧矩阵：产品全空但 group 有值 / 反之
                prod_any = any(str(x).strip() == "Yes" for x in a.product.values())
                group_any = any(str(x).strip() == "Yes" for x in a.group.values())
                if (prod_any or group_any) and not (prod_any and group_any):
                    self.add("MAT-001", "warning", t, f"A{a.row}", a.attr_id,
                             "产品侧与运动/group 侧只配置了一侧：生成映射取交集，将全部为 false，请人工确认是否业务预期")

    # ---------- Sports 心率/站立 ----------
    def _check_hr_standup(self):
        m = self.m
        hr_c = m.field_col("Sports", "type of hr algo")
        st_c = m.field_col("Sports", "standup sensitivity")
        if not st_c:
            return
        for s in m.sports_rows():
            v = m.cell("Sports", s.row, st_c)
            if v is None or str(v).strip() == "":
                self.add("STN-001", "warning", "Sports", f"P{s.row}", v,
                         "standup sensitivity 为空（生成 sport_standup_sens_auto 时会告警）")
            if hr_c:
                hv = m.cell("Sports", s.row, hr_c)
                if hv is None or str(hv).strip() == "":
                    self.add("HR-001", "info", "Sports", f"K{s.row}", hv,
                             "心率算法为空（若沿用默认逻辑请人工确认）")

    # ---------- run ----------
    def run(self) -> list[Finding]:
        self.findings = []
        self._check_sports()
        self._check_group()
        self._check_matrix_alignment()
        self._check_sensor()
        self._check_distance()
        self._check_code_attr()
        self._check_hr_standup()
        return self.findings

    def summary(self) -> str:
        errs = sum(1 for f in self.findings if f.severity == "error")
        warns = sum(1 for f in self.findings if f.severity == "warning")
        infos = sum(1 for f in self.findings if f.severity == "info")
        return f"检查完成：error={errs} warning={warns} info={infos}"


def check_file(xlsx_path: str) -> list[Finding]:
    with RULES_PATH.open(encoding="utf-8") as stream:
        rules = yaml.safe_load(stream)
    m = WorkbookModel(xlsx_path)
    try:
        return Checker(m, rules).run()
    finally:
        m.close()
