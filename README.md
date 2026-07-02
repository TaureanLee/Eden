# Eden

> **Eden** is an [Exergis](#) product by **Taurean Lee** — a real-time EEG
> brainwave, phase–amplitude coupling, and cortical-criticality reader.

Reads live EEG from a wide range of headsets via [BrainFlow](https://brainflow.org)
(Unicorn Hybrid Black, Muse 2 / S, OpenBCI Cyton / Ganglion, BrainBit, Neurosity,
FreeEEG32, and more) and shows your brainwave activity in real time — either in a
**web app** (recommended) or directly in the terminal.

You pick and connect your headset **right in the browser** — no command line
required. The web app streams your dominant brainwave band, per-band powers, and a
live theta–gamma coupling score straight from the headset to your browser. No
headset yet? Choose the built-in **Synthetic** device to explore everything with a
realistic simulated brain.

---

## Quick start (one step)

From the Eden folder:

- **Windows** — double-click **`run.bat`** (or run `.\run.ps1` in PowerShell).
- **macOS / Linux** — run **`./run.sh`** in a terminal.

The launcher sets up a local Python environment the first time (this only happens
once), starts Eden, and opens your browser at **http://127.0.0.1:5000**. Then pick
your headset in the page — or choose **Synthetic** to explore with no hardware.

```powershell
.\run.ps1 --synthetic     # no headset: explore with a simulated brain
./run.sh --synthetic      # macOS / Linux
```

Any `server.py` flag (see the table below) can be passed to the launcher directly.
Requires **Python 3.10+**. Your EEG data never leaves your machine.

> **Shipping Eden as a product?** See [DEPLOY.md](DEPLOY.md) — the analyzer runs
> locally (it needs your headset), and the marketing site in [`site/`](site/)
> deploys to Vercel.

---

## 1. Manual setup (optional)

Prefer to set things up by hand instead of using the launcher?

```powershell
cd "c:\Users\taure\Desktop\Eden"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Re-activate the environment in any new terminal with
> `.\.venv\Scripts\Activate.ps1` before running the commands below.

---

## 2. Connect your headset

Most headsets only need to be reachable by your computer before Eden can stream:

- **Bluetooth headsets** (Unicorn, Muse, BrainBit): pair them with your computer
  first. On Windows: **Settings → Bluetooth & devices → Add device**. The Unicorn
  appears as `UN-XXXX.XX.XX`; its serial is also printed on the device.
- **Wired boards** (OpenBCI Cyton / Ganglion, FreeEEG32): plug in the USB dongle
  and note its serial port (e.g. `COM3` on Windows, `/dev/ttyUSB0` on Linux).
- **WiFi boards** (OpenBCI WiFi shield, Neurosity): note the device IP address.

Make sure no other program (e.g. Unicorn Suite) is already connected to the
device — only one app can stream at a time. You enter any of these details in the
web UI when you connect (see §3).

---

## 3. Go live with the web app (recommended)

Start the server:

```powershell
python server.py
```

Then open **http://127.0.0.1:5000** in your browser and use the **device** panel
at the top of the page:

1. Pick your headset from the **headset** dropdown (or **Synthetic** for a demo).
2. Fill in any connection fields it asks for (serial, serial port, MAC, or IP).
3. Press **connect**. Eden shows the exact error if it fails, so you can fix the
   pairing/port and try again — no restart needed. Press **disconnect** to switch
   devices at any time.

> Prefer the command line? You can still auto-connect on startup, e.g.
> `python server.py --synthetic`, `python server.py --device unicorn --serial UN-2024.11.05`,
> or `python server.py --device cyton --serial-port COM3`.

The page shows:

- **theta–gamma frequency ratio** — live `gamma / theta` peak ratio and a
  cognition score. This is a *frequency ratio only*, not phase–amplitude
  coupling — see the PAC panel for genuine coupling.
- **phase–amplitude coupling (PAC)** — rigorous, per-channel theta–gamma PAC
  with validity and uncertainty (see §4 below).
- **criticality (Trident-state)** — a *separate* estimate of whether the cortex
  is subcritical, near-critical, or supercritical (see §5 below). It is computed
  independently of PAC.
- **real-time** — the last 60 samples of the ratio as a chart.
- **session average** — record an averaged session for a set duration and
  save a screenshot of the result.
- **bands** — live power per band, with the dominant band highlighted.
- **calibration** — generate test noise at selected frequencies and compare
  real vs test spectra (1-50 Hz) in the bottom chart.

The status dot (top right) tells you the connection state:

| Status text                    | Meaning                                              |
|--------------------------------|------------------------------------------------------|
| `live`                         | Streaming real data from the headset. ✅             |
| `not connected — select a headset above` | Pick a device and press connect.            |
| `connecting to … device`       | Eden is opening the device session.                  |
| `waiting for … device`         | Connected, buffering the first few seconds of data.  |
| `no data — check the headset`  | Connected but the stream went quiet (check the band).|
| `reconnecting…`                | The live stream dropped; Eden retries automatically. |
| `device error: …`              | BrainFlow reported an error (shown verbatim).        |
| `server unreachable`           | The Python server isn't running.                     |

If a headset won't connect, fix the pairing/serial/port and try **connect** again
from the device panel — no need to restart the server.

### Try the web app without hardware

```powershell
python server.py --synthetic
```

This streams a synthetic board so you can see the full UI working with no device.

### Web app options

The web UI is the primary way to connect; these flags are optional conveniences
for auto-connecting on startup.

| Flag            | Default | Description                                        |
|-----------------|---------|----------------------------------------------------|
| `--device`      | (none)  | Auto-connect to a device key (e.g. `unicorn`, `muse_2`, `cyton`) |
| `--serial`      | (none)  | Serial number/name for the auto-connect device     |
| `--serial-port` | (none)  | Serial port for the auto-connect device            |
| `--synthetic`   | off     | Auto-connect to the synthetic (demo) board         |
| `--window`      | 3.0     | Analysis window in seconds                         |
| `--interval`    | 1.0     | Seconds between updates                            |
| `--port`        | 5000    | HTTP port for the web app                          |
| `--no-browser`  | off     | Don't open a browser automatically on startup      |
| `--debug`       | off     | Verbose server logging                             |

### Calibration mode in the UI

At the bottom of the page, use the **calibration** panel to tune and test:

- `frequency (Hz)` sets the dominant synthetic test frequency (1-50 Hz).
- `noise level` controls broadband noise intensity.
- `amplitude` controls the synthetic sine amplitude.
- `test signal` toggle enables/disables the generated test trace.

The bottom chart overlays:

- **real**: normalized spectrum from your incoming EEG (after filtering)
- **test**: normalized spectrum from the generated test signal

This makes it easier to calibrate how your processing reacts to specific
frequency content.

---

## 4. Phase–amplitude coupling (PAC)

The **PAC panel** answers a different question from the theta–gamma frequency
ratio: *is the phase of the theta rhythm actually modulating the amplitude of
gamma activity?* It is implemented as a standalone, testable pipeline in
[`pac_analysis.py`](pac_analysis.py) (numpy + scipy only, no hardware/Flask
dependencies) and validated against synthetic signals in
[`simulate_pac_validation.py`](simulate_pac_validation.py).

### What it does (per channel, never averaged)

1. **Per-channel** — PAC is computed independently on every channel. Channels
   are never averaged before PAC, because averaging cancels out coupling that
   differs in phase across the scalp.
2. **Confirm a real theta rhythm** — the power spectrum is parameterized with a
   specparam/FOOOF-style fit (aperiodic 1/f background + Gaussian peaks). A
   theta peak must rise above the aperiodic background to be used. If it does
   not, the channel reports **“θ unreliable — PAC not calculated”**.
3. **Edge-of-band guard** — a “peak” landing exactly at a band edge (e.g. 30 Hz)
   is treated as suspect and flagged rather than trusted.
4. **Window quality / artifact rejection** — windows with dropouts, clipping,
   step/level shifts, high-frequency bursts, or broadband contamination are
   rejected. Dropouts are **not interpolated** before PAC.
5. **Genuine PAC, not the frequency ratio** — coupling is quantified with
   **Tort’s Modulation Index** (KL divergence of the amplitude-by-phase
   distribution from uniform).
6. **Surrogate comparison** — the raw MI is normalized against a time-shift
   surrogate null distribution, yielding a **z-score** and a **percentile**.
   Significance requires clearing the surrogate threshold.
7. **Harmonic test** — nonsinusoidal (sharp) theta produces gamma-band
   harmonics that masquerade as PAC. The pipeline measures waveform asymmetry
   and harmonic combs and reports a **harmonic risk** (low/medium/high). A
   near-perfect 10:1 frequency relationship is treated as *more* suspicious of
   harmonics, not less.
8. **Pipeline self-test** — `simulate_pac_validation.py` runs the full pipeline
   on synthetic signals (genuine PAC, uncoupled, sharp-theta harmonics, 1/f
   noise, transients, jaw bursts, dropouts) to guard against filtering
   artifacts and confirm each detector fires correctly.
9. **Uncertainty, not one number** — the panel reports the estimator name, the
   z-score and surrogate percentile, the number of supporting channels, the
   window quality, and the harmonic risk — rather than a single percentage.

> The criticality / “Trident-state” estimate is intentionally a separate
> concern. PAC is deliberately *not* an input to it, and PAC itself is never
> renamed “criticality.” The two are independent metrics shown side by side.

Run the validation suite at any time:

```powershell
python simulate_pac_validation.py
```

---

## 5. Criticality (Trident-state)

The **criticality panel** answers a separate question from PAC: *where is the
cortex on the axis from* **subcritical** *(under-aroused, inhibition-dominant)*
*through* **near-critical** *(balanced, the optimal “in the zone” state) to*
**supercritical** *(over-aroused, excitation-dominant)?* It lives in
[`criticality_analysis.py`](criticality_analysis.py) and is validated by
[`simulate_criticality_validation.py`](simulate_criticality_validation.py).

**It is computed independently of PAC.** PAC is deliberately *not* an input. The
two metrics are shown next to each other so any relationship between them (for
example, the hypothesis that near-criticality co-occurs with strong theta–gamma
coupling) can be *observed* rather than baked in by construction. Neither metric
is derived from the other.

### Markers (all per-channel, never spatially averaged first)

1. **Aperiodic 1/f exponent** as an excitation/inhibition (E:I) proxy: a steeper
   slope leans inhibition-dominant/subcritical, a flatter slope leans
   excitation-dominant/supercritical.
2. **Arousal balance** from band powers (fast beta+gamma vs alpha): fast-heavy =
   high arousal (supercritical side), alpha-heavy = low arousal (subcritical).
3. **Long-range temporal correlations (LRTC)** via DFA of the alpha envelope,
   which peak near criticality — weighted lightly and caveated because it needs
   minutes of clean data to be reliable.

The panel reports the state, a **confidence** level, the 1/f exponent, the
arousal balance, and a **Trident remedy** — *which* entrainment band you might
gently encourage to nudge the cortex back toward the near-critical sweet spot,
and which prong it represents: gamma (left/executive prong) to wake an
under-aroused brain, alpha (right/creative prong) to calm an over-aroused one,
and theta (central/fluid-intelligence prong) to hold the near-critical state.
The Trident describes the *suggested remedy*, not a claim about the mode you are
currently in. These scalp markers are indirect proxies, so a personal baseline
improves accuracy.

Run its validation suite:

```powershell
python simulate_criticality_validation.py
```

---

## 6. Terminal-only reader (optional)

Prefer a plain text view? `brainwave_reader.py` prints the dominant band and a
bar chart in the terminal — no browser needed.

```powershell
python brainwave_reader.py --serial UN-2024.11.05   # or omit --serial to auto-discover
python brainwave_reader.py --synthetic              # no hardware
```

---

## How it works

- Streams 8 EEG channels at 250 Hz from the Unicorn Hybrid Black.
- Every second it analyzes the last 3 seconds of data.
- `DataFilter.get_avg_band_powers` computes average power per band across all channels.
- The band with the highest power is your **dominant brainwave**.
- The web app additionally reports the **theta–gamma frequency ratio**
  (`gamma / theta`) as a cognition score that peaks at a ratio of 10, and a
  rigorous **per-channel PAC** estimate (see §5) computed over a longer window.

### Frequency bands

| Band  | Range    | Associated with        |
|-------|----------|------------------------|
| Delta | 1-4 Hz   | Deep sleep             |
| Theta | 4-8 Hz   | Drowsiness, meditation |
| Alpha | 8-13 Hz  | Relaxed, eyes closed   |
| Beta  | 13-30 Hz | Active thinking, focus |
| Gamma | 30-50 Hz | High-level cognition   |

---

## Troubleshooting

- **Page loads but status stays red** — the headset isn't streaming. Confirm it's
  powered on, paired, and not in use by another app; pass `--serial` explicitly;
  then restart the server.
- **`BrainFlow` / board errors in the terminal** — the same message is shown in the
  browser status. Usually means the device isn't paired or the serial is wrong.
- **Nothing in the browser** — make sure the `python server.py` window is still
  running and that you opened the correct port (default `5000`).
- **Test the pipeline anytime** with `--synthetic` to rule out app vs. hardware issues.
