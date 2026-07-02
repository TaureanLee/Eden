"""
Eden — web server for live EEG brainwave, PAC, and criticality visualization.

Eden is an Exergis product by Taurean Lee.

Runs BrainFlow in a background thread, computes average band powers, and
streams them to the browser via Server-Sent Events (SSE). Serves a minimal
Bootstrap UI from the static/ folder.

Usage:
    python server.py                      # auto-discover paired Unicorn
    python server.py --serial UN-XXXX     # target a specific device
    python server.py --synthetic          # no hardware: synthetic board
    python server.py --port 5000          # change the HTTP port
"""

import argparse
import json
import logging
import math
import threading
import time
import webbrowser

import numpy as np
from flask import Flask, Response, request, send_from_directory
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds
from brainflow.exit_codes import BrainFlowError

import pac_analysis as pac
import criticality_analysis as crit

log = logging.getLogger("eden")

BANDS = [
    ("delta", "1-4 Hz"),
    ("theta", "4-8 Hz"),
    ("alpha", "8-13 Hz"),
    ("beta", "13-30 Hz"),
    ("gamma", "30-50 Hz"),
]

# --- Device catalog -------------------------------------------------------
# Eden can connect to any BrainFlow-supported headset directly from the web UI.
# Each catalog entry names a BrainFlow board and the connection fields that
# board typically needs. Boards not present in the installed BrainFlow version
# are skipped automatically, so the list always matches what is usable.

# Connection fields map 1:1 onto BrainFlowInputParams attributes. Only these
# keys are ever read from a /connect request (allow-list).
PARAM_FIELDS = {
    "serial_number": {"label": "Serial / device name",
                      "placeholder": "e.g. UN-2021.05.36"},
    "serial_port": {"label": "Serial port",
                    "placeholder": "e.g. COM3 or /dev/ttyUSB0"},
    "mac_address": {"label": "MAC address",
                    "placeholder": "e.g. F4:0E:11:75:75:9C"},
    "ip_address": {"label": "IP address",
                   "placeholder": "e.g. 192.168.4.1"},
    "ip_port": {"label": "IP port",
                "placeholder": "e.g. 6677"},
}

# (key, friendly name, BoardIds attribute name, [connection field keys], note)
_DEVICE_CATALOG_RAW = [
    ("synthetic", "Synthetic (demo, no hardware)", "SYNTHETIC_BOARD", [],
     "Generates a realistic fake brain so you can explore Eden without a headset."),
    ("unicorn", "Unicorn Hybrid Black", "UNICORN_BOARD", ["serial_number"],
     "Pair the headset over Bluetooth first. Serial is optional if only one is paired."),
    ("muse_2", "Muse 2", "MUSE_2_BOARD", ["mac_address", "serial_port"],
     "Connects over native Bluetooth. Set serial port only if you use a BLED112 dongle."),
    ("muse_s", "Muse S", "MUSE_S_BOARD", ["mac_address", "serial_port"],
     "Connects over native Bluetooth. Set serial port only if you use a BLED112 dongle."),
    ("muse_2016", "Muse 2016", "MUSE_2016_BOARD", ["mac_address", "serial_port"],
     "Connects over native Bluetooth. Set serial port only if you use a BLED112 dongle."),
    ("cyton", "OpenBCI Cyton", "CYTON_BOARD", ["serial_port"],
     "Plug in the USB dongle and enter its serial port."),
    ("cyton_daisy", "OpenBCI Cyton + Daisy", "CYTON_DAISY_BOARD", ["serial_port"],
     "Plug in the USB dongle and enter its serial port."),
    ("ganglion", "OpenBCI Ganglion", "GANGLION_BOARD", ["serial_port", "mac_address"],
     "Plug in the USB dongle. MAC is optional (auto-discovered if blank)."),
    ("cyton_wifi", "OpenBCI Cyton (WiFi shield)", "CYTON_WIFI_BOARD",
     ["ip_address", "ip_port"], "Enter the WiFi shield IP and port."),
    ("ganglion_wifi", "OpenBCI Ganglion (WiFi shield)", "GANGLION_WIFI_BOARD",
     ["ip_address", "ip_port"], "Enter the WiFi shield IP and port."),
    ("brainbit", "BrainBit", "BRAINBIT_BOARD", ["serial_number"],
     "Connects over Bluetooth. Serial is optional."),
    ("crown", "Neurosity Crown", "CROWN_BOARD", ["serial_number", "ip_address"],
     "Enter the device name or IP shown in the Neurosity app."),
    ("notion2", "Neurosity Notion 2", "NOTION_2_BOARD", ["serial_number", "ip_address"],
     "Enter the device name or IP shown in the Neurosity app."),
    ("notion1", "Neurosity Notion 1", "NOTION_1_BOARD", ["serial_number", "ip_address"],
     "Enter the device name or IP shown in the Neurosity app."),
    ("freeeeg32", "FreeEEG32", "FREEEEG32_BOARD", ["serial_port"],
     "Enter the serial port of the board."),
    ("emotiv_insight", "Emotiv Insight", "EMOTIV_INSIGHT_BOARD", ["serial_port", "mac_address"],
     "Connects over Bluetooth."),
]


def build_device_catalog() -> list:
    """Return the catalog entries whose boards exist in this BrainFlow build."""
    catalog = []
    for key, name, board_attr, fields, note in _DEVICE_CATALOG_RAW:
        board_id = getattr(BoardIds, board_attr, None)
        if board_id is None:
            continue
        try:
            board_value = int(board_id)
        except (TypeError, ValueError):
            continue
        catalog.append({
            "key": key,
            "name": name,
            "board_id": board_value,
            "note": note,
            "fields": [
                {"key": f, **PARAM_FIELDS[f]}
                for f in fields if f in PARAM_FIELDS
            ],
        })
    return catalog


