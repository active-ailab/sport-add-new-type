# sport-add-new-type

Owner: cs-dongqi@zepp.com  
Organization: Active.Bu

本仓库用于承载新增运动类型的自动化工具，当前已完成并提供以下两个工具：

- `sport-proto`：为 `packages/services/sport` 下的 nanopb schema 串行生成、预览与受控回写 `.pb.c/.pb.h`。
- `sport-config`：统一提供 `sports.xlsx` 校验、XML 报告、既有 `sport_gen.py` 生成和本地 Web 配置页面。

## sport-config

`sport-config` 是 `sports.xlsx` 的统一入口：命令行和 Web 使用同一套检查、生成及 YAML 规则，不再分别维护两套规则逻辑。

### 安装

推荐在本仓库创建隔离环境并安装 CLI，安装过程会同时安装 Web 所需的 Flask、规则解析和 XLSX 依赖。

```bash
cd /home/zepp/workspace/active-lab/sport-add-new-type
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install ./cli
```

也可使用仓库中的 `install.sh` 创建命令链接；此方式使用系统 `python3`，须预先安装 `cli/pyproject.toml` 声明的依赖。

### 目标 XLSX 的定位

工具在 `-r` 指定目录或当前命令目录中按以下顺序定位目标：

1. 目录下直接存在的 `sports.xlsx`。
2. 向上找到含 `.repo/` 的固件仓根目录后，使用 `framework/engine/sportEngine/common/sports.xlsx`。

`-r` 只决定待检查、生成或打开的 XLSX 的解析起点；它不控制 XML 报告目录。无法定位文件时，`-a` 会打开原有的文件选择页面；`-c` 和 `-g` 会明确报错，不会修改任何文件。

### 命令行用法

```bash
# 检查并在当前命令目录写出 XML 报告
sport-config -c

# XML 报告写入指定目录；该路径仅属于 -c，不是 XLSX 路径
sport-config -c /path/to/report-dir

# 检查目标由 -r 指定，报告目录仍由 -c 后的位置参数指定；两者可同时使用
sport-config -c /path/to/report-dir -r /path/to/firmware-repo

# 先统一检查；通过后直接运行既有 sport_gen.py
sport-config -g
sport-config -g -r /path/to/firmware-repo

# 打开本地 Web；找不到目标时显示已有的选择文件页面
sport-config -a
sport-config add -r /path/to/firmware-repo
```

支持的动作及别名如下：

| 功能 | 写法 | 结果 |
| --- | --- | --- |
| 检查 | `-c`、`-check`、`check` | 运行统一检查并写出 XML 报告。标准输出仅报告成功或失败及报告路径；存在错误时退出码为 `2`。 |
| 生成 | `-g`、`-gen`、`gen` | 先运行统一检查；没有错误才调用既有 `sport_gen.py`。 |
| Web | `-a`、`add` | 启动本地 Web 页面；页面中的检查、导出和生成均调用与 CLI 相同的服务。 |

动作名称大小写不敏感，例如 `-C`、`-G` 均可使用。`-c` 的可选路径只表示报告输出目录；`-r` 的可选路径只表示目标 XLSX 的解析起点，两者不是互斥参数，也不是同一个功能。XML 文件名固定为 `sport-config-check-report.xml`；未传报告目录时，写入执行命令时的当前目录。

当前版本已完成内部编辑能力的功能拆分，但尚未对外提供 `-e` / `edit` 命令入口。

### Web 页面

`sport-config -a` 保留原 `sports-xlsx-tool` 的全部页面和编辑功能，并由 `sport-config` 统一启动。页面规则检查、XML 导出和生成均复用命令行服务：

- 检查报告页显示与 `-c` 一致的结果，并可通过“导出 XML”下载报告。
- 页面导航右侧提供一个独立的全局“生成”按钮；它不是列表项或各列表的重复按钮，执行与 `-g` 相同的检查后生成流程。
- 检查结果颜色保持一致：`error` 标红、`warning` 标黄，`info` 不设置背景色。

### 规则、报告与生成边界

唯一规则文件为 `cli/src/sport_config/rules/sports_xlsx_rules.yaml`。其中同时承载原 `sport-config` 的 XLSX schema 检查规则和原 Web 的数据契约检查规则；Web 检查页与 `-c` 使用完全相同的规则、严重级别和 XML 格式。

检查范围仅为 `sports.xlsx`：不会检查 `sports.csv`、`sports_md` 或产品 Feature 表。生成仍沿用既有 `sport_gen.py`，其对 `sports_md` 的既有更新行为不变；因此请在生成前确认目标仓和 XLSX 均为预期对象。

## sport-proto

1. 在代码 repo 的任意子目录执行 `sport-proto -l`，查看实际存在的 Profile。
2. 将列表中的 Profile 传给 `-p`，先预览生成差异和 `/tmp` 产物。
3. 确认差异后，追加 `-w` 从临时产物覆盖目标 `.pb.c/.pb.h`。

```bash
# 1. 查询可用 Profile
sport-proto -l

# 2. 预览单个 Profile
sport-proto -p PHN

# 3. 确认后回写
sport-proto -p PHN -w

# 多个 Profile 会按输入顺序逐个串行处理
sport-proto -p PHN -p phn_plan
```

运行位置可以是代码 repo 的任意子目录；工具会向上查找包含 `.repo/` 的根目录。

## 仓库通知

- 推送到 `main` 或 `master` 时发送飞书通知。
- 支持手动触发 `Feishu Notify` 工作流。
- 复用统一的 `reusable-feishu-notify.yml` 发送仓库变更信息。

## 目录结构

```text
sport-add-new-type/
├── cli/
│   ├── bin/                # sport-config、sport-proto 命令入口
│   ├── src/
│   │   ├── sport_config/   # sport-config.py 主入口、Web、XLSX 与规则
│   │   └── sport_proto/    # sport-proto.py 主入口
│   ├── tests/              # CLI 单元测试
│   └── pyproject.toml      # CLI 安装与依赖配置
├── VERSION                 # 仓库版本
├── install.sh              # 本地安装脚本
└── .github/workflows/      # 飞书通知工作流
```
