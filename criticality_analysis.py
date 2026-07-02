"""
Cortical criticality ("Trident-state") estimation for scalp EEG.

This is a DELIBERATELY SEPARATE module from the phase-amplitude coupling (PAC)
analysis. The project requirement is explicit: the criticality / Trident-state
estimate must be its own module, and PAC is NOT one of its inputs. PAC is never
renamed "criticality", and criticality is never computed from PAC.

It places the brain on a single axis:

        subcritical  <----  near-critical (optimal)  ---->  supercritical
        (low arousal,        (balanced E:I,                 (high arousal,
         inhibition-          "in the zone")                  excitation-
         dominant)                                            dominant)

Markers used (all are *proxies*; scalp EEG cannot measure criticality directly):

1. Aperiodic 1/f exponent as an excitation/inhibition (E:I) proxy. A steeper
   (larger) exponent indicates inhibition-dominant / subcritical; a flatter
   (smaller) exponent indicates excitation-dominant / supercritical.
   (Gao, Peterson & Voytek 2017; Donoghue et al. 2020.)
2. Arousal from the band-power balance (fast beta/gamma vs alpha). High fast
   power relative to alpha = high arousal (supercritical side); high alpha =
   low arousal (subcritical side).
3. Long-range temporal correlations (LRTC) via detrended fluctuation analysis
   (DFA) of the alpha amplitude envelope. LRTC are maximised near criticality
   (DFA ~ 0.75). On short windows this is only indicative, so it is weighted
   low and always carries a caveat. (Linkenkaer-Hansen 2001; Hardstone 2012.)

This estimate is computed INDEPENDENTLY of PAC. PAC is deliberately NOT an
input: the two metrics are kept separate so any relationship between them (e.g.
the hypothesis that near-criticality co-occurs with strong theta-gamma coupling)
can be *observed* rather than baked in by construction. The UI may display them
side by side, but neither is computed from the other.

The estimate is reported with an explicit confidence and caveats rather than a
single hard label, because all of these markers are indirect and ideally need a
personal baseline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import pac_analysis as pac


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

# Band ranges used for the arousal proxy (Hz).
BANDS = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 50.0),
}


@dataclass
class CriticalityConfig:
    fs: float = 250.0

    # E:I proxy from the aperiodic exponent.
    exp_balanced: float = 1.5      # exponent expected near balanced E:I
    exp_spread: float = 0.7        # exponent change that = one "unit" of deviation

    # Arousal proxy from band-power balance (log2 fast/alpha ratio).
    arousal_balanced: float = 0.0  # log2((beta+gamma)/alpha) at balance
    arousal_spread: float = 1.5

    # How the markers combine into the signed deviation d.
    #   d < 0 -> subcritical, d ~ 0 -> near-critical, d > 0 -> supercritical
    w_ei: float = 0.6
    w_arousal: float = 0.4

    # State scoring.
    near_threshold: float = 0.6    # |d| below this competes as near-critical
    dfa_weight: float = 0.3
    dfa_target: float = 0.75       # DFA exponent at criticality
    dfa_tolerance: float = 0.25

    # DFA scales (seconds) for the alpha envelope.
    dfa_min_seconds: float = 0.4
    dfa_max_fraction: float = 0.25  # longest scale = this * window length

    # Quality gating.
    min_fit_r2: float = 0.80
    min_channels: int = 1


# Trident-framework mapping (educational; not medical advice).
#
# These describe the ENTRAINMENT REMEDY for each state (which rhythm to
# encourage to move the brain toward the near-critical point), and which prong
# of the "Trident" that remedy band represents. They do NOT claim the brain is
# currently "in" that processing mode - the state itself is purely the position
# on the subcritical<->supercritical arousal axis.
TRIDENT = {
    "subcritical": {
        "suggested_band": "gamma (30-50 Hz)",
        "entrainment_prong": "left prong - executive / focused processing",
        "goal": "raise arousal toward the near-critical point",
    },
    "near-critical": {
        "suggested_band": "theta (4-8 Hz)",
        "entrainment_prong": "central prong - fluid intelligence / relational "
                             "processing (IQ)",
        "goal": "sustain the optimal near-critical state",
    },
    "supercritical": {
        "suggested_band": "alpha (8-13 Hz)",
        "entrainment_prong": "right prong - creative / divergent processing",
        "goal": "calm arousal toward the near-critical point",
    },
}

ESTIMATOR_NAME = "E:I exponent + arousal + LRTC (independent of PAC)"


# --------------------------------------------------------------------------- #
# Markers
# --------------------------------------------------------------------------- #

def relative_band_powers(signal: np.ndarray, fs: float) -> dict:
    """Relative power per band (sums to ~1) over 1-50 Hz for one channel."""
    n = signal.shape[0]
    if n <= 1:
        return {b: 0.0 for b in BANDS}
    x = signal - np.mean(signal)
    w = np.hanning(n)
    psd = np.abs(np.fft.rfft(x * w)) ** 2
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    powers = {b: float(np.sum(psd[(freqs >= lo) & (freqs < hi)]))
              for b, (lo, hi) in BANDS.items()}
    total = sum(powers.values())
    if total <= 1e-12:
        return {b: 0.0 for b in BANDS}
    return {b: p / total for b, p in powers.items()}


def arousal_index(rel: dict, cfg: CriticalityConfig) -> float:
    """Signed arousal proxy: >0 = aroused (supercritical), <0 = drowsy (sub)."""
    fast = rel.get("beta", 0.0) + rel.get("gamma", 0.0)
    alpha = rel.get("alpha", 0.0)
    ratio = np.log2((fast + 1e-6) / (alpha + 1e-6))
    contrib = (ratio - cfg.arousal_balanced) / cfg.arousal_spread
    return float(np.clip(contrib, -2.5, 2.5))


def ei_index(exponent: float, cfg: CriticalityConfig) -> float:
    """Signed E:I proxy from the aperiodic exponent.

    Flatter spectrum (smaller exponent) -> excitation-dominant -> supercritical
    (positive). Steeper spectrum (larger exponent) -> inhibition-dominant ->
    subcritical (negative).
    """
    contrib = (cfg.exp_balanced - exponent) / cfg.exp_spread
    return float(np.clip(contrib, -2.5, 2.5))


def dfa_exponent(signal: np.ndarray, fs: float, cfg: CriticalityConfig):
    """Detrended fluctuation analysis of the alpha amplitude envelope.

    Returns (exponent, n_scales). On short windows this is only indicative, so
    callers should weight it lightly and surface the caveat.
    """
    n = len(signal)
    if n < int(2.0 * fs):
        return None, 0
    # alpha amplitude envelope
    alpha = pac.bandpass(signal, fs, BANDS["alpha"][0], BANDS["alpha"][1], order=4)
    from scipy.signal import hilbert
    env = np.abs(hilbert(alpha))
    y = np.cumsum(env - np.mean(env))

    min_s = max(4, int(cfg.dfa_min_seconds * fs))
    max_s = max(min_s + 1, int(cfg.dfa_max_fraction * n))
    if max_s <= min_s:
        return None, 0
    scales = np.unique(np.logspace(np.log10(min_s), np.log10(max_s), 12).astype(int))
    scales = scales[scales >= 4]
    fluct = []
    used = []
    for s in scales:
        n_seg = n // s
        if n_seg < 1:
            continue
        rms = []
        t = np.arange(s)
        for i in range(n_seg):
            seg = y[i * s:(i + 1) * s]
            coef = np.polyfit(t, seg, 1)
            fit = np.polyval(coef, t)
            rms.append(np.sqrt(np.mean((seg - fit) ** 2)))
        if rms:
            fluct.append(np.mean(rms))
            used.append(s)
    if len(used) < 3:
        return None, 0
    log_s = np.log10(used)
    log_f = np.log10(np.array(fluct) + 1e-12)
    slope = float(np.polyfit(log_s, log_f, 1)[0])
    return slope, len(used)


def dfa_closeness(dfa: float, cfg: CriticalityConfig) -> float:
    """1.0 when DFA == target (criticality), falling to 0 at +/- tolerance."""
    if dfa is None:
        return 0.0
    return float(np.clip(1.0 - abs(dfa - cfg.dfa_target) / cfg.dfa_tolerance, 0.0, 1.0))


# --------------------------------------------------------------------------- #
# Per-channel and whole-head criticality
# --------------------------------------------------------------------------- #

def analyze_channel_criticality(signal: np.ndarray, cfg: CriticalityConfig,
                                channel_index: int = 0) -> dict:
    """Marker extraction for ONE channel (channels are never combined first)."""
    signal = np.asarray(signal, dtype=float)
    signal = signal - np.mean(signal)

    freqs, psd = pac.compute_psd(signal, cfg.fs)
    params = pac.parameterize_spectrum(freqs, psd, pac.PACConfig(fs=cfg.fs))
    exponent = params["exponent"]
    fit_r2 = params["r_squared"]

    rel = relative_band_powers(signal, cfg.fs)
    ei = ei_index(exponent, cfg)
    arousal = arousal_index(rel, cfg)
    dfa, n_scales = dfa_exponent(signal, cfg.fs, cfg)

    d = cfg.w_ei * ei + cfg.w_arousal * arousal
    d = float(np.clip(d, -2.5, 2.5))

    return {
        "channel": channel_index,
        "valid": fit_r2 >= cfg.min_fit_r2,
        "deviation": round(d, 3),
        "ei_contrib": round(ei, 3),
        "arousal_contrib": round(arousal, 3),
        "aperiodic_exponent": round(exponent, 3),
        "dfa": round(dfa, 3) if dfa is not None else None,
        "dfa_scales": n_scales,
        "fit_r2": round(fit_r2, 3),
        "rel_alpha": round(rel.get("alpha", 0.0), 3),
        "rel_beta": round(rel.get("beta", 0.0), 3),
        "rel_gamma": round(rel.get("gamma", 0.0), 3),
    }


def _state_from_scores(d: float, dfa_close: float, cfg: CriticalityConfig):
    """Decide the state from the signed deviation d, consistently with the
    arousal / E:I labels (all use the same near_threshold).

    The near-critical zone is |d| <= near_threshold. Beyond it the brain is
    super- (d>0) or sub- (d<0) critical. Confidence is the honest distance from
    the nearest decision boundary (small near a boundary, large when clearly in
    one regime); strong LRTC (dfa_close) can only add confidence to a
    near-critical call, never override a clear E:I + arousal signal.
    """
    nt = cfg.near_threshold
    # transparency scores (kept for display)
    scores = {
        "subcritical": max(0.0, -d - nt),
        "near-critical": max(0.0, nt - abs(d)) + cfg.dfa_weight * dfa_close,
        "supercritical": max(0.0, d - nt),
    }
    # reference deviation (in d-units) beyond a boundary that counts as full
    # confidence; ~1 normalized marker-unit past the boundary.
    conf_ref = 1.0
    if d > nt:
        state = "supercritical"
        confidence = (d - nt) / conf_ref
    elif d < -nt:
        state = "subcritical"
        confidence = (-d - nt) / conf_ref
    else:
        state = "near-critical"
        confidence = (nt - abs(d)) / nt + cfg.dfa_weight * dfa_close
    return state, float(np.clip(confidence, 0.0, 1.0)), scores


def analyze_criticality(eeg: np.ndarray, quality: list,
                        cfg: CriticalityConfig) -> dict:
    """Whole-head criticality estimate, computed independently of PAC.

    ``eeg``     : (n_channels, n_samples) RAW EEG (never spatially combined).
    ``quality`` : per-channel quality dicts ("good"/"fair"/"bad").

    PAC is intentionally NOT used here. The two metrics are reported separately
    so any correlation between criticality and theta-gamma coupling can be
    observed empirically instead of being assumed.
    """
    eeg = np.asarray(eeg, dtype=float)
    n_ch = eeg.shape[0]

    channels = []
    for ch in range(n_ch):
        q = quality[ch]["quality"] if ch < len(quality) else "good"
        if q == "bad":
            channels.append({"channel": ch, "valid": False, "excluded": True,
                             "deviation": None, "aperiodic_exponent": None,
                             "dfa": None, "fit_r2": None})
            continue
        res = analyze_channel_criticality(eeg[ch], cfg, channel_index=ch)
        res["excluded"] = False
        res["quality"] = q
        channels.append(res)

    valid = [c for c in channels if c.get("valid")]
    if len(valid) < cfg.min_channels:
        return {
            "summary": {
                "state": "unknown",
                "label": "criticality not estimable (no clean spectral fit)",
                "estimator": ESTIMATOR_NAME,
                "confidence": 0.0,
                "n_channels": n_ch,
                "n_valid": len(valid),
                "notes": ["Need at least one channel with a reliable 1/f fit."],
            },
            "channels": channels,
        }

    d = float(np.median([c["deviation"] for c in valid]))
    exponent = float(np.median([c["aperiodic_exponent"] for c in valid]))
    dfa_vals = [c["dfa"] for c in valid if c["dfa"] is not None]
    dfa_med = float(np.median(dfa_vals)) if dfa_vals else None
    dfa_close = dfa_closeness(dfa_med, cfg)

    state, confidence, scores = _state_from_scores(d, dfa_close, cfg)

    # Report arousal and E:I from their OWN median contributions so they reflect
    # the actual markers (and may legitimately disagree), rather than both being
    # re-derived from the combined deviation d.
    med_ei = float(np.median([c["ei_contrib"] for c in valid]))
    med_arousal = float(np.median([c["arousal_contrib"] for c in valid]))
    arousal = ("high" if med_arousal > 0.5 else
               ("low" if med_arousal < -0.5 else "balanced"))
    ei_balance = ("excitation-dominant" if med_ei > 0.5 else
                  ("inhibition-dominant" if med_ei < -0.5 else "balanced"))

    notes = [
        "Scalp markers are indirect proxies for criticality; a personal "
        "baseline improves accuracy.",
        "Computed independently of PAC - the two metrics are not coupled by "
        "construction.",
    ]
    if dfa_med is None or any(c["dfa_scales"] < 5 for c in valid if c["dfa"] is not None):
        notes.append("LRTC/DFA needs minutes of data; short-window value is "
                     "indicative only and weighted low.")

    label = {
        "subcritical": "subcritical - under-aroused / inhibition-dominant",
        "near-critical": "near-critical - balanced, optimal 'in the zone' state",
        "supercritical": "supercritical - over-aroused / excitation-dominant",
    }[state]

    summary = {
        "state": state,
        "label": label,
        "estimator": ESTIMATOR_NAME,
        "deviation": round(d, 3),
        "distance_from_critical": round(abs(d), 3),
        "confidence": round(confidence, 3),
        "confidence_label": ("high" if confidence >= 0.5 else
                             ("medium" if confidence >= 0.25 else "low")),
        "arousal": arousal,
        "ei_balance": ei_balance,
        "aperiodic_exponent": round(exponent, 3),
        "dfa": round(dfa_med, 3) if dfa_med is not None else None,
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "trident": TRIDENT[state],
        "n_channels": n_ch,
        "n_valid": len(valid),
        "notes": notes,
    }

    return {"summary": summary, "channels": channels}