def _device_by_key(key: str):
    for entry in build_device_catalog():
        if entry["key"] == key:
            return entry
    return None


def _json_default(obj):
    """Make numpy scalars/arrays JSON serializable; sanitize non-finite floats."""
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def safe_json(payload) -> str:
    """Serialize to JSON, tolerating numpy types and non-finite floats."""
    try:
        return json.dumps(payload, default=_json_default)
    except ValueError:
        # NaN/Infinity slipped through (allow_nan default); retry strictly clean.
        return json.dumps(payload, default=_json_default, allow_nan=False)

# Classic EEG band edges in Hz (matches BANDS order above).
BAND_RANGES = [(1.0, 4.0), (4.0, 8.0), (8.0, 13.0), (13.0, 30.0), (30.0, 50.0)]

# Fine-grained per-channel bands (matches the Unicorn Bandpower layout, with the
# beta band split into low/mid/high). Used for the detailed per-channel readout
# only; the 5-band BANDS above still drive the ratio, PAC, and criticality.
DETAIL_BANDS = [
    ("delta", "delta", 1.0, 4.0),
    ("theta", "theta", 4.0, 8.0),
    ("alpha", "alpha", 8.0, 13.0),
    ("beta_low", "beta low", 13.0, 18.0),
    ("beta_mid", "beta mid", 18.0, 24.0),
    ("beta_high", "beta high", 24.0, 30.0),
    ("gamma", "gamma", 30.0, 50.0),
]

# Short, friendly meaning for the dominant band (shown like the Unicorn app).
BAND_MEANINGS = {
    "delta": "Deep sleep, healing, the unconscious",
    "theta": "Creativity, fantasy, deep meditation",
    "alpha": "Relaxed focus, calm, flow",
    "beta": "Active thinking, alertness, focus",
    "beta_low": "Relaxed alertness, light focus",
    "beta_mid": "Active thinking, engagement",
    "beta_high": "High alertness, stress, intensity",
    "gamma": "Peak focus, insight, binding",
}


# Signal-quality thresholds. BrainFlow does NOT expose true electrode impedance
# for the Unicorn Hybrid Black, so signal quality is inferred from each channel's
# statistics relative to its peers: amplitude outliers (muscle/movement
# artifacts), flat channels (disconnected), and high-frequency/EMG dominance.
QUALITY_AMP_BAD = 3.0    # channel std > 3x the median channel std => artifact/bad
QUALITY_AMP_FAIR = 2.0   # channel std > 2x the median => fair
QUALITY_FLAT = 0.15      # channel std < 0.15x the median => flat/disconnected
QUALITY_HF_BAD = 0.60    # >60% of 1-50 Hz power above 30 Hz => muscle (EMG) artifact
QUALITY_HF_FAIR = 0.45   # >45% high-frequency power => fair


