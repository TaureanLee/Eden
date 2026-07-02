# Your Brain, Live: How Eden Turns Invisible Electricity Into an Honest Picture

### A real-time window into the rhythms behind thinking and memory — built to tell real coupling apart from convincing fakes

*By Taurean Lee*

---

## What this app actually is

This app reads the tiny electrical signals your brain makes and shows them on a screen in real time, like a live weather report for your head.

Those signals come in repeating waves called **rhythms**, and the app's main job is to watch whether a **slow** rhythm and a **fast** rhythm are working together as a team — a partnership that turns out to be closely tied to thinking and memory. The technical name for that partnership is **phase–amplitude coupling (PAC)** between the **theta** band (slow) and the **gamma** band (fast), measured live and separately for each sensor.

What makes this app unusual is that it is built to tell the difference between *real* coupling and signals that merely *look* coupled. Every claim it makes is gated behind oscillation detection, artifact rejection, surrogate-based significance testing, and a harmonic-artifact safeguard — and it reports a confidence measure instead of a single confident-sounding number.

> The point isn't to sound sure. It's to be honest about how sure it actually is.

---

## Why your brain makes electricity

Your brain is built from billions of cells called **neurons**, and when they signal each other they release tiny bursts of electricity — far too small to feel or to hurt you, on the order of millionths of a volt.

A single neuron is invisible from outside your skull. What we actually detect is huge numbers of neurons doing the same thing at the same moment, because when they sync up their tiny voltages add together into something measurable, and when they fire randomly they cancel out.

That is exactly why **rhythms** are the thing worth watching: a brain rhythm is a large population of neurons growing loud and quiet together in a repeating pattern, where the *speed* of the pattern is its **frequency** and the *size* of the swing is its **amplitude**.

More precisely, scalp signals are dominated by the summed **post-synaptic potentials** of cortical pyramidal neurons whose dendrites line up perpendicular to the surface, so the recording reflects synchronous excitability fluctuations across populations — and it is those fluctuations in timing that let one rhythm's phase gate the activity of another, faster one.

---

## How the signals are captured

A headset called the **Unicorn Hybrid Black** does the capturing. Think of a cap with small metal buttons (**electrodes**) resting against your scalp, each listening to the electrical buzz at its spot.

There are **8 of these spots** (called **channels**), which matters because different brain regions do different jobs — a rhythm at the front can be doing something completely different from one at the back, so eight vantage points beat a single guess.

The headset samples each spot **250 times per second** and streams the data to your computer over Bluetooth. It samples that fast because you can only capture a wave by checking far more often than it wiggles, and gamma can wiggle up to about 50 times a second.

That rate isn't arbitrary: the **Nyquist criterion** says you must sample faster than twice the highest frequency you care about, so a 50 Hz ceiling needs more than 100 Hz — and 250 Hz leaves comfortable headroom for anti-alias filtering. Because the skull and scalp smear each source across several electrodes (**volume conduction**), keeping the channels separate — as this app does — preserves location-specific coupling that blending them together would blur or cancel.

---

## What the computer does with it

Two pieces work together like a kitchen: a program called `server.py` is the cook that does all the math, and a web page in your browser is the table where the results are served with charts, numbers, and colors.

The cook keeps a rolling memory of the last few seconds of brain data, and roughly once a second it grabs that recent chunk, runs every calculation, and hands a fresh summary to the page — which is why it feels live without you ever refreshing. Under the hood the page *subscribes* to the server and the server *pushes* each new result the moment it's ready, a one-way live feed.

Concretely, the backend is a Flask server that acquires from the board on a background thread and streams JSON over **Server-Sent Events (SSE)**, maintaining a sliding analysis buffer from which it computes band powers and the full PAC analysis each interval. The frontend (`app.js`) parses every payload and repaints the display, so the speed of capture and the speed of drawing stay independent. You reach it like any website, at **http://127.0.0.1:5000**, which simply means "this same computer."

