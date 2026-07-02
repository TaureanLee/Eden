"""
Phase-amplitude coupling (PAC) analysis for scalp EEG.

This module implements a deliberately conservative theta-gamma PAC pipeline. It
is written as pure functions (numpy + scipy only) so the whole thing can be unit
tested against synthetic signals without any hardware or web server.

Design goals (see the project requirements):

1. PAC is computed independently for every clean channel. Channels are never
   averaged or spatially combined before PAC is measured.
2. A theta oscillation must be confirmed to exist above the aperiodic 1/f
   background (specparam / FOOOF-style spectral parameterization) before theta
   phase is interpreted. If no reliable theta peak exists we report
   "theta unreliable - PAC not calculated" instead of a meaningless number.
3. Gamma is checked the same way, and a narrow peak landing exactly on the band
   edge (30 Hz) is treated as suspect rather than accepted. We distinguish a
   genuine gamma oscillation from broadband high-frequency elevation.
4. Windows containing dropouts, clipping, steps, or broadband EMG/eye bursts are
   flagged and excluded. Dropouts are never interpolated before PAC.
5. PAC is Tort's Modulation Index (KL divergence of the gamma-amplitude /
   theta-phase distribution from uniform), not a frequency ratio.
6. Raw PAC is normalised against a time-shift surrogate null distribution to get
   a z-score and percentile.
7. Theta waveform sharpness / asymmetry and a harmonic comb check estimate the
   risk that "PAC" is really a nonsinusoidal-theta harmonic artifact.
8. Filtering uses documented Butterworth bands with reflection padding and
   filter-edge trimming. The gamma band is wide enough to retain PAC sidebands.
9. The result reports uncertainty (z, percentile, supporting channels, window
   quality, harmonic risk, estimator name) rather than a single percentage.

References (method names, not endorsements of any single implementation):
  - Tort et al. 2010, J Neurophysiol (Modulation Index).
  - Donoghue et al. 2020, Nat Neurosci (specparam / FOOOF).
  - Aru et al. 2015, Curr Opin Neurobiol (PAC pitfalls, harmonics, surrogates).
  - Cole & Voytek 2017 (waveform shape / bycycle).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, filtfilt, hilbert, welch


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

@dataclass
class PACConfig:
    fs: float = 250.0                      # sampling rate (Hz)
    theta_band: tuple = (4.0, 8.0)
    gamma_band: tuple = (30.0, 50.0)

    # specparam / FOOOF-style fit
    fit_range: tuple = (2.0, 50.0)
    max_n_peaks: int = 8
    peak_threshold_sd: float = 2.0         # peak must exceed this * residual SD
    min_peak_prominence: float = 0.10      # log10 power above aperiodic fit
    peak_width_limits: tuple = (1.0, 12.0) # Hz (FWHM)
    min_fit_r2: float = 0.85               # below this the spectral fit is poor

    # oscillation acceptance
    theta_edge_margin: float = 0.4         # Hz away from theta band edges
    gamma_edge_margin: float = 2.0         # Hz; rejects a "peak" sitting on 30 Hz

    # PAC / Tort MI
    n_phase_bins: int = 18
    n_surrogates: int = 200
    edge_seconds: float = 0.4              # filter-edge samples trimmed each side
    filter_order: int = 4

    # artifact / window rejection (in robust z units unless noted)
    clip_fraction_bad: float = 0.02        # >2% of samples at saturation rail
    step_z_bad: float = 8.0                # single-sample jump this large = step
    flat_run_seconds: float = 0.10         # flat run >= this = dropout
    hf_fraction_bad: float = 0.55          # >55% of 1-50 Hz power above 30 Hz
    broadband_channel_fraction: float = 0.5  # share of channels w/ HF burst

    # waveform / harmonic controls
    harmonic_tolerance: float = 1.5        # Hz: gamma cf within this of n*theta
    sharpness_asym_high: float = 0.6       # |asymmetry| above this = sharp/spiky

    # significance
    sig_percentile: float = 95.0           # surrogate percentile to "support"


ESTIMATOR_NAME = "Tort MI (KL), time-shift surrogate z"


# --------------------------------------------------------------------------- #
# Filtering (documented bandwidth, padding, edge trimming)
# --------------------------------------------------------------------------- #

def bandpass(signal: np.ndarray, fs: float, lo: float, hi: float,
             order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth bandpass with reflection padding.

    filtfilt is zero-phase (acausal); it is appropriate for analysing a closed
    window with tolerated latency. Reflection padding plus filter-edge trimming
    (done by the caller via ``edge_samples``) removes startup transients.
    """
    nyq = 0.5 * fs
    lo_n = max(1e-4, lo / nyq)
    hi_n = min(0.9999, hi / nyq)
    b, a = butter(order, [lo_n, hi_n], btype="band")
    pad = min(len(signal) - 1, int(fs))  # up to 1 s reflection pad
    if pad > 3:
        padded = np.concatenate([signal[pad:0:-1], signal, signal[-2:-pad - 2:-1]])
        filt = filtfilt(b, a, padded)
        return filt[pad:pad + len(signal)]
    return filtfilt(b, a, signal)


