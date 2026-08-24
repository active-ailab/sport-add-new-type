# sport-proto 第一阶段 CLI 设计方案

Owner: cs-dongqi@zepp.com  
Organization: Active.Bu

## 1. 目标与范围

第一阶段仅实现 `sport-proto`，用于运动服务 protobuf 的 nanopb 生成、预览及受控写回。

- 项目目录：`/home/zepp/workspace/active-lab/sport-add-new-type`。
- 代码基线由运行时解析的 repo 根目录决定，例如 `/home/zepp/workspace/abs-stable`。
- 业务范围仅限 `<repo>/packages/services/sport`。
- nanopb 生成器路径：`<repo>/framework/utils/nanopb/generator/nanopb_generator.py`。

## 2. 项目结构

目录参考 `active-build-script` 的 CLI 组织方式，并保持单命令的最小结构：

```text
sport-add-new-type/
├── README.md
├── VERSION
├── install.sh
└── cli/
    ├── pyproject.toml
    ├── bin/
    │   └── sport-proto
    ├── src/
    │   └── sport_proto.py
    └── tests/
        └── test_sport_proto.py
```

安装后命令为：

```bash
sport-proto [参数]
```

## 3. Repo 根目录发现

`-r` 是可选参数。

1. 有 `-r` 时，从指定路径开始向上查找；没有时，从当前工作目录开始向上查找。
2. 仅当某级目录存在 `.repo/` 时，该目录才被认定为代码 repo 根目录。
3. 根目录确定后，CLI 再验证以下路径：

```text
packages/services/sport/
framework/utils/nanopb/generator/nanopb_generator.py
```

4. 未找到 `.repo/`，或上述任一路径缺失，命令失败且不生成、不写回任何文件。

## 4. 命令与短参

全部使用单层参数。所有短参大小写不敏感，例如 `-r` 与 `-R`、`-l` 与 `-L` 等价。

| 短参 | 长参 | 参数 | 说明 |
|---|---|---|---|
| `-h` | `--help` | 无 | 显示帮助。 |
| `-v` | `--version` | 无 | 显示 CLI 版本。`-V` 等价。 |
| `-r` | `--repo` | `<path>` | 可选；指定 repo 根目录或其中的子目录。 |
| `-l` | `--list` | 无 | 列出当前 repo 实际存在的 `.proto` 相对路径、对应 Profile 及数量；Profile 按最长值左对齐。 |
| `-p` | `--profile` | `<name>` | 选择一个 profile；值为对应 `.proto` 去掉后缀的文件名，可重复。 |
| `-a` | `--all` | 无 | 选择当前 repo 中实际存在且受支持的全部 sport proto。 |
| `-w` | `--write` | 无 | 明确把临时生成产物替换回 repo 内的 `.pb.c/.pb.h`。 |

约束：

- `-p` 与 `-a` 互斥。
- `-w` 必须与 `-p` 或 `-a` 一起使用。
- `-l` 不能与 `-p`、`-a`、`-w` 同时使用。

## 5. 默认与生成行为

不带 `-p`、`-a`、`-l` 时，CLI 只输出：

- 自动识别的 repo 根目录；
- nanopb 生成器路径；
- `protoc`、Python protobuf 版本；
- 当前实际存在的 sport proto 数量；
- 后续命令示例。

指定 `-p` 或 `-a` 时，CLI 串行处理所选 profile，并输出与 repo 现有文件的 diff。每个 profile 独立完成一次生成与清理后，才开始下一个 profile。默认不写回：

```bash
sport-proto -p PHN
sport-proto -p PHN -p phn_plan -p phn_record
sport-proto -a
```

只有指定 `-w` 才允许写回：

```bash
sport-proto -p PHN -w
sport-proto -a -w
```

每次生成前都会自动检查 repo、生成器、`protoc` 和 Python protobuf 的可用性；检查失败时不能写回。

## 6. nanopb 生成执行与清理

生成器目录是一次调用期间的受控工作区：

```text
<repo>/framework/utils/nanopb/generator/
```

对每一个选定 profile，执行顺序固定如下；多个 `-p` 与 `-a` 均按此流程逐个串行执行，生成器目录任一时刻只处理一个 profile：

1. 确认生成器目录中不存在与本次 profile 同名的 `.proto`、`.options`、`.pb.c`、`.pb.h`；存在即失败，避免覆盖或删除已有文件。
2. 将原始 `.proto` 和存在的 `.options` 复制到生成器目录。
3. 切换到生成器目录，执行 `nanopb_generator.py <文件名>.proto`。
4. 将生成的 `.pb.c`、`.pb.h` 移动到 `/tmp` 下为本次调用创建的专用临时比对目录。
5. 在 `finally` 清理生成器目录中由本次调用复制的输入和遗留生成物，确保脚本目录恢复干净。
6. 将临时比对目录产物与 profile 的目标 `.pb.c/.pb.h` 做 diff；指定 `-w` 时才从临时目录原子覆盖目标文件。
7. 未指定 `-w` 时，指令结束输出 `/tmp` 临时目录中本次生成的 `.pb.c`、`.pb.h` 路径；指定 `-w` 并成功覆盖时，输出最终目标 `.pb.c`、`.pb.h` 的相对路径和绝对路径。

