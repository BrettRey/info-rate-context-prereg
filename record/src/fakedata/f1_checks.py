"""Check 1 of the revised F1 checks (DECISIONS 2026-10-09), and the independent reconstruction of check 2.

1a. Raw scores from the Python scorer agree with KenLM's `query` on representative configurations,
    including the ones that failed the original rule (same seeds and data as their F1 cells).
1b. Normalised scores agree with an explicit sum over every syllable outcome at sampled positions:
    the code normalises by 1 - P(</s>|h) - P(<unk>|h); here sum_s P(s|h) is computed directly.
2.  Modified Kneser-Ney rebuilt from the counts for the worst bigram case (independent draws,
    10,000 types, 5M tokens, lines of 1,000): discounts from counts-of-counts, interpolation with
    continuation-count unigrams, compared token by token with KenLM.
Usage: python -I src/fakedata/f1_checks.py WORKDIR OUT.md
"""
import importlib.util, math, os, subprocess, sys
import numpy as np
import kenlm

HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("f1v2", os.path.join(HERE, "f1v2.py")); F = importlib.util.module_from_spec(s); s.loader.exec_module(F)

def cell_data(work, proc, m, v, n, line, seed):
    p = F.zipf(v)
    base = 100000 * seed + 1000 * m + F.VOCABS.index(v) * 10 + (0 if proc == "iid" else 1)
    tr, te = F.simulate(n, p, m, base + 1), F.simulate(F.N_TEST, p, m, base + 2)
    F.write(f"{work}/train.txt", tr, line); F.write(f"{work}/test.txt", te, line)
    return tr, te

def build(work, order):
    F.lmplz(order, f"{work}/train.txt", f"{work}/m.arpa", f"{work}/tmp", f"{work}/logs/check_o{order}.log")
    subprocess.run([f"{F.KENLM}/build_binary", f"{work}/m.arpa", f"{work}/m.bin"], capture_output=True, check=True)

def check_raw_and_norm(work, v, rng, n_pos=300):
    raw, norm, n, _ = F.score_model(f"{work}/m.bin", f"{work}/test.txt")
    q, nq = F.query_crossent(f"{work}/m.bin", f"{work}/test.txt")
    model = kenlm.Model(f"{work}/m.bin")
    lines = open(f"{work}/test.txt").read().splitlines()
    vocab = [f"s{i}" for i in range(v)]
    worst_sum, worst_norm = 0.0, 0.0
    st, st2, tmp = kenlm.State(), kenlm.State(), kenlm.State()
    for _ in range(n_pos):
        li = rng.integers(len(lines)); toks = lines[li].split(); j = rng.integers(len(toks))
        model.BeginSentenceWrite(st)
        for w in toks[:j]:
            model.BaseScore(st, w, st2); st, st2 = st2, st
        ps = np.array([10 ** model.BaseScore(st, w, tmp) for w in vocab])
        pe, pu = 10 ** model.BaseScore(st, "</s>", tmp), 10 ** model.BaseScore(st, "<unk>", tmp)
        worst_sum = max(worst_sum, abs(ps.sum() + pe + pu - 1))
        worst_norm = max(worst_norm, abs(ps.sum() - (1 - pe - pu)))
    return {"python_raw": raw, "query_raw": q, "raw_diff": raw - q, "tokens_python": n, "tokens_query": nq,
            "max_dev_total_prob": worst_sum, "max_dev_normaliser": worst_norm}

