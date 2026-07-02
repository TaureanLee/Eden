"""
Synthetic-signal validation for the PAC pipeline (pac_analysis.py).

A reliable theta-gamma PAC algorithm must distinguish these cases:

  A. genuine PAC (gamma amplitude locked to theta phase)
  B. uncoupled 4 Hz + 40 Hz (both oscillations, but no coupling)
  C. nonsinusoidal 4 Hz with harmonics (sharp theta -> spurious 40 Hz energy)
  D. broadband 1/f noise (no theta oscillation)
  E. transient spikes (sudden steps)
  F. jaw-like broadband high-frequency bursts
  G. electrode dropout (flat run)

This exercises the REAL functions used by the server, so a pass here means the
live app behaves the same way. No hardware required.

Run:
    .\.venv\Scripts\python.exe simulate_pac_validation.py
"""

import sys

import numpy as np

import pac_analysis as pac

FS = 250.0
DUR = 24.0
N = int(FS * DUR)
T = np.arange(N) / FS


def pink_noise(n, rng, exponent=1.0):
    """Generate approximate 1/f^exponent noise via spectral shaping."""
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, d=1.0 / FS)
    freqs[0] = freqs[1]
    spec = spec / (freqs ** (exponent / 2.0))
    out = np.fft.irfft(spec, n=n)
    return out / (np.std(out) + 1e-9)


def genuine_pac(rng, theta_f=6.0, gamma_f=40.0, depth=1.0, noise=0.3):
    # Non-integer gamma/theta ratio (~6.7) so genuine PAC is NOT confusable
    # with a theta harmonic comb.
    theta_phase = 2 * np.pi * theta_f * T
    theta = np.sin(theta_phase)
    amp_mod = 1.0 - depth * 0.5 * (1.0 + np.cos(theta_phase))  # gamma max at trough
    amp_mod = 0.2 + 0.8 * (amp_mod - amp_mod.min()) / (np.ptp(amp_mod) + 1e-9)
    gamma = amp_mod * np.sin(2 * np.pi * gamma_f * T)
    return theta + 0.6 * gamma + noise * pink_noise(N, rng)


def uncoupled(rng, theta_f=6.0, gamma_f=40.0, noise=0.3):
    theta = np.sin(2 * np.pi * theta_f * T)
    gamma = 0.5 * np.sin(2 * np.pi * gamma_f * T + rng.uniform(0, 2 * np.pi))
    return theta + gamma + noise * pink_noise(N, rng)


def sharp_theta(rng, theta_f=6.0, n_harm=8, noise=0.2):
    """Sawtooth-like (1/k harmonics) sharp theta wave -> harmonic comb into the
    gamma band (6, 12, ... 48 Hz)."""
    sig = np.zeros(N)
    for k in range(1, n_harm + 1):
        sig += (1.0 / k) * np.sin(2 * np.pi * theta_f * k * T)
    return sig + noise * pink_noise(N, rng)


def broadband_noise(rng):
    return pink_noise(N, rng, exponent=1.0)


def with_spikes(rng):
    sig = np.sin(2 * np.pi * 4.0 * T) + 0.3 * pink_noise(N, rng)
    for idx in rng.integers(int(0.1 * N), int(0.9 * N), size=5):
        sig[idx] += 12.0 * np.sign(rng.standard_normal())
    return sig


def jaw_burst(rng):
    sig = np.sin(2 * np.pi * 4.0 * T) + 0.3 * pink_noise(N, rng)
    burst = np.zeros(N)
    a, b = int(0.4 * N), int(0.6 * N)
    emg = rng.standard_normal(b - a)
    # high-frequency EMG-like energy concentrated 30-50 Hz
    emg = pac.bandpass(emg, FS, 30.0, 50.0) if (b - a) > 30 else emg
    burst[a:b] = 6.0 * emg
    return sig + burst


def dropout(rng):
    sig = np.sin(2 * np.pi * 4.0 * T) + 0.3 * pink_noise(N, rng)
    a = int(0.45 * N)
    sig[a:a + int(0.3 * FS)] = 0.0  # 300 ms flat dropout
    return sig


def line(t):
    print("\n" + "=" * 68)
    print(t)
    print("=" * 68)


