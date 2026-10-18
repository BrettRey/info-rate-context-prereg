"""GPU scheduling estimate from completed fixed-settings F1 per-fit timings.

Interpolate observed seconds linearly in inventory, separately by dependency
family and visible context. Word-aware rungs use their context size; rung 0 and
skipped 1w use iid. Charged rungs are bracketed at 1..2 times their plain proxy
because F1 has no joint 2V outcome fits. This is an extrapolation, not a bound.
"""
import argparse
import csv
import importlib.util
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("cost_neural_f3b",HERE/"f3b_neural_words_rates.py")
N=importlib.util.module_from_spec(spec); spec.loader.exec_module(N)


def estimate(config, timing_file):
    groups={}; seen=set(); run_ids=set(); seed_ids=set()
    with Path(timing_file).open() as stream:
        for row in csv.DictReader(stream,delimiter="\t"):
            key=(row["proc"],int(row["m"]),int(row["vocab"]),int(row["k"]))
            if key in seen: raise ValueError("duplicate F1 timing fit")
            seen.add(key); run_ids.add(row["run_id"]); seed_ids.add(row["seed"])
            if (row["device"]!="mps" or row["setting"]!=N.F1.SETTING
                    or json.loads(row["settings"])!=N.F1.settings_for(dict(dim=128,hidden=512))
                    or any(int(row[key])!=value for key,value in
                           (("n_train",10_000_000),("n_val",500_000),("n_test",1_000_000),("line",1000)))):
                raise ValueError("timings must be fixed-settings full GPU F1")
            seconds=float(row["seconds"])
            if not math.isfinite(seconds) or seconds<=0: raise ValueError("invalid F1 duration")
            groups[key]=seconds
    if len(run_ids)!=1 or len(seed_ids)!=1 or seen!=set(N.F1.design(N.F1.FULL)):
        raise ValueError("need one complete 84-fit F1 run/seed")
    totals={family:[0.,0.,0] for family in config["families"]}
    anchors=(600,2000,10000)
    for family,language,vocab,rung in N.fit_coordinates(config):
        m,mapped=N.W.E.FAMILIES[family]
        k=0 if rung=="0" else int(rung[0])
        proc="mapped" if mapped else "copy"
        if rung=="0" or (rung=="1w" and m==3):
            proc,lag,k="iid",0,1
        else:
            lag=m
        values=[groups[proc,lag,v,k] for v in anchors]
        seconds=float(N.np.interp(vocab,anchors,values))*config["n_train"]/10_000_000
        totals[family][0]+=seconds
        totals[family][1]+=seconds*(2 if rung.endswith("charged") else 1)
        totals[family][2]+=1
    return totals


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timings",type=Path)
    parser.add_argument("--run-tag",type=int,default=2010)
    args=parser.parse_args()
    totals=estimate(N.configuration(device="mps",run_tag=args.run_tag),args.timings)
    print("family unique-fits plain-proxy-hours charged-2x-proxy-hours")
    for family,(low,high,count) in totals.items():
        print(f"{family} {count} {low/3600:.2f} {high/3600:.2f}")
    print(f"total {sum(row[2] for row in totals.values())} "
          f"{sum(row[0] for row in totals.values())/3600:.2f} "
          f"{sum(row[1] for row in totals.values())/3600:.2f}")
    print("Allow additional setup/scoring/thermal overhead; early stopping may differ from F1. "
          "Sequential family shards; never concurrent GPU fits.")


if __name__=="__main__": main()
