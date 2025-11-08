#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run baseline and adaptive scenarios, save outputs under outputs/{baseline,adaptive}
Assumptions:
- You have SUMO installed and SUMO_HOME/tools on PATH for TraCI.
- You're running this script in the SUMO project root where cfg.sumocfg and control_*.py live.
- cfg.sumocfg writes outputs to tripinfo.xml and summary.xml in CWD (default from the template).
"""
import os, shutil, subprocess, sys

def safe_mkdir(p):
    os.makedirs(p, exist_ok=True)

def run_and_collect(tag, cmd):
    print(f"[run] {tag}: {' '.join(cmd)}")
    ret = subprocess.run(cmd, shell=False)
    if ret.returncode != 0:
        print(f"[ERR] {tag} failed with code {ret.returncode}")
        sys.exit(ret.returncode)
    out_dir = os.path.join("outputs", tag)
    safe_mkdir(out_dir)
    for f in ["tripinfo.xml", "summary.xml"]:
        if os.path.exists(f):
            os.replace(f, os.path.join(out_dir, f))
    # move detector logs if present
    for f in list(os.listdir(".")):
        if f.endswith(".xml") and (f.startswith("Q_") or f.startswith("D_")):
            os.replace(f, os.path.join(out_dir, f))
    print(f"[ok] saved to {out_dir}")

def main():
    safe_mkdir("outputs")
    run_and_collect("baseline", [sys.executable, "control_baseline.py"])
    run_and_collect("adaptive", [sys.executable, "control_adaptive.py"])
    print("[done] both scenarios finished")

if __name__ == "__main__":
    main()
