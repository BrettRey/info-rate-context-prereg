"""Print each comparison cell and its paired 8-minus-5 differences (no selection).

Usage: python -I -B src/fakedata/nn_compare_summary.py results/fakedata/nn_compare_gpu.tsv
"""
import argparse
import csv

PAIR = ("zero_unigram_cosine5", "zero_unigram_cosine8")


def summarize(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if len({r["run_id"] for r in rows}) > 1:
        raise ValueError("mixed run IDs")
    groups = {}
    for row in rows:
        key = tuple(row[field] for field in ("proc", "m", "k", "vocab", "replicate"))
        group = groups.setdefault(key, {})
        if row["setting"] in group:
            raise ValueError("duplicate candidate in a cell")
        group[row["setting"]] = row
    for (proc, m, k, vocab, rep), group in groups.items():
        print(f"{proc}{m} k={k} V={vocab} replicate={rep}")
        for name, row in group.items():
            print(f"  {name}: bias={float(row['bias']):+.6f}, fit-oracle={float(row['fit_minus_oracle']):+.6f}, "
                  f"selected_step={row['best_step']}, epochs={row['epochs']}, seconds={row['seconds']}, "
                  f"final_evaluated={row['final_evaluated']}")
        if all(name in group for name in PAIR):
            five, eight = (group[name] for name in PAIR)
            for field in ("h_ref", "oracle_loss", "train_seed", "val_seed", "test_seed", "map_seed", "model_seed"):
                if five[field] != eight[field]:
                    raise ValueError("unpaired candidates")
            print(f"  8-minus-5: bias={float(eight['bias'])-float(five['bias']):+.6f}, "
                  f"fit-oracle={float(eight['fit_minus_oracle'])-float(five['fit_minus_oracle']):+.6f}")
        else:
            print("  8-minus-5: pending")
    print(f"{len(rows)}/13 fits recorded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="results/fakedata/nn_compare_gpu.tsv")
    summarize(parser.parse_args().path)


if __name__ == "__main__":
    main()