def main() -> int:
    cfg = pac.PACConfig(fs=FS)
    rng = np.random.default_rng(7)
    fails = []

    # ------------------------------------------------------------- A genuine
    line("A  Genuine PAC (gamma amplitude locked to theta phase)")
    res = pac.analyze_channel(genuine_pac(rng), cfg, rng)
    print(f"  status={res['status']} valid={res['valid']}")
    if res["valid"]:
        p = res["pac"]
        print(f"  theta={res['theta']['center_hz']} Hz (acc={res['theta']['accepted']}), "
              f"gamma={res['gamma']['center_hz']} Hz ({res['gamma']['type']})")
        print(f"  MI={p['modulation_index']} z={p['z']} pct={p['percentile']} "
              f"sig={p['significant']} harm={res['harmonic']['level']}")
    if res["valid"] and res["pac"]["significant"]:
        print("  PASS: significant PAC detected")
    else:
        fails.append("A genuine PAC not detected as significant")
        print("  FAIL: expected significant PAC")
    if res["valid"] and res["harmonic"]["level"] != "high":
        print("  PASS: harmonic risk not high for true PAC")
    else:
        fails.append("A genuine PAC wrongly flagged high harmonic risk")

    # ------------------------------------------------------------- B uncoupled
    line("B  Uncoupled 4 Hz + 40 Hz (no coupling)")
    res = pac.analyze_channel(uncoupled(rng), cfg, rng)
    print(f"  status={res['status']} valid={res['valid']}")
    if res["valid"]:
        p = res["pac"]
        print(f"  MI={p['modulation_index']} z={p['z']} pct={p['percentile']} "
              f"sig={p['significant']}")
    if res["valid"] and not res["pac"]["significant"]:
        print("  PASS: theta present but PAC not significant")
    else:
        fails.append("B uncoupled signal reported significant PAC")
        print("  FAIL: expected non-significant PAC")

    # ------------------------------------------------------------- C harmonics
    line("C  Nonsinusoidal sharp theta (harmonic comb to ~40 Hz)")
    res = pac.analyze_channel(sharp_theta(rng), cfg, rng)
    print(f"  status={res['status']} valid={res['valid']}")
    if res["valid"]:
        print(f"  harm level={res['harmonic']['level']} "
              f"hit={res['harmonic']['harmonic_hit']} "
              f"comb={res['harmonic']['comb_count']} "
              f"asym={res['harmonic']['asymmetry']}")
        print(f"  reasons: {res['harmonic']['reasons']}")
    if res["valid"] and res["harmonic"]["level"] in ("medium", "high"):
        print("  PASS: harmonic contamination flagged")
    else:
        fails.append("C sharp-theta harmonics not flagged")
        print("  FAIL: expected medium/high harmonic risk")

    # ------------------------------------------------------------- D noise
    line("D  Broadband 1/f noise (no theta oscillation)")
    res = pac.analyze_channel(broadband_noise(rng), cfg, rng)
    print(f"  status={res['status']} valid={res['valid']} "
          f"theta_acc={res['theta']['accepted']}")
    print(f"  messages: {res['messages']}")
    if (not res["valid"]) and res["status"] in ("theta_unreliable", "fit_poor"):
        print("  PASS: PAC correctly not calculated")
    else:
        fails.append("D broadband noise produced a PAC value")
        print("  FAIL: expected PAC not calculated")

    # ------------------------------------------------------------- E spikes
    line("E  Transient spikes (sudden steps)")
    w = pac.assess_window(with_spikes(rng)[np.newaxis, :], cfg)
    flags = w["per_channel"][0]["flags"]
    print(f"  window verdict={w['verdict']} flags={flags}")
    if "step" in flags:
        print("  PASS: step artifact detected")
    else:
        fails.append("E spike/step not detected")
        print("  FAIL: expected 'step' flag")

    # ------------------------------------------------------------- F jaw burst
    line("F  Jaw-like broadband high-frequency burst (whole head)")
    eeg = np.array([jaw_burst(rng) for _ in range(8)])
    quality = [{"channel": i, "quality": "good"} for i in range(8)]
    out = pac.analyze_pac(eeg, quality, cfg, rng)
    print(f"  window verdict={out['window']['verdict']} "
          f"broadband={out['window']['broadband']} "
          f"hf_channels={out['window']['hf_burst_channels']}")
    print(f"  overall: {out['summary']['verdict']}")
    if out["window"]["broadband"] or out["window"]["verdict"] == "poor":
        print("  PASS: broadband HF burst flagged, PAC not interpreted")
    else:
        fails.append("F jaw burst not flagged as broadband")
        print("  FAIL: expected broadband/poor window")

    # ------------------------------------------------------------- G dropout
    line("G  Electrode dropout (flat run, must NOT be interpolated)")
    w = pac.assess_window(dropout(rng)[np.newaxis, :], cfg)
    flags = w["per_channel"][0]["flags"]
    print(f"  flags={flags}")
    eeg = np.array([dropout(rng)] + [genuine_pac(rng) for _ in range(7)])
    quality = [{"channel": i, "quality": "good"} for i in range(8)]
    out = pac.analyze_pac(eeg, quality, cfg, rng)
    ch0 = out["channels"][0]
    print(f"  channel0 status={ch0['status']} (excluded => not interpolated)")
    if "dropout" in flags and ch0["status"] == "excluded":
        print("  PASS: dropout detected and channel excluded")
    else:
        fails.append("G dropout not detected/excluded")
        print("  FAIL: expected dropout flag and exclusion")

    # ------------------------------------------------------------- whole head
    line("H  Whole-head summary on genuine PAC (per-channel, uncertainty)")
    eeg = np.array([genuine_pac(rng) for _ in range(8)])
    quality = [{"channel": i, "quality": "good"} for i in range(8)]
    out = pac.analyze_pac(eeg, quality, cfg, rng)
    s = out["summary"]
    print(f"  estimator: {s['estimator']}")
    print(f"  supporting channels: {s['supporting_label']} | median z={s['median_z']} "
          f"| harmonic risk={s['harmonic_risk']} | window={s['window_quality']}")
    print(f"  verdict: {s['verdict']}")
    if s["n_supporting"] >= 5 and s["n_valid"] == 8:
        print("  PASS: per-channel PAC retained and summarized")
    else:
        fails.append("H whole-head summary insufficient")
        print("  FAIL: expected >=5 supporting channels")

    # ------------------------------------------------------------- summary
    line("SUMMARY")
    if fails:
        print(f"{len(fails)} check(s) FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("ALL PAC VALIDATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