---

## The brain's different rhythms

Your brain's buzz isn't one steady note — it's more like several rhythms playing at once, sorted by speed in **Hz** (wiggles per second):

| Wave name | Speed       | When you usually see it          |
|-----------|-------------|----------------------------------|
| **Delta** | 1–4 Hz      | Deep, dreamless sleep            |
| **Theta** | 4–8 Hz      | Sleepy, daydreaming, meditating  |
| **Alpha** | 8–13 Hz     | Calm and relaxed, eyes closed    |
| **Beta**  | 13–30 Hz    | Awake, thinking, focused         |
| **Gamma** | 30–50 Hz    | Hard concentration, high focus   |

The app measures how strong each band is and highlights the strongest as your "dominant brainwave," but the two it cares about most are **theta** and **gamma**, because their partnership is the part tied to thinking and memory.

"Strength" here means how much **power** sits in that frequency range right now, which the app computes per band and compares — yet power alone never tells you whether two bands are *cooperating*, only how loud each one is on its own.

That distinction is the whole reason a dedicated coupling measure exists: these band boundaries are useful conventions rather than hard biological lines, power is estimated from the power spectral density (Welch's method), and crucially **power and cross-frequency coupling are independent** — two recordings can carry identical theta and gamma power while one is tightly coupled and the other not at all.

---

## Theta–gamma coupling and cognition

When the slow theta rhythm and the fast gamma rhythm cooperate, picture a big slow ocean wave (theta) carrying many small fast ripples (gamma) on its surface. When the slow wave's *timing* governs how *big* those ripples grow, that is **theta–gamma coupling** — like tapping your foot to a slow beat while strumming fast notes exactly in time with each tap.

Scientists think this is one way the brain organizes information for **memory** and **focus**, and a helpful image is a train: the theta wave is the train and each gamma ripple is a car, every car holding one item — one thing on a shopping list — so a single theta wave can carry several items at once, which is one leading picture of how your **working memory** juggles a handful of things.

Because each gamma ripple rides at a *different point* along the theta wave — early, middle, late — the brain can keep those items in **sequence** rather than mashing them together, and stronger, cleaner coupling has been linked in research to better memory and attention. That ordering is the real connection to **cognition**, because the coupling appears to be part of *how* careful thinking is carried out.

In the formal account, this is the **Lisman–Jensen "theta–gamma neural code,"** in which each item is a gamma cycle nested inside a theta cycle and its place in the sequence is encoded by *where* in the theta phase it sits, predicting a working-memory capacity near theta/gamma ≈ 7±2 items. Measured coupling in hippocampal and neocortical circuits scales with memory load and predicts whether something is successfully remembered, and seems to coordinate communication between regions.

> Two warnings come straight out of this, and the app respects both: coupling is a *correlation*, not proof of any single mechanism — and PAC estimates are notoriously easy to fake with artifacts.

Which is precisely why the next section exists.

---

## How the app stays honest about coupling

It is dangerously easy to *think* you found brain teamwork when you really found a glitch, so the app behaves like a strict, skeptical scientist and refuses to claim coupling until it has ruled out the boring explanations. Each safeguard below is described once, plainly, and then sharpened.

**It studies each spot on its own.** All eight channels are analyzed separately and never blended first, because coupling can sit at a different *phase* on different parts of the scalp, so averaging the waveforms together can cancel a genuine effect — keeping them apart both protects the signal and reveals *where* coupling is happening.

**It checks that a real slow wave even exists.** Before measuring coupling it confirms a genuine theta rhythm is present, and if it can't find one it plainly says *"theta unreliable — PAC not calculated."* Technically it splits the spectrum into the **aperiodic 1/f background** — the natural downward slope of brain noise — and the true **peaks** rising above it (a specparam/FOOOF-style fit), because a theta phase is only meaningful if there's a real oscillatory peak to read it from; otherwise the "phase" is just noise.

**It distrusts the edges.** A rhythm that appears right at the boundary of the search range — say exactly 30 Hz — is flagged as suspect rather than trusted, since peaks landing precisely on a band edge usually come from filter edge effects or spillover instead of a real oscillator.

**It throws out bad moments instead of patching them.** Blinks, jaw clenches, head scratches, or an electrode briefly losing contact create ugly spikes that aren't brain rhythms, so the app detects these "bad windows" and discards them, screening for clipping, sudden level shifts, flat **dropouts**, and broadband high-frequency bursts (the classic muscle/EMG signature). Dropouts are **never interpolated** before the analysis, because filling in invented data can manufacture coupling that was never there.

**It measures real coupling, not a cheap stand-in.** Strength is quantified with the **Tort Modulation Index (MI)**, which sorts gamma amplitude into bins by theta phase and measures how far that distribution sits from perfectly flat (via KL divergence): a flat distribution means no coupling, a peaky one means gamma reliably prefers a particular theta phase.

**It compares the result against pure luck.** The app deliberately scrambles the data's timing to see what "no real coupling, just chance" looks like, then asks whether the true result clearly beats that — like checking whether six heads in a row is genuinely lucky or merely ordinary. It does this by building a **surrogate null distribution**: it time-shifts the amplitude against the phase many times, recomputes MI each time, and expresses the real MI as a **z-score** and **percentile** against that null, demanding a high percentile before calling anything significant, because even random data produces a small nonzero MI.

**It watches for fakers.** A slow wave with a sharp, jagged shape can *imitate* fast ripples without any real fast rhythm, so the app rates a **harmonic risk** of low/medium/high — and, counterintuitively, a *too-perfect* whole-number ratio like exactly 10-to-1 raises suspicion, because real biology is rarely that tidy. The reason is that a non-sinusoidal theta wave carries Fourier **harmonics** at integer multiples that can leak into the gamma band and masquerade as coupling, so the app measures waveform asymmetry and looks for evenly spaced harmonic combs to warn when apparent coupling is really a waveform-shape artifact rather than an independent gamma oscillator.

**It rehearses on fake brains with known answers.** Before being trusted on a real brain, the whole pipeline is run on synthetic signals whose correct answers are already known — genuine coupling, no coupling, the harmonic trick, pure noise, transients, muscle bursts, and dropouts — and it must get them all right; that suite lives in `simulate_pac_validation.py`, guards against filtering artifacts, and currently passes every check.

**It shows uncertainty instead of false confidence.** Rather than a single tidy percentage, every result carries the estimator's name, the **z-score** and **surrogate percentile**, how many channels **agree**, the **window quality**, and the **harmonic risk**, because honestly reporting how sure it is matters more than sounding sure.

---

## Criticality: subcritical, near-critical, or supercritical

Separately from coupling, the app estimates how "tuned" your whole cortex is right now, placing it on a single line that runs from **subcritical** on the left, through **near-critical** in the middle, to **supercritical** on the right.

Subcritical is the sleepy, under-aroused end where the brain is a bit too calm and sluggish to respond crisply; supercritical is the over-aroused, racing-mind end where activity is too hot and jumpy to hold steady; and near-critical is the balanced sweet spot in between — often described as being "in the zone," alert but not stressed.

The idea comes from physics: many complex systems work best poised right at the boundary between too-quiet and too-chaotic, and the brain appears to be tuned toward that same edge, where it best balances stability with flexibility.

To place you on that line the app reads three independent clues from the EEG: the **steepness of the background 1/f curve**, which acts as a proxy for the balance between excitation and inhibition (a steep curve leans toward the calm, inhibition-heavy subcritical side, a flat curve toward the excited supercritical side); the **arousal balance** of fast rhythms versus alpha (lots of fast beta and gamma means high arousal, lots of alpha means low); and **long-range temporal correlations**, a measure of how the rhythm's ups and downs stay subtly linked over time, which tend to peak right at the critical point. Because that last clue needs minutes of clean data to trust, the app weights it lightly and says so.

> Crucially, this criticality estimate is computed completely separately from PAC — coupling is never fed into it — so the two sit side by side as independent readouts.

That independence matters: if you *do* notice that strong theta–gamma coupling tends to show up when you're near-critical, that's a real pattern you observed rather than something the app wired together on purpose.

The panel also maps the state onto a "Trident" *remedy* — not a claim about which mental mode you're in, but a suggestion of which rhythm you might gently encourage to nudge the brain back toward the near-critical sweet spot: gamma (the left, executive prong) to wake up an under-aroused brain, alpha (the right, creative prong) to calm an over-aroused one, and theta (the central, fluid-intelligence prong) to hold the balanced state in the middle. All of this is educational rather than medical advice.

### How each clue is actually measured

The first clue, the **1/f curve**, comes from the same background slope the PAC section described: if you chart how much power sits at each frequency, brain activity always slopes downward — lots of slow power, less and less as you climb to fast frequencies — and the *steepness* of that slope is the number that matters here. The app fits that slope (the aperiodic exponent) and reads it as a stand-in for the tug-of-war between **excitation** (cells urging each other to fire) and **inhibition** (cells quieting each other down): a steep slope means slow rhythms dominate and the brake (inhibition) is winning, which sits on the calm subcritical side, while a flat slope means fast activity is keeping up and the accelerator (excitation) is winning, which sits on the supercritical side. In the app's math the exponent is compared to a balanced value of about 1.5, and how far it lands above or below that point pushes the marker left or right; this idea — that the spectral slope tracks the excitation/inhibition balance — comes from work by Gao, Peterson, and Voytek and is the single most-trusted of the three clues here.

The second clue, **arousal**, is simpler: the app adds up how much power lives in the fast bands (beta and gamma) and compares it to how much lives in alpha, the relaxed "idling" rhythm. A brain humming with fast activity and little alpha is keyed up and aroused (supercritical lean), while a brain full of alpha and little fast activity is relaxed or drowsy (subcritical lean). Concretely it takes the ratio of fast-to-alpha power on a logarithmic scale so that "twice as much" and "half as much" count equally in opposite directions, and that signed value becomes the second push on the marker. The 1/f exponent and this arousal balance are combined — weighted roughly sixty/forty toward the exponent — into one signed "distance from the critical point," where a value near zero means near-critical and large positive or negative values mean super- or subcritical.

The third clue, **long-range temporal correlations**, is the subtlest and is measured with a technique called **detrended fluctuation analysis (DFA)**. The plain idea: take the rising-and-falling strength of the alpha rhythm over time and ask whether its quiet spells and busy spells stay *gently linked across many seconds* — like weather, where a stormy hour makes the next hour more likely to be stormy too — or whether each moment is independent of the last, like coin flips. Systems poised at criticality show a very particular amount of this long-memory linkage (a DFA value around 0.75), neither perfectly random nor rigidly locked, so the closer the measured value sits to that sweet spot the more it nudges the estimate toward near-critical. The catch is that you need many minutes of clean recording to measure this reliably; on the short windows the app works with, the number is only a hint, so the app deliberately gives it the smallest weight and tells you in the notes when it's running on too little data to be sure. Taken together, these three clues are combined into a soft vote across the three states, and the app reports not just the winning state but a **confidence** based on how clearly it won — because, as with PAC, an honest "here's how sure I am" beats a single confident-sounding label, especially for indirect scalp markers that are most meaningful against your own personal baseline.

---

## What you see on the screen

The page is laid out in panels.

A **theta–gamma frequency ratio** gives a quick number comparing the fast rhythm's speed to the slow rhythm's speed with a playful "cognition score," but it is only a *speed comparison* and is clearly labeled as **not** coupling so you never mistake it for PAC.

The **phase–amplitude coupling (PAC)** panel is the serious one: it gives an overall verdict — for example *"significant theta–gamma PAC on 3 channels"* or *"not interpretable"* — and a table with one row per spot showing the slow speed (θ Hz), the fast speed (γ Hz), the coupling strength (MI), how far it beat chance (z and percentile), the harmonic risk, and a plain status word. Those status words are worth knowing:

- **PAC** — real, significant coupling there.
- **n.s.** — "not significant," coupling that didn't clearly beat chance.
- **θ unreliable** — no trustworthy theta rhythm, so nothing was calculated.
- **excluded** — that spot's data was too messy (such as a dropout) to use.

Right next to it sits the **criticality (Trident-state)** panel with a sliding marker on the subcritical-to-supercritical axis, the chosen state, a confidence level, and the markers behind it — a separate readout, by design.

The rest of the page rounds it out — a **real-time chart** of the last minute, a **session average** you can record and save as an image, **bands** showing each rhythm's live strength with the strongest highlighted, a **calibration** tool that injects a known fake signal to confirm the app reacts correctly (like playing a known note to test a microphone), and a **status dot** for the headset connection.

The frequency ratio is deliberately kept apart from PAC to avoid a common mistake — a peak-frequency ratio is not a coupling measure, and treating it as one overstates the evidence — so the PAC panel instead lays out the full picture (effect size, statistical reliability, how many channels agree, data quality, and the harmonic confound) and lets you weigh it the way an analyst would rather than trusting one opaque index.

---

## Trying it without a headset

You don't need the real headset to explore the app: a **synthetic** mode generates fake brain-like signals so the whole thing runs on any computer when you add `--synthetic` at launch, with the caveat that those numbers are practice data, not a real person's brain.

It's also how the code is tested safely, since it provides a known, repeatable input to confirm the app behaves the same way every time before it faces real, unpredictable data. That synthetic board is BrainFlow's built-in generator, ideal for end-to-end testing of capture, analysis, and display without hardware — but because its channels are essentially noisy sinusoids, they won't reliably show genuine coupling, which is exactly why the deterministic ground-truth suite in `simulate_pac_validation.py`, not the live synthetic feed, is the real test of whether the math is correct.

---

## The honest limits

This is an educational tool, not a medical device: it can't diagnose anything, read your thoughts, or tell what you're thinking about — it only shows the general electrical rhythms of your brain and whether some of them appear to be working together.

Even the coupling it does measure is a *correlation* rather than a mind-reader; strong theta–gamma coupling is *associated* with memory and attention in research, but seeing it on screen reveals only that the rhythms seem to be coordinating, never *what* you're remembering or thinking. The criticality estimate carries the same caution — its scalp markers are indirect proxies that are most meaningful against your own personal baseline, not as absolute labels.

The hardware adds real limits too — consumer dry-electrode EEG has sparse spatial coverage, is sensitive to motion and muscle artifacts, and offers no source localization — so these scalp-level, correlational results would be over-read if treated as cognitive readouts.

> The genuine value here is pedagogical and methodological: the app demonstrates a rigorous, skeptical way to handle a measurement that is famously easy to get wrong.

---

## The whole thing in one picture

```
  Your brain
      |   (makes tiny electricity)
      v
  Unicorn headset  ──(Bluetooth)──>  Computer
   (8 listening spots,                  |
    250 checks/second)                  |  server.py does the math:
                                        |   - sort the brain rhythms (bands)
                                        |   - find real theta & gamma rhythms
                                        |   - measure theta–gamma coupling (PAC)
                                        |   - estimate criticality (separately)
                                        |   - run the honesty checks
                                        v
                                  Your web browser
                                  (charts, numbers, colors,
                                   updating every second)
```

In short, the app turns the invisible electrical buzz of your brain into a live, honest, easy-to-read picture, paying special attention to whether your slow and fast rhythms are teaming up the way thinking and memory seem to require.

---

*Thanks for reading. Eden is an Exergis product by Taurean Lee.*
