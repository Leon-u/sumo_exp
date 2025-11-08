import os, sys, pathlib
sys.path.append(str(pathlib.Path("D:/Software/Dev/sumo/tools")))
import sumolib, traci

SUMO = sumolib.checkBinary("sumo-gui")
traci.start([SUMO, "-c", "cfg.sumocfg", "--start", "--quit-on-end"])
while traci.simulation.getMinExpectedNumber() > 0:
    traci.simulationStep()
traci.close()
print("[baseline] done")
