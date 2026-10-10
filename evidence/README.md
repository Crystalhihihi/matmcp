# evidence/ — 关键运行的证据原件（精选自 runs/，大文件 gpw/traj/日志留本地）

> 每个目录对应一次真实运行，作为 README 与 docs/experiments.md 所述结论的物证。
> 完整证据链（含全部中间产物）见本地 runs/index.html 记录页。

| 目录 | 证明什么 |
|---|---|
| `20260812-200432_mos2_196a` | **P2 验收门终跑**：垃圾参数（ecut=200, 1×1×1）被拦截 → 自动调参 {300, kd15} → 1.680 eV direct，status=pass（attempts.json 有重试链） |
| `20260812-220421_mos2_854b` / `20260812-220741_mos2_53de` | **双引擎对等**：GPAW 1.6772 vs QE 1.6935 eV，同为 K–K 直接带隙，Δ=0.016 eV |
| `20260812-172419_mp-149` / `_mp-2534` / `181329_mp-2657` | 五材料回归的 Si / GaAs / TiO2 pass 原件（带隙 vs MP 偏差 0.016 / 0.021 / 0.104 eV） |
| `20260812-162204_mp-22526` | **诚实 fail**：LiCoO2 PBE 1.146 vs MP 0.662 eV，band_gap_vs_mp 判 fail 并给根因（强关联体系）——系统拒绝而非凑绿 |
| `20260812-154225_mos2` + `20260812-155712_mos2` | **E2 事故物证**：5×5×1 丢 K 点给出 2.019 eV 错误间接带隙（154225）；155712 的 convergence.json 记录 3×3→1.638 / 6×6→1.965 / 9×9→1.676 / 12×12→1.759 振荡序列 |
| `20260812-153143_mos2/bands_scf.txt` | **E1 物证**：GPAW 输出原文 `k=[0.33,0.33,0] → [0.33,0.33,0]`（K→K 直接）+ "No difference between direct/indirect transitions"——agent 目测误读时没读的这行 |
| `20260812-215029_mos2_1057` | **真门生产实证**：QE 腿收敛门未开 → workflow_result.json `rejected_unconverged`，零最终结果产出 |
| `20261009-225541_mos2_d84a` | **2H-MoS2 复跑 pass**（gap 1.677 eV direct @K–K，vs MP 1.66 eV）+ **calc_pdos 首跑**：pdos.json 机器导出 Mo d 带中心 −3.757 eV（占据态口径） |
| `20261009-231803_mos2-1t_906f` | **首个金属体系 run（E13）**：1T-MoS2 的 convergence.json 记录 gap 通道振荡不收（0.716→0.072 eV）而能量通道收敛，smeared-metal 规则放行，summary.json `metallic_evidence` 字段存证；verdict=pass_with_warnings（唯一 warn = MP 亚稳相标注） |
| `20261010-001026_mos2-svac-4x4_2e1e` | **S 空位缺陷态演示（demo 级，未过收敛门，仅定性）**：4×4 2H-MoS2 超胞去一个顶层 S，defect.json 机器导出带隙态峰 E_F+0.571 eV、局域于空位邻近 3 个 Mo 的 d 投影；MPI 12 核弛豫收敛 fmax=0.073 eV/Å（E14 坑见 experiments.md） |
