#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced OD->trips generator for SUMO
- Reads a CSV with columns: time_begin,time_end,origin_taz,dest_taz,veh
- Supports mapping TAZ -> one or multiple edges (with weights) for origins/sinks
- Round-robin (weighted) assignment to achieve balanced injection across multiple edges
- Ensures trips are sorted by 'depart' (ascending) to avoid incremental loading warnings/drops
- Avoids writing <vType> by default to prevent id duplication with external vtypes.add.xml
- Can optionally emit fromTaz/toTaz instead of from/to edges (--emit-taz)
Usage examples:
  # Default mapping baked in:
  #   A -> E_A_J1
  #   B -> E_S1N_J1, E_S2N_J2, E_S3N_J3  (equal weights)
  #   C -> E_J3_O
  python gen_trips.py --csv od_15min.csv --out trips.trips.xml --begin 0

  # With custom mapping files (JSON), e.g. origin_map.json:
  # {"A": {"E_A_J1": 1}, "B": {"E_S1N_J1": 2, "E_S2N_J2": 1, "E_S3N_J3": 1}}
  # and dest_map.json:
  # {"C": {"E_J3_O": 1}}
  python gen_trips.py --csv od_15min.csv --out trips.trips.xml --begin 0 \
      --origin-map origin_map.json --dest-map dest_map.json

  # Emit TAZ endpoints (to be used with duarouter --with-taz --taz-files ...):
  python gen_trips.py --csv od_15min.csv --out trips.trips.xml --begin 0 --emit-taz
"""
import argparse, csv, itertools, math, json
import xml.etree.ElementTree as ET

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="OD csv file: time_begin,time_end,origin_taz,dest_taz,veh")
    ap.add_argument("--out", required=True, help="output trips xml")
    ap.add_argument("--begin", type=int, default=0, help="simulation begin seconds offset for the first row's time_begin")
    ap.add_argument("--veh-per-second-cap", type=float, default=50.0, help="cap generation rate to avoid dense same-second departures")
    ap.add_argument("--emit-taz", action="store_true", help="emit fromTaz/toTaz fields instead of from/to edges")
    ap.add_argument("--origin-map", type=str, default="", help="JSON file mapping TAZ -> {edge:weight,...}")
    ap.add_argument("--dest-map", type=str, default="", help="JSON file mapping TAZ -> {edge:weight,...}")
    ap.add_argument("--time0", type=str, default="07:00", help="anchor clock time for begin offset (default 07:00)")
    return ap.parse_args()

def hhmm_to_sec(hhmm: str):
    h, m = hhmm.split(":")
    return int(h) * 3600 + int(m) * 60

def build_rr_sequence(weight_dict):
    """
    Build an infinite weighted round-robin iterator of edges given {"edgeA":2,"edgeB":1} -> [A,A,B] cycling
    """
    items = []
    for k, w in weight_dict.items():
        w = max(1, int(w))
        items.extend([k]*w)
    if not items:
        return iter(())  # empty iterator
    import itertools
    return itertools.cycle(items)

def load_mapping(json_path, default_dict):
    if not json_path:
        return default_dict
    with open(json_path, "r", encoding="utf-8") as f:
        obj = json.load(f)
        # normalize to dict[str]->dict[str]->int
        norm = {}
        for taz, edge_w in obj.items():
            norm[taz] = {str(e): int(w) for e, w in edge_w.items()}
        return norm

def main():
    args = parse_args()

    # Built-in defaults for the corridor demo
    default_origin_map = {
        "A": {"E_A_J1": 1},
        "B": {"E_S1N_J1": 1, "E_S2N_J2": 1, "E_S3N_J3": 1},
    }
    default_dest_map = {
        "C": {"E_J3_O": 1}
    }

    origin_map = load_mapping(args.origin_map, default_origin_map)
    dest_map   = load_mapping(args.dest_map,   default_dest_map)

    # Prepare round-robin selectors per TAZ
    origin_rr = {taz: build_rr_sequence(wdict) for taz, wdict in origin_map.items()}
    dest_rr   = {taz: build_rr_sequence(wdict) for taz, wdict in dest_map.items()}

    trips_tmp = []  # collect and sort by depart

    with open(args.csv, newline='') as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            t0 = hhmm_to_sec(row["time_begin"]) - hhmm_to_sec(args.time0) + args.begin
            t1 = hhmm_to_sec(row["time_end"])   - hhmm_to_sec(args.time0) + args.begin
            n = int(row["veh"])
            if n <= 0 or t1 <= t0:
                continue
            dur = t1 - t0

            step = max(1.0, dur / n)
            step = max(step, 1.0/args.veh_per_second_cap)

            # determine origin/dest endpoints
            o_taz = row["origin_taz"].strip()
            d_taz = row["dest_taz"].strip()

            # Round-robin select edges for each generated trip
            depart = float(t0)
            generated = 0
            while depart < t1 and generated < n:
                if args.emit_taz:
                    o_key = {"fromTaz": o_taz}
                    d_key = {"toTaz": d_taz}
                else:
                    # Map TAZ -> edge via weighted RR
                    if o_taz in origin_rr:
                        try:
                            o_edge = next(origin_rr[o_taz])
                            o_key = {"from": o_edge}
                        except StopIteration:
                            o_key = {"fromTaz": o_taz}
                    else:
                        # fallback: treat as 'fromTaz' if not mapped
                        o_key = {"fromTaz": o_taz}
                    if d_taz in dest_rr:
                        try:
                            d_edge = next(dest_rr[d_taz])
                            d_key = {"to": d_edge}
                        except StopIteration:
                            d_key = {"toTaz": d_taz}
                    else:
                        d_key = {"toTaz": d_taz}

                trips_tmp.append((depart, o_key, d_key))
                generated += 1
                depart += step

    # Sort by depart to avoid incremental loading drops
    trips_tmp.sort(key=lambda x: x[0])

    # Write XML (no <vType> by default; external vtypes.add.xml may define types)
    root = ET.Element("routes")
    for idx, (depart, o_key, d_key) in enumerate(trips_tmp):
        attrib = {"id": f"v{idx}", "depart": f"{depart:.1f}"}
        attrib.update(o_key)
        attrib.update(d_key)
        ET.SubElement(root, "trip", attrib=attrib)

    ET.ElementTree(root).write(args.out, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {args.out} with {len(trips_tmp)} trips. emit_taz={args.emit_taz}")

if __name__ == "__main__":
    main()
