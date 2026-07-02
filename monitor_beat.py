"""Lightweight live monitor for binaural-beat sessions.

Samples the running Eden SSE stream once per payload, extracts the headline
metrics, and appends a compact line to monitor_beat.log so the agent can scan
for drastic changes over time. Read-only; does not touch the server.
"""
import json
import time
import urllib.request

URL = "http://127.0.0.1:5000/stream"
LOG = "monitor_beat.log"


def sample():
    r = urllib.request.urlopen(URL, timeout=20)
    for raw in r:
        line = raw.decode("utf-8", "replace")
        if line.startswith("data:"):
            d = json.loads(line[5:].strip())
            r.close()
            return d
    return None


def headline(d):
    def rnd(v, n=2):
        return round(v, n) if isinstance(v, (int, float)) else None

    bands = d.get("bands") or []
    # bands is a list of {name, value}
    bmap = {}
    if bands and isinstance(bands[0], dict):
        for b in bands:
            bmap[b.get("name") or b.get("band")] = b.get("value")
    el = d.get("electrodes") or []
    qcount = {}
    for e in el:
        qcount[e["quality"]] = qcount.get(e["quality"], 0) + 1
    ps = (d.get("pac") or {}).get("summary", {})
    cs = (d.get("criticality") or {}).get("summary", {})
    return {
        "dominant": d.get("dominant"),
        "ratio": rnd(d.get("ratio")),
        "theta_hz": rnd(d.get("theta_freq")),
        "gamma_hz": rnd(d.get("gamma_freq")),
        "qual": qcount,
        "pac_valid": ps.get("n_valid"),
        "pac_support": ps.get("supporting_label"),
        "pac_z": ps.get("median_z"),
        "crit_state": cs.get("state"),
        "crit_dev": cs.get("deviation"),
        "crit_conf": cs.get("confidence_label"),
        "exponent": cs.get("aperiodic_exponent"),
        "dfa": cs.get("dfa"),
        "arousal": cs.get("arousal"),
        "ei": cs.get("ei_balance"),
        "bands": {k: rnd(v, 1) for k, v in bmap.items()} if bmap else None,
    }


def main():
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("# binaural-beat monitor started\n")
    while True:
        try:
            d = sample()
            if d is None:
                continue
            h = headline(d)
            ts = time.strftime("%H:%M:%S")
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"{ts} {json.dumps(h)}\n")
        except Exception as exc:  # keep monitoring through transient errors
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} ERROR {exc}\n")
        time.sleep(3)


if __name__ == "__main__":
    main()