原始 `.proto` 和 `.options` 始终保留在 `<repo>/packages/services/sport` 的业务目录中；生成器目录只保留脚本自身的常驻文件。

## 7. Profile 输入输出映射

以下路径均相对 repo 根目录 `<repo>`。输入由 `.proto` 与同名可选 `.options` 构成；输出是 nanopb 的 `.pb.c/.pb.h`。

| Profile | 输入 proto | 可选 options | 输出 C | 输出 H |
|---|---|---|---|---|
| `sport_settings` | `packages/services/sport/settings/sport_settings.proto` | `packages/services/sport/settings/sport_settings.options` | `packages/services/sport/settings/sport_settings.pb.c` | `packages/services/sport/settings/sport_settings.pb.h` |
| `equipment` | `packages/services/sport/src/equipment/equipment.proto` | `packages/services/sport/src/equipment/equipment.options` | `packages/services/sport/src/equipment/equipment.pb.c` | `packages/services/sport/include/equipment/equipment.pb.h` |
| `lactate_data` | `packages/services/sport/src/gomore_service/proto/lactate_data.proto` | `packages/services/sport/src/gomore_service/proto/lactate_data.options` | `packages/services/sport/src/gomore_service/proto/lactate_data.pb.c` | `packages/services/sport/include/gomore_service/lactate_data.pb.h` |
| `PHN` | `packages/services/sport/src/phn/phn_proto/PHN.proto` | `packages/services/sport/src/phn/phn_proto/PHN.options` | `packages/services/sport/src/phn/phn_proto/PHN.pb.c` | `packages/services/sport/include/phn/PHN.pb.h` |
| `phn_plan` | `packages/services/sport/src/phn/phn_proto/phn_plan.proto` | `packages/services/sport/src/phn/phn_proto/phn_plan.options` | `packages/services/sport/src/phn/phn_proto/phn_plan.pb.c` | `packages/services/sport/include/phn/phn_plan.pb.h` |
| `phn_record` | `packages/services/sport/src/phn/phn_proto/phn_record.proto` | `packages/services/sport/src/phn/phn_proto/phn_record.options` | `packages/services/sport/src/phn/phn_proto/phn_record.pb.c` | `packages/services/sport/include/phn/phn_record.pb.h` |
| `phn_sport_reminder` | `packages/services/sport/src/phn/phn_proto/phn_sport_reminder.proto` | 无 | `packages/services/sport/src/phn/phn_proto/phn_sport_reminder.pb.c` | `packages/services/sport/include/phn/phn_sport_reminder.pb.h` |
| `readiness` | `packages/services/sport/src/readiness/readiness.proto` | 无 | `packages/services/sport/src/readiness/readiness.pb.c` | `packages/services/sport/include/readiness/readiness.pb.h` |
| `sport_data_page` | `packages/services/sport/src/sport_data_page/sport_page_proto/sport_data_page.proto` | `packages/services/sport/src/sport_data_page/sport_page_proto/sport_data_page.options` | `packages/services/sport/src/sport_data_page/sport_page_proto/sport_data_page.pb.c` | `packages/services/sport/include/sport_data_page/sport_data_page.pb.h` |
| `sport_effect` | `packages/services/sport/src/sport_effect.proto` | `packages/services/sport/src/sport_effect.options` | `packages/services/sport/src/sport_effect.pb.c` | `packages/services/sport/include/sport_effect.pb.h` |
| `treadmill_setting` | `packages/services/sport/src/treadmill_setting/treadmill_setting.proto` | 无 | `packages/services/sport/src/treadmill_setting/treadmill_setting.pb.c` | `packages/services/sport/include/treadmill_setting/treadmill_setting.pb.h` |
| `sport_summary` | `packages/services/sport/summary/sport_summary.proto` | `packages/services/sport/summary/sport_summary.options` | `packages/services/sport/summary/sport_summary.pb.c` | `packages/services/sport/summary/sport_summary.pb.h` |

Profile 名称与 `.proto` 的文件名去掉后缀完全一致。`-l` 扫描当前实际存在的 `.proto` 并输出对应 Profile；`-a` 则从映射表中筛选当前实际存在的 profile。

## 8. 第一阶段验收标准

1. 从 repo 内任意子目录可自动向上识别包含 `.repo/` 的根目录。
2. `-l` 输出 `packages/services/sport` 内实际存在的 proto 相对路径及对应 Profile。
3. 生成期间，输入暂存于生成器目录，产物先转存至 `/tmp` 下调用专用临时比对目录。
4. 无论生成成功或失败，生成器目录中由本次调用引入的 `.proto`、`.options`、`.pb.c`、`.pb.h` 都会清理。
5. 选定 profile 默认正确展示 diff，repo 工作区不发生变化。
6. `-w` 仅从临时目录替换该 profile 映射中的 `.pb.c/.pb.h`，不会写入其他路径。
7. 缺失 proto、options 不匹配、生成器失败、版本检查失败时，命令返回失败且不写回。
8. 未指定 `-w` 时，指令结束输出本次 `/tmp` 临时产物路径；指定 `-w` 成功覆盖时，输出最终 `.pb.c/.pb.h` 文件路径。
9. 多个 `-p` 或 `-a` 执行时，每一个 profile 完成后均确认生成器目录干净，再处理下一个 profile。