def mkn_bigram(tr, te, v, line, log_path):
    """Interpolated modified Kneser-Ney, order 2, from counts. BOS = v, EOS = v + 1."""
    BOS, EOS = v, v + 1
    tr = tr[: (len(tr) // line) * line].reshape(-1, line); te = te[: (len(te) // line) * line].reshape(-1, line)
    seq = np.concatenate([np.full((tr.shape[0], 1), BOS), tr, np.full((tr.shape[0], 1), EOS)], axis=1)
    a, b = seq[:, :-1].ravel(), seq[:, 1:].ravel()
    W = v + 2
    pairs, c = np.unique(a * W + b, return_counts=True)
    pv, pw = pairs // W, pairs % W
    # discounts at order 2 from counts-of-counts of raw bigram counts
    nk = [np.sum(c == k) for k in (1, 2, 3, 4)]
    Y = nk[0] / (nk[0] + 2 * nk[1])
    D2 = [1 - 2 * Y * nk[1] / nk[0], 2 - 3 * Y * nk[2] / nk[1], 3 - 4 * Y * nk[3] / nk[2]]
    # continuation counts for unigrams: distinct left contexts
    acount = np.bincount(pw, minlength=W).astype(float)          # each (v,w) pair counted once
    # unigram discounts: closed form, or KenLM's fallback when it fails
    ak = [np.sum(acount[:EOS + 1] == k) for k in (1, 2, 3, 4)]
    try:
        Yu = ak[0] / (ak[0] + 2 * ak[1])
        D1 = [1 - 2 * Yu * ak[1] / ak[0], 2 - 3 * Yu * ak[2] / ak[1], 3 - 4 * Yu * ak[3] / ak[2]]
        if not all(0 < d for d in D1): raise ZeroDivisionError
        fb = False
    except ZeroDivisionError:
        D1, fb = [0.5, 1.0, 1.5], True
    def disc(x, D):
        return np.where(x >= 3, D[2], np.where(x == 2, D[1], np.where(x == 1, D[0], 0.0)))
    uni_ids = np.array([i for i in range(W) if i != BOS])          # predicted outcomes: types and EOS
    au = acount[uni_ids]
    A = au.sum()
    gamma_u = disc(au, D1).sum() / A
    n_uniform = len(uni_ids) + 1                                    # + <unk>
    p_uni = np.zeros(W)
    p_uni[uni_ids] = (au - disc(au, D1)) / A + gamma_u / n_uniform
    p_unk = gamma_u / n_uniform
    # bigram: context totals and discount mass
    ctx_tot = np.bincount(pv, weights=c, minlength=W)
    ctx_disc = np.bincount(pv, weights=disc(c, D2), minlength=W)
    gamma = np.divide(ctx_disc, ctx_tot, out=np.zeros(W), where=ctx_tot > 0)
    lookup = dict(zip(pairs.tolist(), c.tolist()))
    tseq = np.concatenate([np.full((te.shape[0], 1), BOS), te], axis=1)
    ta, tb = tseq[:, :-1].ravel(), tseq[:, 1:].ravel()
    cab = np.array([lookup.get(int(x) * W + int(y), 0) for x, y in zip(ta, tb)], dtype=float)
    seen_ctx = ctx_tot[ta] > 0
    prob = np.where(seen_ctx, np.maximum(cab - disc(cab, D2), 0) / np.where(seen_ctx, ctx_tot[ta], 1) + gamma[ta] * p_uni[tb], p_uni[tb])
    log_disc = open(log_path).read()
    return prob, {"D2_mine": [round(d, 6) for d in D2], "unigram_fallback": fb, "D1_used": D1,
                  "kenlm_log_order2": [l for l in log_disc.splitlines() if l.startswith("2 ")]}

def main():
    work, out = sys.argv[1], sys.argv[2]
    for d in (work, f"{work}/tmp", f"{work}/logs"): os.makedirs(d, exist_ok=True)
    rng = np.random.default_rng(20261009)
    lines = ["# F1 code checks and independent reconstruction", "", "Generated by `src/fakedata/f1_checks.py` on simulated data (same seeds as the F1 version 2 cells).", ""]
    configs = [("iid", 0, 10000, 5_000_000, 1000, 2), ("iid", 0, 10000, 10_000_000, 15, 2), ("copy", 1, 10000, 5_000_000, 1000, 2),
               ("copy", 2, 2000, 10_000_000, 15, 3), ("copy", 1, 600, 5_000_000, 1000, 5)]
    lines.append("## 1a and 1b: raw scores against `query`; normalisation against an explicit sum (300 sampled positions)")
    lines.append("")
    lines.append("| process | types | train | line | order | Python raw | query raw | difference | tokens equal | max deviation of total probability from 1 | max deviation of the normaliser |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for proc, m, v, n, line, order in configs:
        tr, te = cell_data(work, proc, m, v, n, line, 1)
        build(work, order)
        r = check_raw_and_norm(work, v, rng)
        lines.append(f"| {proc}{m} | {v} | {n} | {line} | {order} | {r['python_raw']:.7f} | {r['query_raw']:.7f} | {r['raw_diff']:.2e} | {r['tokens_python'] == r['tokens_query']} | {r['max_dev_total_prob']:.2e} | {r['max_dev_normaliser']:.2e} |")
        if (proc, m, v, n, line, order) == ("iid", 0, 10000, 5_000_000, 1000, 2):
            model = kenlm.Model(f"{work}/m.bin")
            prob, info = mkn_bigram(tr, te, v, line, f"{work}/logs/check_o2.log")
            ken = []
            for row in open(f"{work}/test.txt"):
                for lp, _, _ in list(model.full_scores(row, bos=True, eos=False)):
                    ken.append(lp)
            ken = np.array(ken)
            mine = np.log10(prob)
            recon = {"tokens": len(ken), "max_abs_log10_diff": float(np.max(np.abs(mine - ken))),
                     "crossent_kenlm_bits": float(-ken.mean() * math.log2(10)), "crossent_mine_bits": float(-mine.mean() * math.log2(10)), **info}
        for f_ in ("m.arpa", "m.bin"):
            if os.path.exists(f"{work}/{f_}"): os.remove(f"{work}/{f_}")
    os.remove(f"{work}/train.txt"); os.remove(f"{work}/test.txt")
    lines += ["", "## 2: modified Kneser-Ney rebuilt from counts (independent draws, 10,000 types, 5M, lines of 1,000, order 2)", ""]
    for k, val in recon.items():
        lines.append(f"- {k}: {val}")
    open(out, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
