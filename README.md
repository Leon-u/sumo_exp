# 基于 OD 的走廊拥堵形成与 Max-Pressure 自适应信号控制（TraCI）

最小可运行的 SUMO 工程，用**时变 OD**在三信号走廊上复现拥堵，并用 **TraCI + Max-Pressure** 做自适应信号控制（支持 GUI 和无界面）。同时提供“全红自检”脚本验证 TraCI 控制链路。

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
  control_force_all_red.py   # 自检：开局强制全红，用于验证 TraCI 控制生效
  control_adaptive_maxp_switch_align.py
                             # 自适应：Max-Pressure（按连接/车道），窗口期切相 + 适度延长

  # 输出与日志
  logs/                      # 运行时日志输出目录（如 maxp_log.csv）
  tripinfo.xml               # 车辆旅行信息（由 cfg.sumocfg 打开）
  summary.xml                # 全局摘要（由 cfg.sumocfg 打开）
```

> 说明  
> - **Max-Pressure 实现**采用“连接层（link）→ 车道级车数”为压力输入，不再用 `haltingNumber`，因此在**低速滚动**但未完全停住的场景也能感知差异。  
> - 自适应逻辑**只在安全窗口切相**（不破坏黄/全红）并**小步延长**当前最大压相位，默认不打散绿波。  
> - 提供 `control_force_all_red.py` 验证你本机的 TraCI 控制链路确实生效（GUI 上会立刻全红）。

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

### 1) 由 CSV 生成 trips（二选一）

**A. 使用仓库脚本（无需 od2trips）：**

```bash
python utils/gen_trips.py --csv od_15min.csv --out trips.trips.xml --begin 0
```

**B. 使用官方 od2trips：**

```bash
od2trips -n taz.add.xml -d od_15min.csv -o trips.trips.xml --ignore-errors
```

> 若使用 od2trips，请确保 `vtypes.add.xml` 中存在 `<vType id="car" .../>`；trips 内的 `<trip type="car" ...>` 才不会报 “vehicle type 'car' is not known”。

### 2) 路径分配（duarouter）

```bash
duarouter -n net.net.xml -t trips.trips.xml -o routes.rou.xml --seed 42
```

> Windows 用户不要用 `\` 做续行；直接一行写全参数。  
> 如出现 “type 'car' unknown”，请确认 `trips.trips.xml` 中 `type` 与 `vtypes.add.xml` 一致。

### 3) 跑基线 / 自适应（GUI 或无界面）

**GUI（观察）：**

```bash
python control_baseline.py
python control_adaptive_maxp_switch_align.py
```

**无界面（评测）：**把脚本里 `sumolib.checkBinary("sumo-gui")` 改成 `"sumo"`，或设置环境变量 `SUMO_BINARY=sumo`。

> 脚本启动参数已包含 `--route-steps -1`，避免增量装载导致 GUI 卡顿/刷警告。

### 4) 输出与评估

`cfg.sumocfg` 已开启常用输出：
- `tripinfo.xml`: 每车旅行时间、等待、路线等
- `summary.xml`: 每步摘要

简单评估样例（Python）：

```python
import xml.etree.ElementTree as ET
root = ET.parse("tripinfo.xml").getroot()
tts   = [float(x.attrib["duration"]) for x in root.iter("tripinfo")]
waits = [float(x.attrib["waitingTime"]) for x in root.iter("tripinfo")]
print("Trips =", len(tts))
print("Mean TT(s) =", sum(tts)/len(tts))
print("Mean Wait(s) =", sum(waits)/len(waits))
```

自适应脚本还会输出 `logs/maxp_log.csv`，字段含义：
```
time,tls,cur,best,best_score,cur_score,gap_best-second,gap_best-cur,rem,served,action
```
可据此检查是否发生了 `switch->p` 或 `extend+3`。

---

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

## 常见问题与排查

1. **GUI 一开就“卡”/黑屏**  
   - 已在脚本内使用 `--route-steps -1` 和（可选）`myview.cfg` 轻量渲染；  
   - 仍卡：尝试无界面 `sumo` 评测；或将 `cfg.sumocfg` 的 `<step-length>` 临时设为 `1.0` 观测。

2. **“Edge 'E' / ':J3' is not known”**  
   - 不要用 `lane_id.split('_')[0]` 取边，内部车道会得到 `:J3`；本仓脚本已改为保持 **lane 级计算** 并过滤内部车道。

3. **“vehicle type 'car' is not known”**  
   - 确保 `vtypes.add.xml` 中存在 `<vType id="car" ...>`，且 `trips.trips.xml`/`routes.rou.xml` 的 `type="car"` 对齐。

4. **“state length mismatch / Mismatching phase size”**  
   - 自定义 `tls.add.xml` 时要保证 phase 的 `state` 长度与 `getControlledLinks()` 一致；若不确定，先不要启用 `tls.add.xml`，使用 net 自带 TLS。

5. **“TraCI server already finished / 连接被关闭”**  
   - 多由前置错误导致 SUMO 秒退；用 `--log logs/sumo.log --error-log logs/sumo.err` 落地后查看第一条报错。  
   - 确保不重复启动、端口未占用，`<time end>` 足够大且有车能进入网络。

6. **我只想验证 TraCI 控制是否生效**  
   - 先运行 `python control_force_all_red.py`，GUI 应立刻全红（车辆在停止线排队）。

---

## 复现实验对比（建议流程）

1. 生成 `routes.rou.xml`；  
2. **无界面**分别运行：
   ```
   python control_baseline.py
   python control_adaptive_maxp_switch_align.py
   ```
3. 用 `tripinfo.xml` 对比：`mean_timeLoss / mean_wait / p90_TT / throughput`。  
4. 若差异不明显，调大需求不均衡（OD），或把 `BETA_OUT=0.0`、`EXT_STEP=4`、`MIN_SERVE=3.0`，观察差异，随后回调到更稳配置。

---

## 许可证

MIT（可按需替换）。

---

## 贡献

欢迎 PR：  
- 引入入口处 e1/e2 检测器作为压力输入；  
- 增加 PI/MPC/RL 控制器作横向对比；  
- 指标面板/可视化叠加（TraCI GUI overlay）。
