# PH6780 Stage 3B：有限 recovery 与搬迁配对 pilot

## 验收结论

**Engineering PASS。Pilot viability PASS。** 10/10 条固定运行完成，B0 重放、
单变量审计、共同随机数、food-coordinate isolation、scalar-only、diffusion=0、
24 步 recovery 上限、状态守恒、保护哈希和资源门槛均通过。C 在所有 seed 中都
实际触发 recovery，episode 记录完整；五对中均至少发现过 B，因此输出足以支持
后续确认实验设计。

**C 的五-seed描述性方向混合，但整体不利于 C。** C 在四个可直接比较的 seed 中
有三个更早发现 B，一个更晚；另一个 seed 中 C 没有发现 B。B0 在 2/5 seeds
完成 B 送达，共 2 次；C 在 1/5 完成，共 1 次。不能据此声称 recovery 有效，
也不能声称它无效；这些 seeds 已在 Stage 3A 观察过，样本很小且没有确认性统计。

当前实现**具备进入 20-seed 确认实验的工程条件**，但本阶段没有运行确认 seeds，
也没有自动进入下一阶段。进入前应由 master 验收协议、指标和这个混合负面 pilot，
并保持 duration=24 与全部 B0 参数不变。

## 冻结实现与审计

起点为 `658e39439a1e94f7ff185d2cefc92bdeba5f19a8`，新分支为
`codex/stage3b-recovery-search-pilot`。规格在任何 Stage 3B 模拟前写入
`docs/STAGE3B_RECOVERY_PILOT_SPEC.md`。B0 仍是公平主 baseline；冻结的 Stage 3A
源码没有修改。C 的唯一动力学变化是 follower 连续两个低信号步骤后，进行最多
24 次局部左右交替 recovery movement，再回到同一 FCRW。

每只 C 蚂蚁仅保存 recovery active/step、anchor heading、initial side 和最后可靠
heading。它每步只读取左右两个 scalar samples。没有 food/nest direction、cell
direction、source identity、全局轨迹或全局场扫描。initial side 由独立的
`SeedSequence([seed, ant_id, 4])` 预生成；B0/C 的初始状态、FCRW、follower noise、
side schedule、环境和信息素参数逐项一致，B0 不读取 side schedule。

seed 2026091701 的 relocation B0 与静态 B0 同时推进到 t=5999：agent
position/heading/role/path/cargo、field hash、ledger、事件和累计指标完全相同；
5,285 条观察事件也与已提交的 Stage 3A 前缀一致。实际第一对的 B0 搬迁前 ledger
再次与 Stage 3A 匹配。证据见 `single_change_audit.json`、
`baseline_prefix_replay.json`、`food_coordinate_isolation.json` 和
`first_pair_audit.json`。

## 五对探索性结果

所有差值均为 **C - B0**。负的发现/送达时间差表示 C 更早；没有事件时不伪造
时间差。capped recovery time 从 t=6000 起算，无 B 送达时固定为 6000。

| Seed | B0 / C 首次发现 B | Δ发现 | B0 / C 首次送达 B | Δcapped time | B0 / C 的 B 送达 | 搬迁前 A 送达 Δ |
|---|---|---:|---|---:|---|---:|
| 2026091701 | 7137 / 6879 | -258 | 未送达 / 未送达 | 0 | 0 / 0 | -3 |
| 2026091702 | 7415 / 6111 | -1304 | 未送达 / 未送达 | 0 | 0 / 0 | 0 |
| 2026091703 | 6297 / 9874 | +3577 | 11644 / 10242 | -1402 | 1 / 1 | +5 |
| 2026091704 | 8961 / 7112 | -1849 | 未送达 / 未送达 | 0 | 0 / 0 | 0 |
| 2026091705 | 6623 / 未发现 | 不可比 | 10697 / 未送达 | +1303 | 1 / 0 | -2 |

B0/C 搬迁前 A 送达总数都是 16，但 seed 内差异很大：C 两个更低、两个相同、
一个更高。B0 的 verified recruitment 总数为 12,548，C 为 2,037；搬迁前
follower food arrivals 为 21 对 14。这些下降部分来自 C 把原本会进入 FCRW、
再被招募的片段改成 recovery，不能把角色事件数直接解释成运输效率。

搬迁后旧 A 周围 10 单位内的 dwell ratio `C/B0` 依次为 1.19、0.44、2.47、
0.68、1.59，方向同样混合。完整逐 seed 数值在 `per_seed_comparison.csv`，汇总在
`paired_summary.json`。没有进行显著性检验、置信区间选择或不利结果重跑。

## Recovery 行为

C 共记录 **25,270** 个完整 recovery episodes：18,671 次重获任意局部信号，
6,591 次 24 步超时，8 次在 recovery movement 后接触食物。表面重获率为
**73.89%**。这不等于找回正确路线：它只表示左右传感器重新达到 `signal_on`。

按预注册的同一只蚂蚁、episode 结束后 100 步窗口，40 个 episode 后发生 B
发现，**0 个 episode 后发生 B 送达**。因此高重获率没有转化为清晰的送达优势。
初始 seed 第一对中，C 有 4,379 个 episodes、74.70% 重获；它更早发现 B，
但和 B0 一样没有完成 B 送达，并把搬迁前 A 送达从 4 降到 1。

全部 episode 都满足 24 movement 上限；没有 anchor fallback。重获要求
`S>=signal_on`，`signal_off<=S<signal_on` 不提前退出；timeout 后下一步使用原 B0
FCRW。完整 recovery 摘要位于各 C 目录的 `recovery_episodes.json`。

## 资源、测试与保护

10 条运行合计 **155.91 CPU 秒、157.12 秒顺序墙钟**。单条最大墙钟 18.40 秒，
最大 CPU 18.15 秒，最大峰值 RSS 391,012,352 bytes（约 373 MiB）。长期运行结果
共 24,551,963 bytes；最大单文件 4,932,128 bytes。所有值远低于 600 秒、2 GiB、
512 MB/条、2 CPU-hours、2 GB 总量和 50 MB 单文件限制。每条结果都低于 10 MiB
目标，总提交仍低于 100 MB 目标。

最终完整回归测试为 **337 passed**，无失败或跳过；测试使用禁用 pytest
cache/bytecode 和 Agg 后端，收据保存在
`test_results.txt` 与 `test_runtime.json`。866 个开始前保护文件全部 SHA-256
匹配，五个指定未跟踪目录没有新增、修改或删除；Stage 1/2/3A、既有五个
functional-validation seeds、proposal、briefing、reports、from_prof 和 Stage 2C/PCA
均未改变。十条运行的动力学源码清单完全一致。

## 图表和解释边界

`delivery_and_roles.png` 显示第一对的累计 A/B 送达与角色时序；
`recovery_diagnostics.png` 显示各 seed 的 episode 结果和旧食源 dwell ratio；
`scalar_field_snapshots.png` 显示第一对在 t=5999、7000、12000 的少量预注册场快照。
所有图均标注“Exploratory five-seed paired pilot; not confirmatory evidence.”
场图只在显示时把颜色上限设为 5，原始 scalar 数据没有截断或平滑。

本阶段只能得出：固定的 24 步有限 recovery 能按规格运行并频繁重新检测到局部
信息素；在这五个已观察 seeds 上，它对 B 发现时间的方向不一致，而且没有改善
B 送达总量。尚未形成总体有效性、因果收益、生物合理性、最佳 duration、
decay-law 优劣、SOTA 或确认性结论。没有运行 hard cutoff、其他 duration、
diffusion、优化器、GPU/AutoDL、20-seed confirmation，也没有恢复 Stage 2C/PCA。
