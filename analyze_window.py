"""Summarize a time-window from monitor_beat.log. Usage: python analyze_window.py HH:MM:SS [HH:MM:SS_end]"""
import json
import statistics as st
import sys

start = sys.argv[1] if len(sys.argv) > 1 else "00:00:00"
end = sys.argv[2] if len(sys.argv) > 2 else "99:99:99"

rows = []
for ln in open("monitor_beat.log", encoding="utf-8"):
    ln = ln.strip()
    if not ln or ln.startswith("#"):
        continue
    try:
        ts, js = ln.split(" ", 1)
        d = json.loads(js)
        d["_ts"] = ts
        rows.append(d)
    except Exception:
        pass

seg = [r for r in rows if start <= r["_ts"] <= end]
print("samples", len(seg))
if seg:
    print("from", seg[0]["_ts"], "to", seg[-1]["_ts"])

    def col(k):
        return [r[k] for r in seg if isinstance(r.get(k), (int, float))]

    def med(k):
        c = col(k)
        return round(st.median(c), 3) if c else None

    states, arou, ei = {}, {}, {}
    for r in seg:
        states[r["crit_state"]] = states.get(r["crit_state"], 0) + 1
        arou[r["arousal"]] = arou.get(r["arousal"], 0) + 1
        ei[r["ei"]] = ei.get(r["ei"], 0) + 1
    print("exponent", med("exponent"), "dfa", med("dfa"), "dev", med("crit_dev"))
    print("theta_hz", med("theta_hz"), "gamma_hz", med("gamma_hz"), "ratio", med("ratio"))
    print("state", states)
    print("arousal", arou)
    print("ei", ei)
    print("timeline:")
    for r in seg:
        print(" ", r["_ts"], r["crit_state"], "dev", r["crit_dev"],
              r["arousal"], r["ei"], "exp", r["exponent"])