class EEGStreamer:
    """Reads from a BrainFlow board and keeps the latest band powers.

    The board is selected and connected at runtime (from the web UI or CLI), so
    the streamer starts in a disconnected state and can switch headsets without
    restarting the process.
    """

    def __init__(self, window: float, interval: float, fast_interval: float = 0.1,
                 display_window: float = 1.0):
        self.window = window
        self.interval = interval
        # The bandpower/ratio display refreshes on this fast cadence, decoupled
        # from the slower, expensive PAC/criticality math so it stays as
        # responsive as a dedicated bandpower app.
        self.fast_interval = max(0.04, float(fast_interval))
        # The live readout analyses only this most-recent slice of signal. A
        # short window keeps latency low (a Hanning taper's effective lag is
        # ~half the window), so the display tracks the headset in real time.
        # PAC/criticality still use the longer, more rigorous window below.
        self.display_window = max(0.5, float(display_window))
        self._lock = threading.Lock()
        self._latest = None
        self._running = False
        self._thread = None
        self._heavy_thread = None
        self._error = None
        self._connecting = False

        # Latest expensive results, refreshed by the heavy worker and merged into
        # every fast payload. Per-channel quality is shared the same way.
        self._pac_cache = None
        self._crit_cache = None
        self._quality_cache = None

        # Liveness tracking: BrainFlow's ring buffer returns stale samples if the
        # headset drops (Bluetooth out of range, powered off), so we watch the
        # newest sample timestamp to tell "really streaming" from "frozen buffer".
        self._last_stream_ts = -1.0
        self._last_advance_ts = 0.0
        # One-shot notice the client shows as a toast (e.g. auto-disconnect on
        # signal loss). Cleared once the client has acknowledged it.
        self._notice = None

        # Board-dependent state; populated on connect().
        self.board = None
        self.board_id = None
        self.device = None
        self.device_key = None
        self.sampling_rate = 250
        self.eeg_channels = []
        self.window_samples = int(self.window * self.sampling_rate)
        self.display_samples = int(self.display_window * self.sampling_rate)
        self.timestamp_channel = None

        self._rng = np.random.default_rng()
        self.pac_window = max(self.window, 8.0)
        self.pac_window_samples = int(self.pac_window * self.sampling_rate)
        self.pac_cfg = pac.PACConfig(fs=float(self.sampling_rate))
        self.crit_cfg = crit.CriticalityConfig(fs=float(self.sampling_rate))

        self._test_signal = {
            "enabled": True,
            "frequency_hz": 10.0,
            "noise_level": 0.35,
            "amplitude": 1.0,
        }
        # Channels the user has manually disabled in the UI. These are excluded
        # from the combined signal, PAC, and criticality (treated as 'bad').
        self._removed_channels: set[int] = set()

    # --- Board lifecycle --------------------------------------------------

    def _configure_board(self, board_id: int, params: BrainFlowInputParams,
                         device_key: str, device_name: str) -> None:
        """Build a BoardShim for the chosen board and derive its parameters."""
        self.board = BoardShim(board_id, params)
        self.board_id = board_id
        self.device_key = device_key
        self.device = device_name
        self.sampling_rate = BoardShim.get_sampling_rate(board_id)
        self.eeg_channels = BoardShim.get_eeg_channels(board_id)
        self.window_samples = int(self.window * self.sampling_rate)
        self.display_samples = int(self.display_window * self.sampling_rate)
        # Timestamp row: its last value only advances when genuinely new samples
        # arrive, so it's a reliable "is the headset still streaming?" signal
        # (unlike the ring-buffer count, which saturates on long sessions).
        try:
            self.timestamp_channel = BoardShim.get_timestamp_channel(board_id)
        except Exception:
            self.timestamp_channel = None

        # PAC/criticality run on a longer raw window so theta cycles, the
        # spectral fit, and the surrogate null are all stable.
        self.pac_window = max(self.window, 8.0)
        self.pac_window_samples = int(self.pac_window * self.sampling_rate)
        self.pac_cfg = pac.PACConfig(fs=float(self.sampling_rate))
        self.crit_cfg = crit.CriticalityConfig(fs=float(self.sampling_rate))

    def _verify_signal(self) -> None:
        """Confirm a real headset is actually streaming live EEG.

        After start_stream() a device may report 'connected' yet deliver nothing
        (off, out of range, electrodes not seated). We sample for a moment and
        require non-trivial, non-flat EEG before accepting the connection, so the
        UI can't sit on a dead link. Raises on failure (caught by connect()).
        """
        deadline = time.time() + 4.0
        need = max(int(0.5 * self.sampling_rate), 32)
        last_reason = "no signal — the headset isn't sending any data"
        while time.time() < deadline:
            time.sleep(0.4)
            try:
                data = self.board.get_current_board_data(need)
            except Exception as exc:
                last_reason = str(exc)
                continue
            if data.shape[1] < need:
                last_reason = "headset connected but not streaming samples yet"
                continue
            eeg = data[self.eeg_channels, :]
            if eeg.size == 0:
                last_reason = "no EEG channels reported by the headset"
                continue
            # Reject an all-zero or perfectly flat signal (no electrode contact).
            spread = float(np.max(np.std(eeg, axis=1)))
            if spread <= 1e-6:
                last_reason = ("headset streaming but the signal is flat — check "
                               "it's powered on and electrodes are seated")
                continue
            return  # live, varying EEG confirmed
        raise RuntimeError(last_reason)

    @staticmethod
    def _friendly_connect_error(exc: Exception) -> str:
        """Translate a raw BrainFlow connect failure into actionable guidance.

        The raw codes (e.g. BOARD_NOT_READY_ERROR:7) are opaque to users, so map
        the common hardware causes to plain-language fixes.
        """
        text = str(exc)
        low = text.lower()
        if "no signal" in low or "flat" in low or "not streaming samples" in low \
                or "no eeg channels" in low:
            return text  # _verify_signal already phrases these for the user
        if "board_not_ready" in low or "unable to prepare" in low:
            return ("headset busy or not streaming — close any other app using "
                    "it (e.g. Unicorn Suite/Bandpower), make sure it's powered on "
                    "and paired, then try connecting again")
        if "port" in low and ("open" in low or "access" in low or "use" in low):
            return ("serial port is in use or unavailable — close other apps and "
                    "check the port/COM setting, then try again")
        if "no such" in low or "not found" in low or "invalid serial" in low:
            return ("device not found — check it's powered on, paired/plugged in, "
                    "and that the serial/MAC field matches your headset")
        if "timeout" in low:
            return ("connection timed out — move the headset closer, re-pair it, "
                    "then try again")
        return f"could not connect: {text}"

    def connect(self, device_key: str, field_values: dict) -> dict:
        """Connect to a catalog device. Returns the resulting status dict.

        Stops any current stream first, builds the board with the supplied
        connection fields, and starts the acquisition loop with a short retry.
        Connection failures are surfaced (not raised) so the UI can show them.
        """
        entry = _device_by_key(device_key)
        if entry is None:
            with self._lock:
                self._error = f"unknown device '{device_key}'"
            return self.status()

        # Tear down any existing session before switching devices.
        self.disconnect()

        allowed = {f["key"] for f in entry["fields"]}
        params = BrainFlowInputParams()
        for key, value in (field_values or {}).items():
            if key in allowed and value not in (None, ""):
                setattr(params, key, str(value).strip())

        with self._lock:
            self._connecting = True
            self._error = None
            self._latest = None

        try:
            self._configure_board(entry["board_id"], params,
                                  entry["key"], entry["name"])
        except Exception as exc:
            log.exception("Failed to configure board %s", device_key)
            with self._lock:
                self._connecting = False
                self._error = f"could not configure device: {exc}"
            return self.status()

        last_exc = None
        for attempt in range(1, 3):
            try:
                self.board.prepare_session()
                self.board.start_stream()
                # For real hardware, confirm that actual signal is flowing
                # before we declare success. The synthetic board always
                # produces data, so it's exempt and simulations just work.
                if self.board_id != int(BoardIds.SYNTHETIC_BOARD):
                    self._verify_signal()
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 - surfaced to UI
                last_exc = exc
                log.warning("Connect attempt %d to %s failed: %s",
                            attempt, self.device, exc)
                try:
                    self.board.stop_stream()
                except Exception:
                    pass
                try:
                    self.board.release_session()
                except Exception:
                    pass
                time.sleep(0.5 * attempt)

        if last_exc is not None:
            log.error("Could not connect to %s: %s", self.device, last_exc)
            with self._lock:
                self._connecting = False
                self._error = self._friendly_connect_error(last_exc)
            return self.status()

        with self._lock:
            self._connecting = False
            self._error = None
            self._running = True
            self._pac_cache = None
            self._crit_cache = None
            self._quality_cache = None
            self._last_stream_ts = -1.0
            self._last_advance_ts = time.time()
            self._notice = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._heavy_thread = threading.Thread(target=self._heavy_loop, daemon=True)
        self._heavy_thread.start()
        log.info("Connected to %s (board_id=%s, fs=%s Hz, %d ch)",
                 self.device, self.board_id, self.sampling_rate,
                 len(self.eeg_channels))
        return self.status()

    def disconnect(self) -> dict:
        """Stop the acquisition loop and release the board, if any."""
        thread = self._thread
        heavy = self._heavy_thread
        with self._lock:
            self._running = False
            self._thread = None
            self._heavy_thread = None
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        if heavy and heavy.is_alive():
            heavy.join(timeout=3.0)
        if self.board is not None:
            try:
                self.board.stop_stream()
            except Exception:
                pass
            try:
                self.board.release_session()
            except Exception:
                pass
        with self._lock:
            self.board = None
            self._latest = None
            self._connecting = False
            self._pac_cache = None
            self._crit_cache = None
            self._quality_cache = None
        log.info("Disconnected from %s", self.device or "device")
        return self.status()


    def _teardown_on_signal_loss(self) -> None:
        """Fully disconnect after the headset stops streaming.

        Called from inside the display thread, so it must NOT join that thread
        (which would deadlock). It stops the loops, releases the board, and
        records a one-shot notice for the UI to show as a toast.
        """
        device = self.device or "the headset"
        with self._lock:
            # Signal both loops to exit; this thread returns right after.
            self._running = False
            self._thread = None
            heavy = self._heavy_thread
            self._heavy_thread = None
        # Join the heavy worker (a different thread) before releasing the board
        # so it can't be mid-read when the session is torn down.
        if heavy and heavy.is_alive():
            heavy.join(timeout=3.0)
        board = self.board
        if board is not None:
            try:
                board.stop_stream()
            except Exception:
                pass
            try:
                board.release_session()
            except Exception:
                pass
        with self._lock:
            self.board = None
            self._latest = None
            self._connecting = False
            self._pac_cache = None
            self._crit_cache = None
            self._quality_cache = None
            self._error = (f"signal lost from {device} — disconnected "
                           "automatically. Check it's on and in Bluetooth range.")
            self._notice = {
                "id": time.time(),
                "type": "error",
                "message": (f"Signal lost from {device}. Eden disconnected "
                            "automatically — check it's powered on and in range."),
            }
        log.info("Auto-disconnected from %s after signal loss", device)


    def get_removed_channels(self) -> list:
        with self._lock:
            return sorted(self._removed_channels)

    def set_removed_channels(self, channels) -> list:
        """Replace the set of user-disabled channels (validated against range)."""
        n = len(self.eeg_channels)
        cleaned = set()
        for c in channels or []:
            try:
                idx = int(c)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < n:
                cleaned.add(idx)
        with self._lock:
            self._removed_channels = cleaned
            return sorted(self._removed_channels)

    def get_test_signal(self) -> dict:
        with self._lock:
            return dict(self._test_signal)

    def set_test_signal(self, updates: dict) -> dict:
        with self._lock:
            cfg = dict(self._test_signal)

            if "enabled" in updates:
                cfg["enabled"] = bool(updates["enabled"])
            if "frequency_hz" in updates:
                cfg["frequency_hz"] = float(np.clip(float(updates["frequency_hz"]), 1.0, 50.0))
            if "noise_level" in updates:
                cfg["noise_level"] = float(np.clip(float(updates["noise_level"]), 0.0, 2.0))
            if "amplitude" in updates:
                cfg["amplitude"] = float(np.clip(float(updates["amplitude"]), 0.0, 5.0))

            self._test_signal = cfg
            return dict(self._test_signal)

    def _generate_test_signal(self, num_samples: int, test_cfg: dict) -> np.ndarray:
        """Create a controllable sine + broadband noise test signal."""
        t = np.arange(num_samples) / self.sampling_rate
        freq = float(test_cfg["frequency_hz"])
        noise_level = float(test_cfg["noise_level"])
        amplitude = float(test_cfg["amplitude"])
        channel_count = len(self.eeg_channels)

        channels = []
        for ch in range(channel_count):
            phase = (ch / max(1, channel_count - 1)) * (np.pi / 2.0)
            carrier = np.sin(2.0 * np.pi * freq * t + phase)

            harmonic = np.zeros_like(carrier)
            harmonic_freq = freq * 2.0
            if harmonic_freq <= 50.0:
                harmonic = 0.25 * np.sin(2.0 * np.pi * harmonic_freq * t + (phase * 0.5))

            noise = np.random.normal(0.0, noise_level, num_samples)
            channels.append((amplitude * carrier) + harmonic + noise)

        return np.array(channels)

    def _compute_normalized_spectrum(self, data: np.ndarray, low_hz: float = 1.0, high_hz: float = 50.0) -> tuple[list, list]:
        """Compute an average channel spectrum and normalize it to [0, 1]."""
        n = data.shape[1]
        if n <= 1:
            return [], []

        detrended = data - np.mean(data, axis=1, keepdims=True)
        window = np.hanning(n)
        fft_vals = np.fft.rfft(detrended * window, axis=1)
        power = np.mean(np.abs(fft_vals) ** 2, axis=0)
        freqs = np.fft.rfftfreq(n, d=1.0 / self.sampling_rate)

        mask = (freqs >= low_hz) & (freqs <= high_hz)
        selected_freqs = freqs[mask]
        selected_power = power[mask]
        if selected_power.size == 0:
            return [], []

        max_power = float(np.max(selected_power))
        if max_power <= 1e-12:
            normalized = np.zeros_like(selected_power)
        else:
            normalized = selected_power / max_power

        return selected_freqs.tolist(), normalized.tolist()

    def _assess_signal_quality(self, eeg_data: np.ndarray):
        """
        Infer per-electrode signal quality directly from the EEG data.

        BrainFlow exposes no true impedance for the Unicorn, so each channel is
        scored against its peers. Channels that are amplitude outliers (large
        muscle/movement artifacts), flat (disconnected), or dominated by
        high-frequency EMG content are flagged. Returns the per-channel report
        and combination weights (good=1.0, fair=0.5, bad=0.0).
        """
        n_channels = eeg_data.shape[0]
        detrended = eeg_data - np.mean(eeg_data, axis=1, keepdims=True)
        stds = np.std(detrended, axis=1)
        median_std = float(np.median(stds)) if n_channels else 0.0
        eps = 1e-9

        results = []
        weights = []
        for ch in range(n_channels):
            std = float(stds[ch])
            rel_amp = std / (median_std + eps)
            hf_frac = self._high_frequency_fraction(detrended[ch])

            if (std < QUALITY_FLAT * median_std
                    or rel_amp > QUALITY_AMP_BAD
                    or hf_frac > QUALITY_HF_BAD):
                quality, weight = "bad", 0.0
            elif rel_amp > QUALITY_AMP_FAIR or hf_frac > QUALITY_HF_FAIR:
                quality, weight = "fair", 0.5
            else:
                quality, weight = "good", 1.0

            results.append({
                "channel": ch,
                "noise": round(rel_amp, 2),
                "hf_ratio": round(hf_frac, 2),
                "quality": quality,
            })
            weights.append(weight)

        return results, np.array(weights, dtype=float)

    def _high_frequency_fraction(self, signal: np.ndarray) -> float:
        """Fraction of 1-50 Hz power that lies above 30 Hz (EMG/muscle indicator)."""
        n = signal.shape[0]
        if n <= 1:
            return 0.0
        window = np.hanning(n)
        power = np.abs(np.fft.rfft(signal * window)) ** 2
        freqs = np.fft.rfftfreq(n, d=1.0 / self.sampling_rate)
        band = (freqs >= 1.0) & (freqs <= 50.0)
        total = float(np.sum(power[band]))
        if total <= 1e-12:
            return 0.0
        high = float(np.sum(power[band & (freqs > 30.0)]))
        return high / total

    def _robust_combine(self, eeg_data: np.ndarray, weights: np.ndarray) -> np.ndarray:
        """
        Combine the 8 electrodes into one artifact-resistant 'global' signal.

        Channels are weighted by signal quality and averaged sample-by-sample.
        The shared brain rhythm is correlated across electrodes and adds
        constructively, while local artifacts (e.g. muscle activity on a single
        electrode) are uncorrelated and partially cancel; flagged-bad channels
        get zero weight and are excluded entirely. This lets the dominant brain
        frequency survive even when one or more electrodes are noisy.
        """
        w = np.array(weights, dtype=float)
        if not np.any(w > 0):
            w = np.ones(eeg_data.shape[0])
        w = w / np.sum(w)
        return np.tensordot(w, eeg_data, axes=(0, 0))

    def _band_powers_from_signal(self, signal: np.ndarray) -> np.ndarray:
        """Relative power per band (sums to 1) for a single combined signal."""
        n = signal.shape[0]
        if n <= 1:
            return np.zeros(len(BAND_RANGES))
        detrended = signal - np.mean(signal)
        window = np.hanning(n)
        psd = np.abs(np.fft.rfft(detrended * window)) ** 2
        freqs = np.fft.rfftfreq(n, d=1.0 / self.sampling_rate)

        powers = np.array([
            float(np.sum(psd[(freqs >= lo) & (freqs < hi)]))
            for (lo, hi) in BAND_RANGES
        ])
        total = float(np.sum(powers))
        if total <= 1e-12:
            return np.zeros(len(BAND_RANGES))
        return powers / total

    def _band_detail_per_channel(self, eeg_data: np.ndarray, quality: list) -> dict:
        """Per-channel absolute bandpower (dBµV) for the fine-grained bands.

        Mirrors what a dedicated bandpower app shows: every electrode gets its own
        power value in each band, plus its own dominant band. Power is a properly
        scaled one-sided PSD integrated over each band (µV²), then converted to
        dBµV. Removed/bad channels are reported but flagged so the UI can dim them.
        """
        n_ch, n = eeg_data.shape
        band_keys = [b[0] for b in DETAIL_BANDS]
        band_labels = [b[1] for b in DETAIL_BANDS]

        if n <= 1:
            return {"channels": [], "bands": band_keys, "band_labels": band_labels}

        detrended = eeg_data - np.mean(eeg_data, axis=1, keepdims=True)
        window = np.hanning(n)
        win_norm = float(np.sum(window ** 2))
        fft_vals = np.fft.rfft(detrended * window, axis=1)
        # One-sided power spectral density in µV²/Hz (Unicorn streams µV).
        psd = (np.abs(fft_vals) ** 2) / (self.sampling_rate * win_norm)
        if psd.shape[1] > 2:
            psd[:, 1:-1] *= 2.0
        freqs = np.fft.rfftfreq(n, d=1.0 / self.sampling_rate)
        df = float(freqs[1] - freqs[0]) if freqs.size > 1 else 1.0

        quality_by_ch = {q.get("channel"): q for q in (quality or [])}
        channels = []
        for ch in range(n_ch):
            powers_uv2 = []
            for (_key, _label, lo, hi) in DETAIL_BANDS:
                mask = (freqs >= lo) & (freqs < hi)
                powers_uv2.append(float(np.sum(psd[ch, mask]) * df))
            powers_db = [round(10.0 * math.log10(p + 1e-9), 1) for p in powers_uv2]
            dom_idx = int(np.argmax(powers_uv2)) if any(powers_uv2) else 0
            q = quality_by_ch.get(ch, {})
            channels.append({
                "channel": ch,
                "power_db": powers_db,
                "dominant": band_keys[dom_idx],
                "quality": q.get("quality", "unknown"),
                "removed": bool(q.get("removed", False)),
            })
        return {"channels": channels, "bands": band_keys, "band_labels": band_labels}

    def _compute_pac(self, quality: list) -> dict:
        """Run channel-by-channel theta-gamma PAC on the raw electrodes.

        Uses a dedicated longer window so theta cycles, the spectral fit, and the
        surrogate null are stable. Channels are analysed independently (never
        spatially combined) and bad/artifact channels are excluded, not
        interpolated. Returns a JSON-serializable PAC report, or a 'warming up'
        status until enough data has accumulated.
        """
        try:
            data = self.board.get_current_board_data(self.pac_window_samples)
            min_samples = int(4.0 * self.sampling_rate)
            if data.shape[1] < min_samples:
                return {"summary": {"verdict": "collecting data for PAC...",
                                    "estimator": pac.ESTIMATOR_NAME},
                        "channels": [], "window": None,
                        "seconds": round(data.shape[1] / self.sampling_rate, 1)}
            eeg = data[self.eeg_channels, :]
            result = pac.analyze_pac(eeg, quality, self.pac_cfg, self._rng)
            result["seconds"] = round(eeg.shape[1] / self.sampling_rate, 1)
            return result
        except Exception as exc:
            return {"summary": {"verdict": f"PAC error: {exc}",
                                "estimator": pac.ESTIMATOR_NAME},
                    "channels": [], "window": None}

    def _compute_criticality(self, quality: list) -> dict:
        """Estimate cortical criticality (subcritical / near-critical /
        supercritical) on the raw electrodes.

        This is a SEPARATE metric from PAC and is computed independently: PAC is
        never passed in as an input. Channels are analysed per-electrode and bad
        channels are excluded, not interpolated.
        """
        try:
            data = self.board.get_current_board_data(self.pac_window_samples)
            min_samples = int(4.0 * self.sampling_rate)
            if data.shape[1] < min_samples:
                return {"summary": {"state": "collecting",
                                    "label": "collecting data for criticality...",
                                    "estimator": crit.ESTIMATOR_NAME,
                                    "confidence": 0.0},
                        "channels": [],
                        "seconds": round(data.shape[1] / self.sampling_rate, 1)}
            eeg = data[self.eeg_channels, :]
            result = crit.analyze_criticality(eeg, quality, self.crit_cfg)
            result["seconds"] = round(eeg.shape[1] / self.sampling_rate, 1)
            return result
        except Exception as exc:
            return {"summary": {"state": "error",
                                "label": f"criticality error: {exc}",
                                "estimator": crit.ESTIMATOR_NAME,
                                "confidence": 0.0},
                    "channels": []}

    def _get_peak_frequency_in_band(self, data: np.ndarray, low_hz: float, high_hz: float) -> float:
        """
        Get the dominant frequency within a specific band using FFT.
        Returns the peak frequency in Hz within the band range.
        """
        try:
            # Compute FFT across all channels and take mean spectrum
            fft_vals = []
            for ch_data in data:
                fft = np.fft.fft(ch_data)
                power = np.abs(fft) ** 2
                fft_vals.append(power)
            mean_power = np.mean(fft_vals, axis=0)
            
            # Frequency bins
            freqs = np.fft.fftfreq(data.shape[1], 1.0 / self.sampling_rate)
            freqs = freqs[:len(freqs) // 2]
            mean_power = mean_power[:len(mean_power) // 2]
            
            # Find peak within band
            band_mask = (freqs >= low_hz) & (freqs <= high_hz)
            if np.any(band_mask):
                peak_idx = np.argmax(mean_power[band_mask])
                peak_freq = freqs[band_mask][peak_idx]
                return float(peak_freq)
            else:
                # Fallback to band center
                return (low_hz + high_hz) / 2.0
        except Exception:
            # Fallback to band center if FFT fails
            return (low_hz + high_hz) / 2.0

    def _loop(self) -> None:
        """Fast display loop: bandpower, per-channel detail, ratio, spectrum.

        Runs on the fast cadence and never blocks on the expensive PAC/criticality
        math (that lives in _heavy_loop), so the bandpower readout stays as
        responsive as a dedicated bandpower app. The latest heavy results are
        merged in from cache.
        """
        time.sleep(min(self.display_window, 1.0))
        while self._running:
            start = time.time()
            try:
                data = self.board.get_current_board_data(self.display_samples)
                if data.shape[1] < self.display_samples:
                    time.sleep(self.fast_interval)
                    continue

                # Liveness check: is the headset still delivering NEW samples, or
                # is the buffer frozen (Bluetooth dropout / device off)? The
                # newest sample timestamp only advances when fresh data arrives.
                now_live = time.time()
                if self.timestamp_channel is not None and \
                        self.timestamp_channel < data.shape[0]:
                    newest = float(data[self.timestamp_channel, -1])
                    if newest != self._last_stream_ts:
                        self._last_stream_ts = newest
                        self._last_advance_ts = now_live
                else:
                    # No timestamp row (e.g. synthetic edge cases): assume live.
                    self._last_advance_ts = now_live
                is_live = (now_live - self._last_advance_ts) < 1.5
                if not is_live:
                    # Samples have stopped flowing (Bluetooth dropout / device
                    # off). Tear everything down automatically and leave a notice
                    # for the UI to surface, rather than freezing on stale values.
                    log.warning("Signal lost from %s — auto-disconnecting",
                                self.device or "device")
                    self._teardown_on_signal_loss()
                    return

                # Assess per-electrode signal quality, then combine the 8
                # electrodes into one artifact-resistant global signal so a
                # single noisy electrode can't corrupt the frequency estimate.
                eeg_data = data[self.eeg_channels, :]
                impedance_data, weights = self._assess_signal_quality(eeg_data)

                # Honor channels the user manually disabled in the UI: mark them
                # excluded so they drop out of the combined signal, PAC, and
                # criticality (all of which already skip 'bad'/zero-weight).
                removed = set(self.get_removed_channels())
                if removed:
                    for ch in removed:
                        if ch < len(impedance_data):
                            impedance_data[ch]["quality"] = "bad"
                            impedance_data[ch]["removed"] = True
                            weights[ch] = 0.0

                # Share quality with the heavy worker so PAC/criticality use the
                # same per-channel assessment without recomputing it.
                with self._lock:
                    self._quality_cache = impedance_data

                combined = self._robust_combine(eeg_data, weights)
                combined_2d = combined[np.newaxis, :]

                # Band powers from the combined (interference-summed) signal.
                band_powers = self._band_powers_from_signal(combined)
                dominant_idx = int(np.argmax(band_powers))
                dominant_name = BANDS[dominant_idx][0]

                # Per-channel fine-grained bandpower (Unicorn-style detail).
                band_detail = self._band_detail_per_channel(eeg_data, impedance_data)

                # Normalized real spectrum (1-50 Hz) of the combined signal.
                spectrum_freqs, real_spectrum = self._compute_normalized_spectrum(combined_2d)

                # Build controllable test signal and spectrum for quick calibration.
                test_cfg = self.get_test_signal()
                if test_cfg["enabled"]:
                    test_data = self._generate_test_signal(self.display_samples, test_cfg)
                    _, test_spectrum = self._compute_normalized_spectrum(test_data)
                else:
                    test_spectrum = [0.0 for _ in real_spectrum]

                # Theta-gamma coupling: ratio of peak frequencies (oscillation count)
                # Get the dominant frequency within each band
                theta_freq = self._get_peak_frequency_in_band(combined_2d, 4.0, 8.0)
                gamma_freq = self._get_peak_frequency_in_band(combined_2d, 30.0, 50.0)

                # Ratio = how many gamma oscillations fit in one theta oscillation
                ratio = gamma_freq / theta_freq if theta_freq > 0.1 else 0.0

                # Merge the most recent heavy (PAC/criticality) results.
                with self._lock:
                    pac_result = self._pac_cache
                    criticality_result = self._crit_cache
                if pac_result is None:
                    pac_result = {"summary": {"verdict": "collecting data for PAC...",
                                              "estimator": pac.ESTIMATOR_NAME},
                                  "channels": [], "window": None}
                if criticality_result is None:
                    criticality_result = {"summary": {"state": "collecting",
                                                      "label": "collecting data for criticality...",
                                                      "estimator": crit.ESTIMATOR_NAME,
                                                      "confidence": 0.0},
                                          "channels": []}

                payload = {
                    "timestamp": time.time(),
                    "dominant": dominant_name,
                    "dominant_meaning": BAND_MEANINGS.get(dominant_name, ""),
                    "ratio": ratio,
                    "theta_freq": float(theta_freq),
                    "gamma_freq": float(gamma_freq),
                    "test_signal": test_cfg,
                    "pac": pac_result,
                    "criticality": criticality_result,
                    "spectrum": {
                        "frequencies": spectrum_freqs,
                        "real_power": real_spectrum,
                        "test_power": test_spectrum,
                    },
                    "bands": [
                        {"name": name, "range": rng, "power": float(power)}
                        for (name, rng), power in zip(BANDS, band_powers)
                    ],
                    "band_detail": band_detail,
                    "electrodes": impedance_data,
                    "live": True,
                }
                with self._lock:
                    self._latest = payload
                    # A successful read clears any prior transient hiccup so a
                    # momentary wireless dropout doesn't leave a sticky error.
                    if self._error is not None:
                        self._error = None
            except BrainFlowError as exc:
                # Real headsets (Bluetooth/serial) can momentarily go "not
                # ready" while warming up or after a brief link drop. Treat this
                # as transient: keep the thread alive and retry, without latching
                # a hard error the way a genuine fault would.
                log.warning("Acquisition not ready (transient): %s", exc)
                with self._lock:
                    if self._latest is None:
                        # Only surface to the UI if we never got data at all.
                        self._error = "waiting for the headset to start streaming…"
                time.sleep(max(self.fast_interval, 0.2))
                continue
            except Exception as exc:  # keep the thread alive, surface the error
                log.exception("Display loop error")
                with self._lock:
                    self._error = str(exc)

            # Pace to the fast cadence, accounting for the work just done.
            elapsed = time.time() - start
            time.sleep(max(0.0, self.fast_interval - elapsed))

    def _heavy_loop(self) -> None:
        """Slow worker: rigorous PAC and criticality on the long raw window.

        These are expensive (surrogate nulls, spectral fits, DFA) so they run on
        their own cadence and publish into a cache the fast display loop reads,
        keeping the bandpower readout snappy.
        """
        time.sleep(min(self.window, 1.0))
        while self._running:
            start = time.time()
            try:
                with self._lock:
                    quality = self._quality_cache
                if quality is not None:
                    pac_result = self._compute_pac(quality)
                    criticality_result = self._compute_criticality(quality)
                    with self._lock:
                        self._pac_cache = pac_result
                        self._crit_cache = criticality_result
            except Exception:
                log.exception("Heavy analysis loop error")
            elapsed = time.time() - start
            time.sleep(max(0.0, self.interval - elapsed))


    def latest(self):
        with self._lock:
            return self._latest

    def status(self) -> dict:
        with self._lock:
            payload = self._latest
            connected = self.board is not None
            return {
                "device": self.device,
                "device_key": self.device_key,
                "connected": connected,
                "connecting": self._connecting,
                "streaming": bool(self._running),
                "has_data": payload is not None,
                "error": self._error,
                "notice": self._notice,
                "sampling_rate": self.sampling_rate if connected else None,
                "channel_count": len(self.eeg_channels) if connected else 0,
            }

    def stop(self) -> None:
        self.disconnect()



def create_app(streamer: EEGStreamer) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="")

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/status")
    def status():
        return Response(safe_json(streamer.status()), mimetype="application/json")

    @app.route("/devices")
    def devices():
        return Response(safe_json({"devices": build_device_catalog(),
                                   "status": streamer.status()}),
                        mimetype="application/json")

    @app.route("/connect", methods=["POST"])
    def connect():
        body = request.get_json(silent=True) or {}
        device_key = body.get("device")
        if not isinstance(device_key, str) or not device_key:
            return Response(safe_json({"error": "missing 'device'"}),
                            status=400, mimetype="application/json")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        result = streamer.connect(device_key, params)
        ok = result.get("connected") and not result.get("error")
        return Response(safe_json({"ok": bool(ok), "status": result}),
                        status=200 if ok else 502,
                        mimetype="application/json")

    @app.route("/disconnect", methods=["POST"])
    def disconnect():
        result = streamer.disconnect()
        return Response(safe_json({"ok": True, "status": result}),
                        mimetype="application/json")

    @app.route("/test-signal", methods=["GET", "POST"])
    def test_signal():
        if request.method == "GET":
            return Response(safe_json(streamer.get_test_signal()), mimetype="application/json")

        updates = request.get_json(silent=True) or {}
        updated = streamer.set_test_signal(updates)
        return Response(safe_json(updated), mimetype="application/json")

    @app.route("/channels", methods=["GET", "POST"])
    def channels():
        if request.method == "GET":
            return Response(safe_json({"removed": streamer.get_removed_channels()}),
                            mimetype="application/json")

        body = request.get_json(silent=True) or {}
        removed = streamer.set_removed_channels(body.get("removed", []))
        return Response(safe_json({"removed": removed}), mimetype="application/json")

    @app.route("/stream")
    def stream():
        def gen():
            last_ts = None
            last_beat = time.time()
            # Prime the connection so the browser's EventSource opens promptly.
            yield ": connected\n\n"
            while True:
                payload = streamer.latest()
                now = time.time()
                if payload and payload["timestamp"] != last_ts:
                    last_ts = payload["timestamp"]
                    last_beat = now
                    yield f"data: {safe_json(payload)}\n\n"
                elif now - last_beat >= 15.0:
                    # Heartbeat keeps proxies from closing an idle connection
                    # and lets the client detect a live-but-dataless stream.
                    last_beat = now
                    yield ": ping\n\n"
                # Poll faster than the producer so fresh bandpower frames are
                # forwarded with minimal added latency.
                time.sleep(0.03)

        return Response(gen(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Eden brainwave web server.")
    parser.add_argument("--device", default="",
                        help="Auto-connect to a catalog device key on startup "
                             "(e.g. unicorn, muse_2, cyton). Otherwise pick one "
                             "in the web UI.")
    parser.add_argument("--serial", default="",
                        help="Serial number/name for the auto-connect device.")
    parser.add_argument("--serial-port", default="",
                        help="Serial port for the auto-connect device.")
    parser.add_argument("--synthetic", action="store_true",
                        help="Auto-connect to the synthetic (demo) board.")
    parser.add_argument("--window", type=float, default=3.0, help="Analysis window (s).")
    parser.add_argument("--display-window", type=float, default=1.0,
                        help="Live bandpower/ratio window (s); smaller = lower latency.")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="PAC/criticality update interval (s).")
    parser.add_argument("--fast-interval", type=float, default=0.1,
                        help="Bandpower/ratio display refresh interval (s).")
    parser.add_argument("--port", type=int, default=5000, help="HTTP port.")
    parser.add_argument("--debug", action="store_true", help="Verbose logging.")
    parser.add_argument("--no-browser", action="store_true",
                        help="Do not open a web browser automatically on startup.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    BoardShim.enable_dev_board_logger()

    streamer = EEGStreamer(args.window, args.interval, args.fast_interval,
                           args.display_window)

    # Optional auto-connect for CLI workflows; the web UI is the primary path.
    auto_key = "synthetic" if args.synthetic else (args.device or "")
    if auto_key:
        fields = {}
        if args.serial:
            fields["serial_number"] = args.serial
        if args.serial_port:
            fields["serial_port"] = args.serial_port
        status = streamer.connect(auto_key, fields)
        if status.get("error"):
            log.warning("Auto-connect to '%s' failed: %s. "
                        "Pick a device in the web UI instead.",
                        auto_key, status["error"])
    else:
        log.info("No device specified. Choose and connect one in the web UI.")

    app = create_app(streamer)
    url = f"http://127.0.0.1:{args.port}"
    log.info("Open %s in your browser. Press Ctrl+C to stop.", url)

    if not args.no_browser:
        def _open_browser():
            time.sleep(1.2)  # let the server bind the port first
            try:
                webbrowser.open(url)
            except Exception as exc:  # pragma: no cover - best effort only
                log.debug("Could not open a browser automatically: %s", exc)
        threading.Thread(target=_open_browser, daemon=True).start()

    try:
        app.run(host="127.0.0.1", port=args.port, threaded=True)
    finally:
        streamer.stop()


if __name__ == "__main__":
    main()
