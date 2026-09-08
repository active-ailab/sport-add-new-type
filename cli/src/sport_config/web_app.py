# -*- coding: utf-8 -*-
"""
sports-xlsx-tool Web 界面（本地只监听 127.0.0.1）。

启动：
  .venv/bin/python web/app.py [--file /path/to/sports.xlsx] [--port 8500]
浏览器访问 http://127.0.0.1:8500

每次写操作前由前端先请求 /api/plan 展示跨 Sheet 变更 diff，确认后再 /api/apply。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, render_template, request

from . import xlsx_editor as ops
from .xlsx_model import WorkbookModel
from .xlsx_editor import OpError, SportAddSpec
from .xlsx_repository import save_workbook
from .xlsx_check import check_file
from .xlsx_generate import generate
from .xlsx_target import TargetError, selected_target
from .xml_report import report_bytes

# 目标文件初始为空：启动后由用户在页面自行选择，或通过 --file 显式指定。
# 代码内不写死任何用户/分支的绝对路径。
XLSX_PATH = None
TARGET = None
_generation_lock = threading.Lock()
_generation_state_lock = threading.Lock()
_generation_active = False
_generation_cancelled = False
_generation_process = None
app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
# 前端模板改动即时生效，无需重启服务
app.config["TEMPLATES_AUTO_RELOAD"] = True

# 不依赖目标文件的接口白名单
_FILE_FREE_APIS = {"/api/open", "/api/list-dir", "/api/files"}


def _begin_generation():
    global _generation_active, _generation_cancelled, _generation_process
    if not _generation_lock.acquire(blocking=False):
        raise TargetError("已有生成任务正在运行")
    with _generation_state_lock:
        _generation_active = True
        _generation_cancelled = False
        _generation_process = None


def _finish_generation():
    global _generation_active, _generation_process
    with _generation_state_lock:
        _generation_active = False
        _generation_process = None
    _generation_lock.release()


def _set_generation_process(process):
    global _generation_process
    with _generation_state_lock:
        _generation_process = process
        cancelled = _generation_cancelled
    if process is not None and cancelled and process.poll() is None:
        process.terminate()


def _generation_was_cancelled():
    with _generation_state_lock:
        return _generation_cancelled


@app.before_request
def _require_file():
    if request.path.startswith("/api") and request.path not in _FILE_FREE_APIS:
        if XLSX_PATH is None:
            return jsonify({"ok": False, "code": "NEED_FILE",
                            "error": "尚未选择目标文件，请先在页面顶部选择 sports.xlsx"})
        if not os.path.exists(XLSX_PATH):
            return jsonify({"ok": False, "code": "NEED_FILE",
                            "error": f"目标文件不存在（可能已移动/分支已删除）: {XLSX_PATH}"})


def _model():
    return WorkbookModel(XLSX_PATH)


# ---------------------------------------------------------------- helpers
def _info():
    m = _model()
    try:
        rows = m.sports_rows()
        pcols, pnames = m.sports_product_columns()
        return {
            "file": m.path,
            "sports": len(rows),
            "sport_id_max": m.sport_max_id(),
            "groups": len(m.group_rows()),
            "products": pnames,
            "codeattr_sheets": m.code_attr_sheet_list(),
            "sheets": m.wb.sheetnames,
        }
    finally:
        m.close()


def _sport_row_dict(m, s):
    prod = {k: (str(v).strip() == "Yes") for k, v in s.product_support.items()
            if v is not None and str(v).strip() != ""}
    hr_c = m.field_col("Sports", "type of hr algo")
    st_c = m.field_col("Sports", "standup sensitivity")
    wr_c = m.field_col("Sports", "wrist act type")
    return {"fw_id": s.fw_id, "row": s.row, "cn": s.cn_name, "en": s.en_name,
            "app": s.app_value, "sync": s.sync_key,
            "group_en": s.group_en, "group_cn": s.group_cn,
            "hr_algo": m.cell("Sports", s.row, hr_c) if hr_c else None,
            "standup": m.cell("Sports", s.row, st_c) if st_c else None,
            "wrist": m.cell("Sports", s.row, wr_c) if wr_c else None,
            "products": prod}


def _op_result(op: dict):
    """执行一个操作（不落盘），返回 (plan, extra)。"""
    action = op.get("action")
    p = op.get("p", {})
    m = _model()
    try:
        if action == "sport_add":
            spec = SportAddSpec(
                cn=p.get("cn", ""), en=p.get("en", ""),
                fw_id=p.get("fw_id"), app_value=p.get("app"),
                sync_key=p.get("sync"), group_en=p.get("group_en"),
                group_cn=p.get("group_cn"), template_fw_id=p.get("template"),
                products=p.get("products"),   # None|'copy'|[names]
                hr_algo=p.get("hr"), standup=p.get("standup"), wrist=p.get("wrist"))
            plan = ops.sport_add(m, spec)
        elif action == "sport_update":
            plan = ops.sport_update(m, p.get("fw_id"), cn=p.get("cn"), en=p.get("en"),
                                    app_value=p.get("app"), sync_key=p.get("sync"),
                                    hr_algo=p.get("hr"), standup=p.get("standup"),
                                    wrist=p.get("wrist"), group_cn=p.get("group_cn"),
                                    group_en=p.get("group_en"))
        elif action == "sport_delete":
            plan = ops.sport_delete(m, p.get("fw_id"))
        elif action == "sport_product":
            plan = ops.sport_product_set(m, p.get("fw_id"), p.get("product"),
                                         bool(p.get("enable")))
        elif action == "group_add":
            plan = ops.group_add(m, p.get("en", ""), p.get("cn", ""),
                                 code_attr_tables=p.get("tables"))
        elif action == "group_rename":
            plan = ops.group_rename(m, old_en=p.get("old_en"), old_cn=p.get("old_cn"),
                                    new_en=p.get("new_en"), new_cn=p.get("new_cn"),
                                    code_attr_tables=p.get("tables"))
        elif action == "group_delete":
            plan = ops.group_delete(m, en=p.get("en"), cn=p.get("cn"),
                                    code_attr_tables=p.get("tables"))
        elif action == "attr_add":
            plan = ops.attr_add(m, p.get("describe", ""), p.get("en", ""),
                                peripheral=p.get("peripheral"),
                                code_attr_tables=p.get("tables"), attr_id=p.get("attr_id"),
                                products=p.get("products"), groups=p.get("groups"))
        elif action == "attr_update":
            plan = ops.attr_update(m, p.get("en"), describe=p.get("describe"),
                                   peripheral=p.get("peripheral"),
                                   products=p.get("products"), groups=p.get("groups"),
                                   code_attr_tables=p.get("tables"))
        elif action == "attr_delete":
            plan = ops.attr_delete(m, p.get("en"), code_attr_tables=p.get("tables"))
        elif action == "product_add":
            plan = ops.product_add(m, p.get("name", ""), code_attr_tables=p.get("tables"),
                                   new_code_attr_table=p.get("new_table"))
        elif action == "product_delete":
            plan = ops.product_delete(m, p.get("name", ""), code_attr_tables=p.get("tables"))
        elif action == "refresh_counts":
            plan = ops.sports_refresh_counts(m)
        else:
            raise OpError(f"未知操作 {action}")
        return plan
    finally:
        m.close()


# ---------------------------------------------------------------- routes
@app.get("/")
def index():
    return render_template("index.html", file=XLSX_PATH)


@app.get("/api/files")
def api_files():
    """当前状态查询：目标文件是否已选择。不扫描任何固定目录。"""
    return jsonify({"ok": True, "data": {"current": XLSX_PATH}})


@app.get("/api/list-dir")
def api_list_dir():
    """目录浏览：给定一个目录，列出其子目录与其中的 sports.xlsx（仅该文件名）。
    供用户在文件选择面板中导航到自己的 checkout，不写死任何路径。"""
    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify({"ok": False, "error": "请提供目录路径"})
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        return jsonify({"ok": False, "error": f"目录不存在: {path}"})
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return jsonify({"ok": False, "error": f"无权限读取: {path}"})
    subdirs, files = [], []
    for name in entries:
        full = os.path.join(path, name)
        if os.path.isdir(full):
            if not name.startswith("."):
                subdirs.append(name)
        elif name == "sports.xlsx":
            files.append(full)
    return jsonify({"ok": True, "data": {"dir": path, "subdirs": subdirs, "files": files}})


@app.post("/api/open")
def api_open():
    """选择/切换当前目标文件。仅接受文件名严格为 sports.xlsx 的本地文件。"""
    global XLSX_PATH, TARGET
    body = request.get_json(force=True) or {}
    f = (body.get("file") or "").strip()
    if not f:
        return jsonify({"ok": False, "error": "未提供文件路径"})
    f = os.path.abspath(os.path.expanduser(f))
    if os.path.basename(f) != "sports.xlsx":
        return jsonify({"ok": False, "error": f"仅支持操作名为 sports.xlsx 的文件（当前: {os.path.basename(f)}）"})
    try:
        TARGET = selected_target(f)
    except TargetError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    XLSX_PATH = str(TARGET.xlsx)
    return jsonify({"ok": True, "data": {"file": XLSX_PATH}})


@app.get("/api/info")
def api_info():
    try:
        return jsonify({"ok": True, "data": _info()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.get("/api/meta")
def api_meta():
    m = _model()
    try:
        return jsonify({"ok": True, "data": {
            "groups": [{"en": g.en, "cn": g.cn} for g in m.group_rows()],
            "products": m.sports_product_columns()[1],
            "codeattr_sheets": m.code_attr_sheet_list(),
            "sensor": m.sensor_layout(),
            "distance": m.distance_layout(),
        }})
    finally:
        m.close()


@app.get("/api/sports")
def api_sports():
    m = _model()
    try:
        q = (request.args.get("q") or "").strip().lower()
        rows = []
        for s in m.sports_rows():
            d = _sport_row_dict(m, s)
            if q and q not in (d["cn"] or "").lower() and q not in (d["en"] or "").lower():
                continue
            rows.append(d)
        return jsonify({"ok": True, "data": rows})
    finally:
        m.close()


@app.get("/api/groups")
def api_groups():
    m = _model()
    try:
        sports = m.sports_rows()
        data = []
        for g in m.group_rows():
            used = [s for s in sports if s.group_en is not None
                    and ops.enum_norm(s.group_en) == ops.enum_norm(g.en)]
            data.append({"en": g.en, "cn": g.cn, "row": g.row, "used": len(used)})
        return jsonify({"ok": True, "data": data})
    finally:
        m.close()


@app.get("/api/products")
def api_products():
    m = _model()
    try:
        locations = {}
        for table in m.code_attr_sheet_list():
            for product in m.code_attr_layout(table)["product_names"]:
                locations.setdefault(str(product).casefold(), []).append(table)
        return jsonify({"ok": True, "data": [
            {"name": product, "tables": locations.get(str(product).casefold(), [])}
            for product in m.sports_product_columns()[1]
        ]})
    finally:
        m.close()


@app.get("/api/attrs")
def api_attrs():
    m = _model()
    try:
        table = request.args.get("table") or "code_attr_sport"
        q = (request.args.get("q") or "").strip().lower()
        page = int(request.args.get("page") or 1)
        size = int(request.args.get("size") or 50)
        if table not in m.wb.sheetnames:
            return jsonify({"ok": False, "error": f"表 {table} 不存在"})
        lay = m.code_attr_layout(table)
        rows = []
        for a in m.attr_rows(table):
            if q and q not in (a.describe or "").lower() and q not in (a.en_attr_name or "").lower():
                continue
            rows.append({
                "attr_id": a.attr_id, "row": a.row, "describe": a.describe,
                "en": a.en_attr_name, "peripheral": a.peripheral,
                "products": {k: (str(v).strip() == "Yes") for k, v in a.product.items()
                             if v is not None and str(v).strip() != ""},
                "groups": {k: (str(v).strip() == "Yes") for k, v in a.group.items()
                           if v is not None and str(v).strip() != ""},
            })
        total = len(rows)
        start = (page - 1) * size
        return jsonify({"ok": True, "data": {
            "table": table, "products": lay["product_names"],
            "groups": lay["group_names"], "total": total, "page": page,
            "items": rows[start:start + size]}})
    finally:
        m.close()


@app.get("/api/check")
def api_check():
    try:
        result = check_file(XLSX_PATH)
        return jsonify({"ok": True, "data": [
            {"severity": f.severity, "rule_id": f.rule_id, "sheet": f.sheet,
             "cell": f.cell, "value": f.value, "message": f.message, "impact": f.impact}
            for f in result.findings]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.get("/api/check/export.xml")
def api_check_export():
    from flask import Response
    try:
        return Response(report_bytes(check_file(XLSX_PATH)), mimetype="application/xml", headers={"Content-Disposition": "attachment; filename=sport-config-check-report.xml"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.post("/api/generate")
def api_generate():
    begun = False
    try:
        _begin_generation()
        begun = True
        if TARGET is None:
            raise TargetError("请先选择目标 sports.xlsx")
        result = check_file(XLSX_PATH)
        if result.error_count:
            raise TargetError("sports.xlsx check failed: {} error(s)".format(result.error_count))
        return jsonify({"ok": True, "data": {
            "diff": generate(TARGET, on_process=_set_generation_process,
                             is_cancelled=_generation_was_cancelled)}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    finally:
        if begun:
            _finish_generation()


@app.post("/api/generate/cancel")
def api_generate_cancel():
    global _generation_cancelled
    with _generation_state_lock:
        if not _generation_active:
            return jsonify({"ok": True, "data": {"active": False,
                                                    "message": "当前没有正在生成的任务"}})
        _generation_cancelled = True
        process = _generation_process
    if process is not None and process.poll() is None:
        process.terminate()
    return jsonify({"ok": True, "data": {"active": True, "message": "已请求中断生成"}})


@app.post("/api/plan")
def api_plan():
    op = request.get_json(force=True)
    try:
        plan = _op_result(op)
        return jsonify({"ok": True, "data": {"describe": plan.describe(),
                                             "count": len(plan.items)}})
    except OpError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"})


@app.post("/api/apply")
def api_apply():
    op = request.get_json(force=True)
    try:
        plan = _op_result(op)
        m = _model()
        try:
            plan.apply(m.wb)
            # info = save_workbook(m.wb, XLSX_PATH, backup=True)
            info = save_workbook(m.wb, XLSX_PATH, backup=False)
        finally:
            m.close()
        return jsonify({"ok": True, "data": {"describe": plan.describe(),
                                             "backup": info.get("backup")}})
    except OpError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"})


def run(target=None, host="127.0.0.1", port=8500):
    global XLSX_PATH, TARGET
    TARGET = target
    XLSX_PATH = str(target.xlsx) if target else None
    print(f"访问: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)


def main():
    global XLSX_PATH, TARGET
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="初始目标 sports.xlsx（可选；不传则在页面自行选择）")
    ap.add_argument("--port", type=int, default=8500)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    if a.file:
        try:
            TARGET = selected_target(a.file)
            XLSX_PATH = str(TARGET.xlsx)
        except TargetError as exc:
            print(f"错误：{exc}")
            sys.exit(1)
    else:
        # 可选：若工具目录存在 config.json 且含 xlsx 字段则作为初始默认（团队可自建，未强制）
        cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
        if os.path.exists(cfg):
            try:
                v = json.load(open(cfg)).get("xlsx")
                if v and os.path.exists(os.path.abspath(os.path.expanduser(v))):
                    XLSX_PATH = os.path.abspath(os.path.expanduser(v))
            except Exception:
                pass
    if XLSX_PATH:
        print(f"初始文件: {XLSX_PATH}")
    else:
        print("未指定初始文件：请在页面顶部选择 sports.xlsx（或启动时 --file 指定）")
    print(f"访问: http://{a.host}:{a.port}")
    run(TARGET, a.host, a.port)


if __name__ == "__main__":
    main()
