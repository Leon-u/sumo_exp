# control_adaptive_maxp_switch_align.py  —— 使用“车道车数”计算压强（不再用 haltingNumber）
import os, sys, pathlib, time, csv
sys.path.append(str(pathlib.Path("D:/Software/Dev/sumo/tools")))
import sumolib, traci

SUMO = sumolib.checkBinary("sumo-gui")  # 不看图可改 "sumo"
args = [SUMO, "-c", "cfg.sumocfg", "--start", "--route-steps", "-1", "--no-warnings", "--quit-on-end"]
if pathlib.Path("myview.cfg").exists():
    args += ["--gui-settings-file", "myview.cfg"]
traci.start(args)

TLS = list(traci.trafficlight.getIDList())

# === 参数（保持偏宽松，确保会动作）===
CHECK_EVERY   = 2.0
EXT_STEP      = 3.0
MAX_EXT_ADD   = 20.0
SWITCH_WINDOW = 2.0
MIN_SERVE     = 4.0
COOLDOWN      = 3.0
BETA_OUT      = 0.0   # 只看入口更容易拉开差距；需要时再调回 0.5~1.0
GAP_EXT_TH    = 0.0
GAP_SW_TH     = 0.0
FALLBACK_AFTER = 60.0

def lane_ok(lane_id: str) -> bool:
    # 跳过内部车道（以 ':' 开头）
    return lane_id and not lane_id.startswith(':')

def aligned_idx2lanes(tls_id):
    """返回：(L, idx->(inLane, outLane))，L=min(len(links), max_state_len)"""
    links = traci.trafficlight.getControlledLinks(tls_id)
    prog = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls_id)[0]
    max_state_len = max(len(ph.state) for ph in prog.getPhases())
    L = min(len(links), max_state_len)
    mapping = {}
    for idx in range(L):
        group = links[idx]
        if not group:
            continue
        inLane, via, outLane = group[0]
        if lane_ok(inLane) and lane_ok(outLane):
            mapping[idx] = (inLane, outLane)
    return L, mapping

def build_phase_greens_aligned(tls_id, L):
    greens = {}
    prog = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls_id)[0]
    for i, ph in enumerate(prog.getPhases()):
        s = ph.state[:L]
        greens[i] = {k for k, ch in enumerate(s) if ch in "Gg"}
    return greens

# 车道层“队列强度”：车辆数 + （可选）等待时间权重
def lane_pressure_in(lane_id: str) -> float:
    try:
        n = float(traci.lane.getLastStepVehicleNumber(lane_id))       # 该车道上车辆总数
        # 选配：把等待时间纳入一个很小的权重，区分“真有排队”
        wait = float(traci.lane.getWaitingTime(lane_id))              # 累计等待秒数
        return n + 0.01 * wait
    except traci.TraCIException:
        return 0.0

def lane_pressure_out(lane_id: str) -> float:
    try:
        # 出口拥堵越大，压力越小：用车辆数近似“下游占用”
        return float(traci.lane.getLastStepVehicleNumber(lane_id))
    except traci.TraCIException:
        return 0.0

# 缓存
L_T, IDX2, PHG, BASE_DUR = {}, {}, {}, {}
for tls in TLS:
    L, m = aligned_idx2lanes(tls)
    L_T[tls]  = L
    IDX2[tls] = m                      # 映射到 lane（不是 edge）
    PHG[tls]  = build_phase_greens_aligned(tls, L)
    prog = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls)[0]
    BASE_DUR[tls] = {i: float(p.duration) for i, p in enumerate(prog.getPhases())}

def phase_pressure(tls, p_idx) -> float:
    s = 0.0
    for idx in PHG[tls].get(p_idx, set()):
        io = IDX2[tls].get(idx)
        if not io:
            continue
        inL, outL = io
        s += lane_pressure_in(inL) - BETA_OUT * lane_pressure_out(outL)
    return s

# 运行态
last_wall   = 0.0
last_act    = {tls: -1e9 for tls in TLS}
phase_enter = {tls: 0.0  for tls in TLS}
last_phase_seen = {tls: traci.trafficlight.getPhase(tls) for tls in TLS}
ever_acted  = {tls: False for tls in TLS}

os.makedirs("logs", exist_ok=True)
logf = open("logs/maxp_log.csv", "w", newline="", encoding="utf-8")
log  = csv.writer(logf)
log.writerow(["time","tls","cur","best","best_score","cur_score","gap_best-second","gap_best-cur","rem","served","action"])

# 初始化进入时间
t0 = traci.simulation.getTime()
for tls in TLS:
    phase_enter[tls] = t0

while traci.simulation.getMinExpectedNumber() > 0:
    traci.simulationStep()
    sim_t = traci.simulation.getTime()

    now = time.time()
    if now - last_wall < CHECK_EVERY:
        continue
    last_wall = now

    for tls in TLS:
        cur = traci.trafficlight.getPhase(tls)
        if cur != last_phase_seen[tls]:
            last_phase_seen[tls] = cur
            phase_enter[tls] = sim_t

        rem = traci.trafficlight.getNextSwitch(tls) - sim_t
        served = sim_t - phase_enter[tls]

        pres = {p: phase_pressure(tls, p) for p in PHG[tls].keys()}
        if not pres:
            log.writerow([f"{sim_t:.1f}", tls, cur, cur, "0","0","0","0", f"{rem:.1f}", f"{served:.1f}", "no-pres"])
            continue

        best, best_sc = max(pres.items(), key=lambda kv: kv[1])
        cur_sc = pres.get(cur, -1e9)
        scores = sorted(pres.values(), reverse=True)
        second = scores[1] if len(scores) > 1 else -1e9
        gap_best_second = best_sc - second
        gap_best_cur    = best_sc - cur_sc

        action = "none"
        if sim_t - last_act[tls] >= COOLDOWN:
            if (cur != best) and (rem <= SWITCH_WINDOW) and (served >= MIN_SERVE) and (gap_best_cur >= GAP_SW_TH):
                base = max(MIN_SERVE, BASE_DUR[tls].get(best, MIN_SERVE))
                traci.trafficlight.setPhase(tls, best)
                traci.trafficlight.setPhaseDuration(tls, base)
                last_act[tls] = sim_t
                action = f"switch->{best}"
                ever_acted[tls] = True
            elif (cur == best) and (gap_best_second >= GAP_EXT_TH) and (2.0 <= rem < MAX_EXT_ADD):
                traci.trafficlight.setPhaseDuration(tls, rem + EXT_STEP)
                last_act[tls] = sim_t
                action = f"extend+{EXT_STEP}"
                ever_acted[tls] = True

        if (not ever_acted[tls]) and (sim_t >= FALLBACK_AFTER) and 2.0 <= rem < MAX_EXT_ADD:
            traci.trafficlight.setPhaseDuration(tls, rem + EXT_STEP)
            last_act[tls] = sim_t
            action = f"fallback_extend+{EXT_STEP}"
            ever_acted[tls] = True

        log.writerow([f"{sim_t:.1f}", tls, cur, best, f"{best_sc:.2f}", f"{cur_sc:.2f}",
                      f"{gap_best_second:.2f}", f"{gap_best_cur:.2f}",
                      f"{rem:.1f}", f"{served:.1f}", action])

traci.close()
logf.close()
print("[adaptive-maxp-switch-align-lane] done")
