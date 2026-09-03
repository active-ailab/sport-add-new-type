# sport-add-new-type

Owner: cs-dongqi@zepp.com  
Organization: Active.Bu

本仓库用于承载新增运动类型的自动化工具。当前已交付第一阶段 CLI：`sport-proto`，用于为 `packages/services/sport` 下的 nanopb schema 串行生成、预览与受控回写 `.pb.c/.pb.h`。

另提供 `sport-config`：对固件工程的 `sports.xlsx` 做变动门禁和规则校验，并直接调用既有 `sport_gen.py` 生成代码。

## sport-config

在代码 repo 的任意子目录执行；工具会向上查找包含 `.repo/` 的根目录。`-r` 仅在需要显式指定其他工程时使用。

```bash
# 无 XLSX 改动时输出 SKIP 并成功结束；有改动时执行规则校验
sport-config -c

# 先 check；通过后直接运行既有 sport_gen.py 写入其固定输出目录
sport-config -g

# 指定工程
sport-config -check -r /path/to/firmware-repo
```

`check` 可写为 `-c`、`-C`、`-check` 或 `check`；`gen` 同理可写为 `-g`、`-G`、`-gen` 或 `gen`。动作名称大小写不敏感。

规则唯一来源为 `rules/sports_xlsx_rules.yaml`。`check` 不检查 `sports.csv`、`sports_md` 或产品 Feature 表；`gen` 保留 `sport_gen.py` 对 `sports_md` 的既有更新行为。

## 使用流程

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
├── cli/                    # sport-proto CLI 与单元测试
├── install.sh              # 本地安装脚本
└── .github/workflows/      # 飞书通知工作流
```
