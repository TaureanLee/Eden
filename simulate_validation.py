"""
Validation simulations for two features:

  1. Per-electrode bad-signal detection (Unicorn-suite-style good/bad indicator).
  2. Cross-electrode constructive/destructive combination so a single noisy
     electrode does NOT corrupt the detected brain frequency.

This drives the REAL functions used by the live server (server.EEGStreamer), so a
pass here means the running app behaves the same way. No hardware required.

Run:
    .\.venv\Scripts\python.exe simulate_validation.py
"""

import sys

import numpy as np

from server import EEGStreamer, BANDS, BAND_RANGES

N_CHANNELS = 8


def make_streamer() -> EEGStreamer:
    # Synthetic board => no hardware, but all signal-processing methods are real.
    return EEGStreamer(synthetic=True, serial="", window=3.0, interval=1.0)


def brain_signal(sr: int, freq: float, seconds: float, amp: float = 10.0,
                 noise: float = 1.0, seed: int = 0) -> np.ndarray:
    """8 electrodes sharing the same brain rhythm + small independent noise."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    shared = amp * np.sin(2.0 * np.pi * freq * t)
    return np.array([shared + rng.normal(0.0, noise, n) for _ in range(N_CHANNELS)])


def inject_emg(data: np.ndarray, ch: int, sr: int, seed: int = 99) -> np.ndarray:
    """Add a strong localized muscle artifact (high amplitude, high frequency)."""
    rng = np.random.default_rng(seed)
    n = data.shape[1]
    t = np.arange(n) / sr
    emg = 90.0 * np.sin(2.0 * np.pi * 45.0 * t) + rng.normal(0.0, 70.0, n)
    out = data.copy()
    out[ch] = out[ch] + emg
    return out


def dominant_band(powers: np.ndarray) -> str:
    return BANDS[int(np.argmax(powers))][0]


def band_for_freq(freq: float) -> str:
    for (name, _), (lo, hi) in zip(BANDS, BAND_RANGES):
        if lo <= freq < hi:
            return name
    return "gamma"


def line(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def main() -> int:
    s = make_streamer()
    sr = s.sampling_rate
    failures = []

    # ----------------------------------------------------------------- TEST 1
    line("TEST 1  Bad-electrode detection (clean vs. one EMG channel)")
    clean = brain_signal(sr, 10.0, s.window, seed=1)            # 10 Hz alpha
    quality_clean, _ = s._assess_signal_quality(clean)
    clean_states = [q["quality"] for q in quality_clean]
    print("clean electrodes:", clean_states)
    if all(q == "good" for q in clean_states):
        print("  PASS: all clean electrodes reported good")
    else:
        failures.append("clean electrodes were not all 'good'")
        print("  FAIL: expected all good")

    bad_ch = 3
    noisy = inject_emg(clean, bad_ch, sr)
    quality_noisy, _ = s._assess_signal_quality(noisy)
    for q in quality_noisy:
        print(f"  ch{q['channel']+1}: quality={q['quality']:<4} "
              f"rel-noise={q['noise']:.2f}x  hf={q['hf_ratio']:.2f}")
    if quality_noisy[bad_ch]["quality"] == "bad":
        print(f"  PASS: ch{bad_ch+1} (EMG) flagged BAD")
    else:
        failures.append(f"EMG channel {bad_ch} not flagged bad")
        print(f"  FAIL: ch{bad_ch+1} should be bad")
    others_ok = all(quality_noisy[c]["quality"] == "good"
                    for c in range(N_CHANNELS) if c != bad_ch)
    if others_ok:
        print("  PASS: the other 7 electrodes stay good")
    else:
        failures.append("non-artifact channels misflagged")
        print("  FAIL: other electrodes should stay good")

    # ----------------------------------------------------------------- TEST 2
    line("TEST 2  Interference: one bad electrode must NOT change the result")
    quality, weights = s._assess_signal_quality(noisy)

    robust = s._robust_combine(noisy, weights)
    robust_powers = s._band_powers_from_signal(robust)
    robust_band = dominant_band(robust_powers)
    robust_peak = s._get_peak_frequency_in_band(robust[np.newaxis, :], 8.0, 13.0)

    naive = np.mean(noisy, axis=0)                              # plain average
    naive_powers = s._band_powers_from_signal(naive)
    naive_band = dominant_band(naive_powers)

    print(f"  robust combine -> dominant={robust_band}, alpha peak={robust_peak:.1f} Hz")
    print(f"  naive  average -> dominant={naive_band} (for contrast)")
    if robust_band == "alpha":
        print("  PASS: robust combine keeps dominant = alpha despite EMG")
    else:
        failures.append(f"robust dominant was {robust_band}, expected alpha")
        print("  FAIL: robust dominant should be alpha")
    if abs(robust_peak - 10.0) <= 1.0:
        print("  PASS: detected alpha peak within 1 Hz of 10 Hz")
    else:
        failures.append(f"alpha peak off: {robust_peak:.2f} Hz")
        print("  FAIL: alpha peak should be ~10 Hz")
    if naive_band != "alpha":
        print(f"  NOTE: naive average WOULD report '{naive_band}' "
              "(this is the corruption the fix prevents)")

    # ----------------------------------------------------------------- TEST 3
    line("TEST 3  Frequency sweep, robust vs naive, with EMG on ch6")
    print(f"{'brain Hz':>8} {'expect':>7} {'robust':>7} {'naive':>7}  result")
    for freq in (6.0, 10.0, 20.0, 40.0):
        d = brain_signal(sr, freq, s.window, seed=int(freq))
        d = inject_emg(d, 5, sr)                                # artifact on ch6
        _, w = s._assess_signal_quality(d)
        rob = dominant_band(s._band_powers_from_signal(s._robust_combine(d, w)))
        nai = dominant_band(s._band_powers_from_signal(np.mean(d, axis=0)))
        expect = band_for_freq(freq)
        ok = rob == expect
        print(f"{freq:>8.0f} {expect:>7} {rob:>7} {nai:>7}  "
              f"{'PASS' if ok else 'FAIL'}")
        if not ok:
            failures.append(f"sweep {freq} Hz robust={rob} expected={expect}")

    # ----------------------------------------------------------------- TEST 4
    line("TEST 4  Flat / disconnected electrode is flagged bad")
    flat = brain_signal(sr, 10.0, s.window, seed=7)
    flat[2] = np.zeros(flat.shape[1])                          # ch3 disconnected
    q_flat, _ = s._assess_signal_quality(flat)
    print(f"  ch3 quality = {q_flat[2]['quality']} (noise {q_flat[2]['noise']:.2f}x)")
    if q_flat[2]["quality"] == "bad":
        print("  PASS: flat electrode flagged bad")
    else:
        failures.append("flat electrode not flagged bad")
        print("  FAIL: flat electrode should be bad")

    # ----------------------------------------------------------------- SUMMARY
    line("SUMMARY")
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("ALL CHECKS PASSED")
    print("  - bad/flat electrodes are detected from the signal itself")
    print("  - quality-weighted electrode combination rejects local artifacts")
    print("  - the dominant brain frequency is recovered despite a noisy channel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
