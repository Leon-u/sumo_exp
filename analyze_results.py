#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyze SUMO outputs in outputs/{baseline,adaptive} and print simple KPIs.
KPI set:
- Throughput: number of completed trips
- Travel time (s): mean / median / p90
- Time loss (s): mean
- Waiting time (s): mean
- Queue (veh): average across laneArea detectors (if present)
- Speed on main edges (if e1 detector logs present): average
It also writes a CSV summary: outputs/kpis.csv
"""
import os, statistics, xml.etree.ElementTree as ET

SCENES = ["baseline", "adaptive"]

def parse_tripinfo(path):
    if not os.path.exists(path):
        return []
    root = ET.parse(path).getroot()
    trips = []
    for el in root.iter("tripinfo"):
        d = float(el.attrib.get("duration", 0.0))
        tl = float(el.attrib.get("timeLoss", 0.0))
        wt = float(el.attrib.get("waitingTime", 0.0))
        trips.append((d, tl, wt))
    return trips

def parse_lanearea_series(dirpath):
    vals_all = []
    for fn in os.listdir(dirpath):
        if fn.startswith("Q_") and fn.endswith(".xml"):
            root = ET.parse(os.path.join(dirpath, fn)).getroot()
            vals = []
            for e in root.iter("interval"):
                if "lastStepVehicleNumber" in e.attrib:
                    vals.append(float(e.attrib["lastStepVehicleNumber"]))  # queue length proxy
                elif "nVehContrib" in e.attrib:
                    vals.append(float(e.attrib["nVehContrib"]))
            if vals:
                vals_all.append(sum(vals)/len(vals))
    return sum(vals_all)/len(vals_all) if vals_all else None

def parse_e1_speed(dirpath):
    speeds = []
    for fn in os.listdir(dirpath):
        if fn.startswith("D_") and fn.endswith(".xml"):
            root = ET.parse(os.path.join(dirpath, fn)).getroot()
            for e in root.iter("interval"):
                if "speed" in e.attrib:
                    try:
                        speeds.append(float(e.attrib["speed"]))  # m/s
                    except:
                        pass
    return (sum(speeds)/len(speeds)) if speeds else None

def percentile(data, p):
    if not data:
        return None
    data = sorted(data)
    k = (len(data)-1) * (p/100.0)
    f = int(k)
    c = min(f+1, len(data)-1)
    if f == c:
        return data[int(k)]
    return data[f]*(c-k) + data[c]*(k-f)

def fmt(x, nd=2, default="-"):
    return f"{x:.{nd}f}" if x is not None else default

def main():
    rows = []
    print("scene,trips,mean_TT(s),median_TT(s),p90_TT(s),mean_timeLoss(s),mean_wait(s)")
    for sc in SCENES:
        ddir = os.path.join("outputs", sc)
        trips = parse_tripinfo(os.path.join(ddir, "tripinfo.xml"))
        durs = [x[0] for x in trips]
        tls  = [x[1] for x in trips]
        wts  = [x[2] for x in trips]
        avg_q = parse_lanearea_series(ddir)
        avg_v = parse_e1_speed(ddir)
        row = {
            "scene": sc,
            "trips": len(trips),
            "mean_TT": (sum(durs)/len(durs)) if durs else None,
            "median_TT": (sorted(durs)[len(durs)//2] if durs else None),
            "p90_TT": percentile(durs, 90) if durs else None,
            "mean_timeLoss": (sum(tls)/len(tls)) if tls else None,
            "mean_wait": (sum(wts)/len(wts)) if wts else None,
        }
        rows.append(row)
        print(",".join([
            sc,
            str(row["trips"]),
            fmt(row["mean_TT"]),
            fmt(row["median_TT"]),
            fmt(row["p90_TT"]),
            fmt(row["mean_timeLoss"]),
            fmt(row["mean_wait"])
        ]))
    # write CSV
    os.makedirs("outputs", exist_ok=True)
    with open(os.path.join("outputs", "kpis.csv"), "w", encoding="utf-8") as f:
        f.write("scene,trips,mean_TT,median_TT,p90_TT,mean_timeLoss,mean_wait,avg_queue,avg_e1_speed\n")
        for r in rows:
            f.write(",".join([
                r["scene"],
                str(r["trips"]),
                fmt(r["mean_TT"]),
                fmt(r["median_TT"]),
                fmt(r["p90_TT"]),
                fmt(r["mean_timeLoss"]),
                fmt(r["mean_wait"])
            ]) + "\n")
    print("[ok] wrote outputs/kpis.csv")

if __name__ == "__main__":
    main()