def analytic_phase_amplitude(signal: np.ndarray, fs: float, band: tuple,
                             edge_samples: int, order: int = 4):
    """Return (phase, amplitude) from the Hilbert transform of a band, with the
    unreliable filter-edge samples trimmed off."""
    filtered = bandpass(signal, fs, band[0], band[1], order=order)
    analytic = hilbert(filtered)
    phase = np.angle(analytic)
    amp = np.abs(analytic)
    if edge_samples > 0 and 2 * edge_samples < len(signal):
        sl = slice(edge_samples, len(signal) - edge_samples)
        return phase[sl], amp[sl], filtered[sl]
    return phase, amp, filtered


# --------------------------------------------------------------------------- #
# Spectral parameterization (specparam / FOOOF-style)
# --------------------------------------------------------------------------- #

def _aperiodic(log_f, offset, exponent):
    return offset - exponent * log_f


def _gaussian(f, amp, mu, sigma):
    return amp * np.exp(-((f - mu) ** 2) / (2.0 * sigma ** 2))


def compute_psd(signal: np.ndarray, fs: float):
    """Welch PSD favouring a smooth, well-averaged estimate (~1 Hz resolution).

    A smooth PSD is what the specparam-style fit needs: too few averages produce a
    noisy periodogram that both lowers the fit R^2 for real peaks and invents
    spurious peaks in noise. ~1 Hz resolution still localizes a theta peak within
    the 4-8 Hz band.
    """
    nperseg = int(min(len(signal), max(fs, 256)))
    nperseg = max(64, nperseg)
    freqs, psd = welch(signal, fs=fs, nperseg=nperseg,
                       noverlap=nperseg // 2, detrend="constant")
    return freqs, psd


def parameterize_spectrum(freqs: np.ndarray, psd: np.ndarray,
                          cfg: PACConfig) -> dict:
    """Separate the spectrum into an aperiodic 1/f component and Gaussian peaks.

    This follows the specparam (FOOOF) approach: fit the aperiodic background in
    log-log space, iteratively fit Gaussian peaks to the flattened residual,
    refit the aperiodic on the peak-removed spectrum, and report goodness of fit.
    """
    from scipy.optimize import curve_fit

    lo, hi = cfg.fit_range
    mask = (freqs >= lo) & (freqs <= hi) & (freqs > 0)
    f = freqs[mask]
    p = np.clip(psd[mask], 1e-30, None)
    log_p = np.log10(p)
    log_f = np.log10(f)

    # --- initial aperiodic fit ---
    try:
        (offset, exponent), _ = curve_fit(
            _aperiodic, log_f, log_p, p0=[log_p[0], 1.0], maxfev=10000)
    except Exception:
        A = np.vstack([np.ones_like(log_f), -log_f]).T
        coef, *_ = np.linalg.lstsq(A, log_p, rcond=None)
        offset, exponent = coef[0], coef[1]

    # --- robustly re-fit, ignoring points that stick up (peaks) ---
    for _ in range(3):
        resid = log_p - _aperiodic(log_f, offset, exponent)
        keep = resid <= np.percentile(resid, 60)
        if keep.sum() < 5:
            break
        try:
            (offset, exponent), _ = curve_fit(
                _aperiodic, log_f[keep], log_p[keep],
                p0=[offset, exponent], maxfev=10000)
        except Exception:
            break

    # --- iterative Gaussian peak extraction on the flattened spectrum ---
    flat = log_p - _aperiodic(log_f, offset, exponent)
    peaks = []
    width_lo, width_hi = cfg.peak_width_limits
    sigma_lo, sigma_hi = width_lo / 2.355, width_hi / 2.355
    for _ in range(cfg.max_n_peaks):
        idx = int(np.argmax(flat))
        height = flat[idx]
        if height < max(cfg.min_peak_prominence,
                        cfg.peak_threshold_sd * np.std(flat)):
            break
        try:
            (amp, mu, sigma), _ = curve_fit(
                _gaussian, f, flat, p0=[height, f[idx], 1.0],
                bounds=([0.0, lo, sigma_lo], [np.inf, hi, sigma_hi]),
                maxfev=10000)
        except Exception:
            break
        peaks.append({"cf": float(mu), "prominence": float(amp),
                      "bandwidth": float(2.355 * sigma)})
        flat = flat - _gaussian(f, amp, mu, sigma)

    # --- refit aperiodic with peaks removed, then score the full model ---
    peak_sum = np.zeros_like(f)
    for pk in peaks:
        sigma = pk["bandwidth"] / 2.355
        peak_sum += _gaussian(f, pk["prominence"], pk["cf"], sigma)
    try:
        (offset, exponent), _ = curve_fit(
            _aperiodic, log_f, log_p - peak_sum,
            p0=[offset, exponent], maxfev=10000)
    except Exception:
        pass

    aperiodic = _aperiodic(log_f, offset, exponent)
    model = aperiodic + peak_sum
    ss_res = float(np.sum((log_p - model) ** 2))
    ss_tot = float(np.sum((log_p - np.mean(log_p)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return {
        "offset": float(offset),
        "exponent": float(exponent),
        "peaks": peaks,
        "r_squared": float(r2),
        "error": float(np.sqrt(ss_res / len(log_p))),
        "freqs": f,
        "log_psd": log_p,
        "log_aperiodic": aperiodic,
    }


def detect_band_peak(params: dict, band: tuple, edge_margin: float,
                     min_prominence: float) -> dict:
    """Find the most prominent parameterized peak inside a band.

    A peak within ``edge_margin`` of either band edge is reported but flagged as
    edge-suspect (important for gamma, where a 30 Hz edge peak is unreliable).
    """
    lo, hi = band
    in_band = [pk for pk in params["peaks"] if lo <= pk["cf"] <= hi]
    if not in_band:
        return {"present": False, "accepted": False, "cf": None,
                "prominence": 0.0, "bandwidth": None, "edge_suspect": False,
                "reason": "no peak above aperiodic background in band"}

    best = max(in_band, key=lambda p: p["prominence"])
    edge_suspect = (best["cf"] < lo + edge_margin) or (best["cf"] > hi - edge_margin)
    prominent = best["prominence"] >= min_prominence
    accepted = prominent and not edge_suspect

    if not prominent:
        reason = "peak too weak above aperiodic background"
    elif edge_suspect:
        reason = "peak sits on band edge (suspect, not a clear oscillation)"
    else:
        reason = "accepted"

    return {"present": True, "accepted": accepted, "cf": best["cf"],
            "prominence": best["prominence"], "bandwidth": best["bandwidth"],
            "edge_suspect": edge_suspect, "reason": reason}


# --------------------------------------------------------------------------- #
# Tort Modulation Index + surrogates
# --------------------------------------------------------------------------- #

def _mi_from_bins(bin_idx: np.ndarray, amp: np.ndarray, n_bins: int):
    sums = np.bincount(bin_idx, weights=amp, minlength=n_bins)
    counts = np.bincount(bin_idx, minlength=n_bins)
    mean_amp = sums / np.maximum(counts, 1)
    total = np.sum(mean_amp)
    if total <= 0:
        return 0.0, mean_amp
    p = mean_amp / total
    p = np.clip(p, 1e-12, None)
    entropy = -np.sum(p * np.log(p))
    mi = (np.log(n_bins) - entropy) / np.log(n_bins)
    return float(mi), mean_amp


def tort_modulation_index(phase: np.ndarray, amp: np.ndarray, n_bins: int):
    """Tort's Modulation Index and the preferred coupling phase."""
    edges = np.linspace(-np.pi, np.pi, n_bins + 1)
    bin_idx = np.clip(np.digitize(phase, edges) - 1, 0, n_bins - 1)
    mi, mean_amp = _mi_from_bins(bin_idx, amp, n_bins)
    centers = (edges[:-1] + edges[1:]) / 2.0
    preferred_phase = float(centers[int(np.argmax(mean_amp))])
    return mi, preferred_phase, bin_idx, mean_amp


def surrogate_normalized_pac(phase: np.ndarray, amp: np.ndarray,
                             cfg: PACConfig, rng: np.random.Generator):
    """Compare raw MI against a time-shift surrogate null distribution.

    The amplitude time series is circularly shifted relative to the phase time
    series (preserving each signal's own structure) to build a null where any
    true phase/amplitude relationship is destroyed. Returns z-score, percentile,
    and the raw MI.
    """
    n = len(phase)
    edges = np.linspace(-np.pi, np.pi, cfg.n_phase_bins + 1)
    bin_idx = np.clip(np.digitize(phase, edges) - 1, 0, cfg.n_phase_bins - 1)
    raw_mi, _ = _mi_from_bins(bin_idx, amp, cfg.n_phase_bins)

    min_shift = max(1, int(0.1 * n))
    surr = np.empty(cfg.n_surrogates)
    for i in range(cfg.n_surrogates):
        shift = rng.integers(min_shift, n - min_shift)
        surr[i] = _mi_from_bins(bin_idx, np.roll(amp, shift), cfg.n_phase_bins)[0]

    mu, sd = float(np.mean(surr)), float(np.std(surr))
    z = (raw_mi - mu) / sd if sd > 0 else 0.0
    percentile = float(np.mean(surr < raw_mi) * 100.0)
    return {"raw_mi": float(raw_mi), "z": float(z), "percentile": percentile,
            "surrogate_mean": mu, "surrogate_std": sd}


# --------------------------------------------------------------------------- #
# Waveform shape / harmonic controls
# --------------------------------------------------------------------------- #

def waveform_features(raw: np.ndarray, theta_filtered: np.ndarray):
    """Estimate theta waveform sharpness/asymmetry (bycycle-style, simplified).

    A sharp or asymmetric theta wave is nonsinusoidal and produces harmonics that
    can masquerade as gamma PAC. Returns rise-decay and peak-trough asymmetry in
    [0, 1]; larger means more nonsinusoidal.
    """
    # cycle boundaries = rising zero-crossings of the theta-filtered signal
    sign = np.sign(theta_filtered)
    sign[sign == 0] = 1
    rising = np.where(np.diff(sign) > 0)[0]
    if len(rising) < 3:
        return {"rise_decay_asym": 0.0, "peak_trough_asym": 0.0, "n_cycles": 0}

    rise_decay = []
    peak_sharp = []
    trough_sharp = []
    for a, b in zip(rising[:-1], rising[1:]):
        seg = raw[a:b]
        if len(seg) < 5:
            continue
        peak_i = a + int(np.argmax(seg))
        trough_i = a + int(np.argmin(seg))
        lo_i, hi_i = sorted((peak_i, trough_i))
        rise_t = max(1, hi_i - lo_i)
        decay_t = max(1, b - hi_i + lo_i - a)
        rise_decay.append(abs(rise_t - decay_t) / (rise_t + decay_t))
        if 2 <= peak_i < len(raw) - 2:
            peak_sharp.append(abs(raw[peak_i - 2] - 2 * raw[peak_i] + raw[peak_i + 2]))
        if 2 <= trough_i < len(raw) - 2:
            trough_sharp.append(abs(raw[trough_i - 2] - 2 * raw[trough_i] + raw[trough_i + 2]))

    ps = float(np.mean(peak_sharp)) if peak_sharp else 0.0
    ts = float(np.mean(trough_sharp)) if trough_sharp else 0.0
    pt_asym = abs(ps - ts) / (ps + ts) if (ps + ts) > 0 else 0.0
    return {"rise_decay_asym": float(np.mean(rise_decay)) if rise_decay else 0.0,
            "peak_trough_asym": float(pt_asym),
            "n_cycles": int(len(rising) - 1)}


def harmonic_risk(theta_cf, gamma_cf, params: dict, wave: dict,
                  cfg: PACConfig) -> dict:
    """Estimate the risk that PAC is a nonsinusoidal-theta harmonic artifact."""
    reasons = []
    score = 0

    # 1) is the gamma "peak" sitting near an integer multiple of theta?
    harmonic_hit = False
    if theta_cf and gamma_cf:
        nearest_mult = round(gamma_cf / theta_cf)
        if nearest_mult >= 2:
            if abs(gamma_cf - nearest_mult * theta_cf) <= cfg.harmonic_tolerance:
                harmonic_hit = True
                score += 2
                reasons.append(f"gamma {gamma_cf:.1f} Hz near {nearest_mult}x theta")

    # 2) is there a harmonic comb (peaks at 2x/3x theta) in the spectrum?
    comb = 0
    if theta_cf:
        for mult in (2, 3, 4):
            target = mult * theta_cf
            if any(abs(pk["cf"] - target) <= cfg.harmonic_tolerance
                   for pk in params["peaks"]):
                comb += 1
        if comb >= 2:
            score += 1
            reasons.append(f"{comb} theta harmonics present in spectrum")

    # 3) nonsinusoidal theta waveform
    asym = max(wave.get("rise_decay_asym", 0.0), wave.get("peak_trough_asym", 0.0))
    if asym >= cfg.sharpness_asym_high:
        score += 2
        reasons.append(f"theta waveform sharp/asymmetric ({asym:.2f})")

    level = "low" if score <= 1 else ("medium" if score <= 3 else "high")
    return {"level": level, "score": int(score), "harmonic_hit": harmonic_hit,
            "comb_count": comb, "asymmetry": float(asym),
            "reasons": reasons}


# --------------------------------------------------------------------------- #
# Window-level artifact rejection
# --------------------------------------------------------------------------- #

def assess_window(eeg: np.ndarray, cfg: PACConfig) -> dict:
    """Flag windows that must not be trusted for PAC.

    Checks per channel for clipping/saturation, sudden steps, flat dropouts, and
    broadband high-frequency bursts; aggregates a whole-window verdict. Dropouts
    are flagged, never interpolated.
    """
    n_ch, n = eeg.shape
    flat_run = max(2, int(cfg.flat_run_seconds * cfg.fs))
    per_channel = []
    hf_burst_channels = 0

    for ch in range(n_ch):
        x = eeg[ch]
        flags = []

        # clipping / saturation: many samples pinned at the channel extreme
        amax = np.max(np.abs(x))
        if amax > 0:
            at_rail = np.mean(np.abs(x) >= 0.999 * amax)
            if at_rail >= cfg.clip_fraction_bad:
                flags.append("clipping")

        # sudden voltage steps
        dx = np.diff(x)
        mad = np.median(np.abs(dx - np.median(dx))) + 1e-9
        step_z = np.max(np.abs(dx - np.median(dx))) / (1.4826 * mad)
        if step_z >= cfg.step_z_bad:
            flags.append("step")

        # flat dropout: a run of (near) identical samples
        d_small = np.abs(dx) < (1e-6 + 1e-3 * (np.std(x) + 1e-9))
        if d_small.size:
            longest = _longest_run(d_small)
            if longest >= flat_run:
                flags.append("dropout")

        # broadband high-frequency burst (EMG / eye)
        hf = _hf_fraction(x, cfg.fs)
        if hf >= cfg.hf_fraction_bad:
            flags.append("hf_burst")
            hf_burst_channels += 1

        per_channel.append({"channel": ch, "flags": flags,
                            "hf_fraction": round(float(hf), 3),
                            "step_z": round(float(step_z), 2)})

    broadband = (hf_burst_channels / n_ch) >= cfg.broadband_channel_fraction
    any_bad = any(c["flags"] for c in per_channel)
    if broadband:
        verdict, reason = "poor", "widespread broadband high-frequency activity"
    elif any_bad:
        verdict, reason = "fair", "localized artifacts on some channels"
    else:
        verdict, reason = "acceptable", "no gross artifacts detected"

    return {"verdict": verdict, "reason": reason, "broadband": broadband,
            "hf_burst_channels": int(hf_burst_channels),
            "per_channel": per_channel}


def _longest_run(mask: np.ndarray) -> int:
    longest = run = 0
    for v in mask:
        run = run + 1 if v else 0
        longest = max(longest, run)
    return longest


def _hf_fraction(x: np.ndarray, fs: float) -> float:
    n = len(x)
    if n <= 1:
        return 0.0
    w = np.hanning(n)
    power = np.abs(np.fft.rfft((x - np.mean(x)) * w)) ** 2
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    band = (freqs >= 1.0) & (freqs <= 50.0)
    total = float(np.sum(power[band]))
    if total <= 1e-12:
        return 0.0
    return float(np.sum(power[band & (freqs > 30.0)]) / total)


# --------------------------------------------------------------------------- #
# Per-channel and whole-head PAC
# --------------------------------------------------------------------------- #

def analyze_channel(signal: np.ndarray, cfg: PACConfig,
                    rng: np.random.Generator, channel_index: int = 0,
                    window_flags=None) -> dict:
    """Full PAC pipeline for ONE channel. Never mixes channels."""
    result = {
        "channel": channel_index,
        "status": "ok",
        "valid": False,
        "theta": None,
        "gamma": None,
        "pac": None,
        "waveform": None,
        "harmonic": None,
        "fit_r2": None,
        "window_flags": list(window_flags or []),
        "messages": [],
    }

    if window_flags:
        result["messages"].append(
            "window artifacts present: " + ", ".join(window_flags))

    signal = np.asarray(signal, dtype=float)
    signal = signal - np.mean(signal)

    # --- spectral parameterization: confirm a real theta peak first ---
    freqs, psd = compute_psd(signal, cfg.fs)
    params = parameterize_spectrum(freqs, psd, cfg)
    result["fit_r2"] = round(params["r_squared"], 3)
    result["aperiodic_exponent"] = round(params["exponent"], 3)

    theta = detect_band_peak(params, cfg.theta_band,
                             cfg.theta_edge_margin, cfg.min_peak_prominence)
    gamma = detect_band_peak(params, cfg.gamma_band,
                             cfg.gamma_edge_margin, cfg.min_peak_prominence)
    result["theta"] = {
        "center_hz": round(theta["cf"], 2) if theta["cf"] else None,
        "prominence": round(theta["prominence"], 3),
        "bandwidth_hz": round(theta["bandwidth"], 2) if theta["bandwidth"] else None,
        "accepted": theta["accepted"], "reason": theta["reason"]}
    result["gamma"] = {
        "center_hz": round(gamma["cf"], 2) if gamma["cf"] else None,
        "prominence": round(gamma["prominence"], 3),
        "bandwidth_hz": round(gamma["bandwidth"], 2) if gamma["bandwidth"] else None,
        "accepted": gamma["accepted"], "edge_suspect": gamma["edge_suspect"],
        "type": "oscillatory" if gamma["accepted"] else "broadband/none",
        "reason": gamma["reason"]}

    if params["r_squared"] < cfg.min_fit_r2:
        result["status"] = "fit_poor"
        result["messages"].append(
            f"spectral fit poor (R^2={params['r_squared']:.2f}) - PAC not calculated")
        return result

    if not theta["accepted"]:
        result["status"] = "theta_unreliable"
        result["messages"].append("Theta phase unreliable - PAC not calculated")
        return result

    # --- PAC: theta phase vs gamma amplitude, this channel only ---
    edge = int(cfg.edge_seconds * cfg.fs)
    th_phase, _, th_filt = analytic_phase_amplitude(
        signal, cfg.fs, cfg.theta_band, edge, cfg.filter_order)
    _, gm_amp, _ = analytic_phase_amplitude(
        signal, cfg.fs, cfg.gamma_band, edge, cfg.filter_order)
    raw_trim = signal[edge:len(signal) - edge] if 2 * edge < len(signal) else signal

    mi, preferred_phase, _, _ = tort_modulation_index(
        th_phase, gm_amp, cfg.n_phase_bins)
    surr = surrogate_normalized_pac(th_phase, gm_amp, cfg, rng)

    wave = waveform_features(raw_trim, th_filt)
    harm = harmonic_risk(theta["cf"], gamma["cf"] if gamma["accepted"] else None,
                         params, wave, cfg)

    result["pac"] = {
        "estimator": ESTIMATOR_NAME,
        "modulation_index": round(mi, 5),
        "z": round(surr["z"], 2),
        "percentile": round(surr["percentile"], 1),
        "surrogate_mean": round(surr["surrogate_mean"], 5),
        "surrogate_std": round(surr["surrogate_std"], 5),
        "preferred_phase_rad": round(preferred_phase, 3),
        "significant": surr["percentile"] >= cfg.sig_percentile and surr["z"] >= 2.0,
        "gamma_ratio": round(gamma["cf"] / theta["cf"], 2)
        if (gamma["cf"] and theta["cf"]) else None,
    }
    result["waveform"] = {k: round(v, 3) if isinstance(v, float) else v
                          for k, v in wave.items()}
    result["harmonic"] = harm
    result["valid"] = True

    if harm["level"] == "high":
        result["messages"].append(
            "high harmonic-contamination risk - PAC may be a theta-harmonic artifact")
    return result


def analyze_pac(eeg: np.ndarray, quality: list, cfg: PACConfig,
                rng: np.random.Generator | None = None) -> dict:
    """Channel-by-channel PAC for the whole head, plus a conservative summary.

    ``eeg``      : (n_channels, n_samples) raw EEG (NOT spatially combined).
    ``quality``  : per-channel quality dicts from the streamer ("good"/"fair"/"bad").
    Returns per-channel PAC results and an uncertainty-aware summary. Bad/flat
    channels and artifact windows are excluded, never interpolated.
    """
    if rng is None:
        rng = np.random.default_rng()
    eeg = np.asarray(eeg, dtype=float)
    n_ch = eeg.shape[0]

    window = assess_window(eeg, cfg)
    win_flags_by_ch = {c["channel"]: c["flags"] for c in window["per_channel"]}

    channels = []
    for ch in range(n_ch):
        q = quality[ch]["quality"] if ch < len(quality) else "good"
        flags = win_flags_by_ch.get(ch, [])
        if q == "bad" or flags:
            channels.append({
                "channel": ch, "status": "excluded", "valid": False,
                "quality": q, "window_flags": flags, "pac": None,
                "messages": [
                    "excluded: " + (q if q == "bad" else ", ".join(flags))],
                "theta": None, "gamma": None, "harmonic": None,
                "waveform": None, "fit_r2": None,
            })
            continue
        res = analyze_channel(eeg[ch], cfg, rng, channel_index=ch,
                              window_flags=flags)
        res["quality"] = q
        channels.append(res)

    valid = [c for c in channels if c.get("valid")]
    supporting = [c for c in valid if c["pac"]["significant"]]
    z_values = [c["pac"]["z"] for c in valid]
    mi_values = [c["pac"]["modulation_index"] for c in valid]
    high_harm = [c for c in valid if c["harmonic"]["level"] == "high"]

    summary = {
        "estimator": ESTIMATOR_NAME,
        "n_channels": n_ch,
        "n_valid": len(valid),
        "n_supporting": len(supporting),
        "supporting_label": f"{len(supporting)}/{n_ch}",
        "median_z": round(float(np.median(z_values)), 2) if z_values else None,
        "median_mi": round(float(np.median(mi_values)), 5) if mi_values else None,
        "max_percentile": round(max((c["pac"]["percentile"] for c in valid),
                                    default=0.0), 1),
        "window_quality": window["verdict"],
        "window_reason": window["reason"],
        "harmonic_risk": ("high" if high_harm else
                          ("medium" if any(c["harmonic"]["level"] == "medium"
                                           for c in valid) else "low")),
        "verdict": _overall_verdict(valid, supporting, window),
    }

    return {"summary": summary, "window": window, "channels": channels}


def _overall_verdict(valid, supporting, window) -> str:
    if window["verdict"] == "poor":
        return "window rejected - PAC not interpretable"
    if not valid:
        return "no channel had a reliable theta peak - PAC not calculated"
    if not supporting:
        return "theta present but no significant PAC vs surrogates"
    if any(c["harmonic"]["level"] == "high" for c in supporting):
        return "significant PAC but high harmonic-contamination risk"
    return f"significant theta-gamma PAC on {len(supporting)} channel(s)"
