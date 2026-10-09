#!/usr/bin/env bash
# Times lmplz/build_binary/query for orders 2..5 on synthetic data. Writes results.tsv.
set -u
B="$1"; K=~/src/kenlm/build/bin; PY=/Users/brettreynolds/projects/LLM-CLI-projects/papers/development/info-rate-context/.venv/bin/python
echo -e "regime\tvocab\tn_train\torder\tlmplz_s\tlmplz_maxrss_mb\tbinary_s\tquery_s\tarpa_mb" > "$B/results.tsv"
for regime in markov iid; do for v in 2000 10000; do for n in 10000000 30000000; do
  tr="$B/data/train.txt"; te="$B/data/test.txt"
  $PY -I "$B/scripts/gen.py" "$tr" "$n" "$v" "$regime" 1
  $PY -I "$B/scripts/gen.py" "$te" $((n / 10)) "$v" "$regime" 2
  for o in 2 3 4 5; do
    s=$(date +%s.%N 2>/dev/null || python3 -c 'import time;print(time.time())')
    /usr/bin/time -l "$K/lmplz" -o $o -S 30% -T "$B/tmp" --discount_fallback < "$tr" > "$B/data/m.arpa" 2> "$B/tmp/lmplz.err"
    e=$(python3 -c 'import time;print(time.time())'); rss=$(grep "maximum resident" "$B/tmp/lmplz.err" | awk '{printf "%.0f", $1/1048576}')
    t1=$(python3 -c "print(round($e-$s,1))") ; amb=$(du -m "$B/data/m.arpa" | cut -f1)
    s=$(python3 -c 'import time;print(time.time())'); "$K/build_binary" "$B/data/m.arpa" "$B/data/m.bin" >/dev/null 2>&1; e=$(python3 -c 'import time;print(time.time())'); t2=$(python3 -c "print(round($e-$s,1))")
    s=$(python3 -c 'import time;print(time.time())'); "$K/query" -v summary "$B/data/m.bin" < "$te" > "$B/tmp/q.out" 2>&1; e=$(python3 -c 'import time;print(time.time())'); t3=$(python3 -c "print(round($e-$s,1))")
    echo -e "$regime\t$v\t$n\t$o\t$t1\t$rss\t$t2\t$t3\t$amb" >> "$B/results.tsv"
    rm -f "$B/data/m.arpa" "$B/data/m.bin"
  done
done; done; done
rm -f "$B/data/train.txt" "$B/data/test.txt"; echo done
