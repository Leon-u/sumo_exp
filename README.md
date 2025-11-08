# 基于 OD 的走廊拥堵形成与 Max-Pressure 自适应信号控制（TraCI）

最小可运行的 SUMO 工程，用**时变 OD**在三信号走廊上复现拥堵，并用 **TraCI + Max-Pressure** 做自适应信号控制（支持 GUI 和无界面）。

## 目录结构

```
sumo_exp_corridor/
  # 路网构建
  build_net.netccfg          # netconvert 配置（由 *.nod/*.edg/*.typ 生成 net.net.xml）
  nodes.nod.xml              # 节点（J1/J2/J3 三个信号 + 两端汇入/汇出）
  edges.edg.xml              # 边（主走廊 + 三处支路）
  types.typ.xml              # 道路类型
  net.net.xml                # 生成的路网（若无请按下文步骤 0 生成）

  # 交通需求 / 车辆类型 / 检测器 / 信号
  taz.add.xml                # TAZ 分区（A、B、C）
  od_15min.csv               # 15 分钟粒度的时变 OD
  utils/gen_trips.py         # 由 CSV 生成 trips 的脚本（可替代 od2trips）
  trips.trips.xml            # 由 gen_trips.py 或 od2trips 生成
  routes.rou.xml             # 由 duarouter 生成
  vtypes.add.xml             # 车辆类型（含 id="car"）
  detectors.add.xml          # 进口道 laneAreaDetectors 等
  tls.add.xml                #（如启用）自定义固定配时；默认使用 net 自带 TLS

  # 仿真配置
  cfg.sumocfg                # 主配置（加载 net、routes、additional、输出）
  myview.cfg                 # 轻量 GUI 渲染配置（可选）

  # 控制脚本（TraCI）
  control_baseline.py        # 基线：不改配时，仅推进仿真
  control_adaptive.py
                             # 自适应：Max-Pressure（按连接/车道），窗口期切相 + 适度延长

  # 输出与日志
  logs/                      # 运行时日志输出目录（如 maxp_log.csv）
  tripinfo.xml               # 车辆旅行信息（由 cfg.sumocfg 打开）
  summary.xml                # 全局摘要（由 cfg.sumocfg 打开）
```

> 说明  
> - **Max-Pressure 实现**采用“连接层（link）→ 车道级车数”为压力输入，不再用 `haltingNumber`，因此在**低速滚动**但未完全停住的场景也能感知差异。  
> - 自适应逻辑**只在安全窗口切相**（不破坏黄/全红）并**小步延长**当前最大压相位，默认不打散绿波。  

---

## 环境准备

1. 安装 SUMO（1.24+ 建议）。  
2. 设置 `SUMO_HOME` 环境变量；Windows 需将  
   `D:\Software\Dev\sumo\tools`（示例路径）加入 `PYTHONPATH` 或在脚本里 `sys.path.append(...)`（本仓脚本已处理）。  
3. Python 3.9+，依赖：`sumolib`, `traci`（随 SUMO 附带）——无需另装。

---

## 快速开始

### 0) 生成路网（首次）

```bash
netconvert -c build_net.netccfg
```

生成成功后会得到 `net.net.xml`。

### 1) 由 CSV 生成 trips

**使用仓库脚本（无需 od2trips）：**

```bash
python utils/gen_trips.py --csv od_15min.csv --out trips.trips.xml --begin 0
```

### 2) 路径分配（duarouter）

```bash
duarouter -n net.net.xml -t trips.trips.xml -o routes.rou.xml --seed 42
```

> Windows 用户不要用 `\` 做续行；直接一行写全参数。  

### 3) 跑基线 / 自适应（GUI 或无界面）

**GUI（观察）：**

```bash
python control_baseline.py
python control_adaptive.py
```

**无界面（评测）：**把脚本里 `sumolib.checkBinary("sumo-gui")` 改成 `"sumo"`，或设置环境变量 `SUMO_BINARY=sumo`。

> 脚本启动参数已包含 `--route-steps -1`，避免增量装载导致 GUI 卡顿/刷警告。

### 4) 评估

```bash
python run_scenarios.py
python analyze_results.py
```

## 自适应控制说明（Max-Pressure）

脚本：`control_adaptive_maxp_switch_align.py`

- **压力输入**：连接层的车道车辆数 + 轻微等待时间权重  
  \( P = \sum_{(l_{in}\rightarrow l_{out})\in \text{phase}} (\text{veh}(l_{in}) - \beta \cdot \text{veh}(l_{out})) \)
- **动作规则**  
  - 若**当前相位不是最大压**，且**剩余时间 ≤ 窗口**（默认 2s）且已满足**最短服务时长**（默认 4s），则**切换**到最大压相位，并设置一次**基础服务时长**；  
  - 若**当前相位就是最大压**，则**小步延长**（默认 +3s），并带冷却与上限。  
- **稳态保护**：最短服务、冷却时间、最大追加、只在窗口期切相，避免抖动；索引严格按 `min(len(state), len(links))` 对齐，跳过内部车道（`:` 开头）。

可调参数（脚本顶部）：
- `BETA_OUT`（出边权重，默认 0.0 便于放大差异）  
- `SWITCH_WINDOW`、`MIN_SERVE`、`EXT_STEP`、`MAX_EXT_ADD`、`COOLDOWN`  
- 如果动作太少：把 `BETA_OUT=0.0`、`EXT_STEP=4`、`MIN_SERVE=3.0`；  
  如果动作太频繁：把 `MIN_SERVE=8.0`、`COOLDOWN=6.0`、适当增大窗口。

---


## 许可证

MIT（可按需替换）。

---
