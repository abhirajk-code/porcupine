# Porcupine — Behavior Timeline & Scenarios

All examples use the default configuration (refresh = 5 s, all monitors enabled).

---

## Default values

| Monitor | `every` | Read interval | Display cadence               |
|---------|---------|---------------|-------------------------------|
| temp    | 1       | every 5 s     | every rotation                |
| gpio    | 2       | every 10 s    | every 2nd rotation (even)     |
| cpu     | 5       | every 25 s    | every 5th rotation (0,5,10,…) |
| power   | 5       | every 25 s    | every 5th rotation (0,5,10,…) |
| boot    | 10      | every 50 s    | every 10th rotation           |
| net     | 10      | every 50 s    | every 10th rotation           |

LCD screen order (when all appear): Boot → Power → CPU → Temp → Net → GPIO-1 → GPIO-2

---

## How the two counters work

| Counter   | Increments                        | Gate condition             | Controls                  |
|-----------|-----------------------------------|----------------------------|---------------------------|
| `r_cycle` | every 5 s (refresh tick)          | `r_cycle % every == 0`     | when a monitor is re-read |
| `d_cycle` | each time LCD wraps to screen 0   | `d_cycle % every == 0`     | which monitors appear in this rotation |

Both counters start at 0. At 0, every enabled monitor is included (0 % N == 0 for any N > 0).

---

## Display rotation schedule

The pattern repeats with period LCM(1, 2, 5, 10) = **10 d_cycles**.

| d_cycle | Screens shown              | Count | Duration |
|---------|----------------------------|-------|----------|
| 0       | Boot, Power, CPU, Temp, Net, GPIO-1, GPIO-2 | 7 | 35 s |
| 1       | Temp                       | 1     | 5 s  |
| 2       | Temp, GPIO-1, GPIO-2       | 3     | 15 s |
| 3       | Temp                       | 1     | 5 s  |
| 4       | Temp, GPIO-1, GPIO-2       | 3     | 15 s |
| 5       | Power, CPU, Temp           | 3     | 15 s |
| 6       | Temp, GPIO-1, GPIO-2       | 3     | 15 s |
| 7       | Temp                       | 1     | 5 s  |
| 8       | Temp, GPIO-1, GPIO-2       | 3     | 15 s |
| 9       | Temp                       | 1     | 5 s  |
| 10 (=0) | Boot, Power, CPU, Temp, Net, GPIO-1, GPIO-2 | 7 | 35 s |

One full epoch (d_cycle 0–9): **130 s ≈ 2 min 10 s** before the 7-screen pass repeats.

---

## Scenario 1 — Normal steady state (no alerts)

The table groups events by display rotation (d_cycle). Within each rotation, reads that
occur during that window are listed on the right.

```
d_cycle | Screens in rotation            | Reads during rotation          | Audio
--------+--------------------------------+--------------------------------+-------
d=0     | Boot, Power, CPU, Temp,        | r= 0: ALL                      | ♪ startup beep
(35 s)  |   Net, GPIO-1, GPIO-2          | r= 1: temp                     |
        |                                | r= 2: temp, gpio               |
        |                                | r= 3: temp                     |
        |                                | r= 4: temp, gpio               |
        |                                | r= 5: temp, cpu, power         |
        |                                | r= 6: temp, gpio               |
--------+--------------------------------+--------------------------------+-------
d=1     | Temp                           | r= 7: temp                     |
(5 s)   |                                |                                |
--------+--------------------------------+--------------------------------+-------
d=2     | Temp, GPIO-1, GPIO-2           | r= 8: temp, gpio               |
(15 s)  |                                | r= 9: temp                     |
        |                                | r=10: ALL                      |
--------+--------------------------------+--------------------------------+-------
d=3     | Temp                           | r=11: temp                     |
(5 s)   |                                |                                |
--------+--------------------------------+--------------------------------+-------
d=4     | Temp, GPIO-1, GPIO-2           | r=12: temp, gpio               |
(15 s)  |                                | r=13: temp                     |
        |                                | r=14: temp, gpio               |
--------+--------------------------------+--------------------------------+-------
d=5     | Power, CPU, Temp               | r=15: temp, cpu, power         |
(15 s)  |                                | r=16: temp, gpio               |
        |                                | r=17: temp                     |
--------+--------------------------------+--------------------------------+-------
d=6     | Temp, GPIO-1, GPIO-2           | r=18: temp, gpio               |
(15 s)  |                                | r=19: temp                     |
        |                                | r=20: ALL                      |
--------+--------------------------------+--------------------------------+-------
d=7     | Temp                           | r=21: temp                     |
(5 s)   |                                |                                |
--------+--------------------------------+--------------------------------+-------
d=8     | Temp, GPIO-1, GPIO-2           | r=22: temp, gpio               |
(15 s)  |                                | r=23: temp                     |
        |                                | r=24: temp, gpio               |
--------+--------------------------------+--------------------------------+-------
d=9     | Temp                           | r=25: temp                     |
(5 s)   |                                |                                |
--------+--------------------------------+--------------------------------+-------
d=10    | Boot, Power, CPU, Temp,        | r=26: temp, gpio               |  (repeats)
(35 s)  |   Net, GPIO-1, GPIO-2          | r=27: temp                     |
        |                                | …                              |
```

`ALL` reads occur every 50 s (r = 0, 10, 20, …) — the LCM of all `every` values.

---

## Scenario 2 — Temperature threshold breach

**Threshold: `temp_warn = 80.0 °C` (default)**

Temp breaches at r=11 (during d=3). Since `temp_every=1`, the Temp screen appears in
**every** rotation, so the WARN indicator and beep appear immediately in that same rotation.

```
d_cycle | Screens in rotation            | Reads / events                  | Audio
--------+--------------------------------+---------------------------------+-------------------
d=2     | Temp, GPIO-1, GPIO-2           | r=10: ALL (72 °C)               |
--------+--------------------------------+---------------------------------+-------------------
d=3     | Temp WARN ! ◀                  | r=11: temp → 83 °C ⚠           | ♪♪♪  3 beeps
(5 s)   |                                |   alert detected, ! on all      |   (Temp on screen)
--------+--------------------------------+---------------------------------+-------------------
d=4     | Temp WARN !, GPIO-1 !, GPIO-2 !| r=12: temp, gpio  (still 83 °C) | —
--------+--------------------------------+---------------------------------+-------------------
d=5     | Power !, CPU !, Temp WARN !    | r=15: temp, cpu, power          | ♪♪♪  3 beeps
(15 s)  |                                |   (still 83 °C)                 |   (Temp on screen)
--------+--------------------------------+---------------------------------+-------------------
d=6     | Temp WARN !, GPIO-1 !, GPIO-2 !| r=18: temp, gpio                | ♪♪♪  3 beeps
--------+--------------------------------+---------------------------------+-------------------
d=7     | Temp WARN !                    | r=21: temp  (still 83 °C)       | ♪♪♪  3 beeps
--------+--------------------------------+---------------------------------+-------------------
d=8     | Temp WARN !, GPIO-1 !, GPIO-2 !| r=22–24                         | ♪♪♪  3 beeps
--------+--------------------------------+---------------------------------+-------------------
d=9     | Temp WARN !                    | r=25: temp → 75 °C ✓            | —  (cleared)
        |                                |   alert clears, ! removed       |
--------+--------------------------------+---------------------------------+-------------------
d=10    | Boot, Power, CPU, Temp,        | r=26: temp, gpio                |
        |   Net, GPIO-1, GPIO-2          |                                 |
```

**Key observations:**
- Breach and beep coincide in the **same rotation** (d=3) because Temp is always due (every=1).
- `!` appears at column 15 of every screen's first line while any alert is active.
- Beep fires once per rotation, each time the Temp screen is reached.
- `effective_every["temp"]` stays at 1 (already read every cycle; no escalation needed).

---

## Scenario 3 — CPU usage breach + read escalation

**Threshold: `cpu_warn = 90.0 %` (default)**

CPU is normally read every 25 s (`cpu_every = 5`). When breached,
`effective_every["cpu"]` drops to **1** so CPU data refreshes every 5 s.
CPU screen display cadence remains every 5th rotation (base `cpu_every = 5` is used for display).

At r=15 (during d=5) CPU reads **95 %**.

```
d_cycle | Screens in rotation            | Reads / events                  | Audio
--------+--------------------------------+---------------------------------+-------------------
d=4     | Temp, GPIO-1, GPIO-2           | r=12–14: temp, gpio             |
--------+--------------------------------+---------------------------------+-------------------
d=5     | Power !, CPU WARN ! ◀          | r=15: temp, cpu ⚠ → 95%        | ♪♪  2 beeps
(15 s)  |   Temp !                       |   effective_every[cpu]: 5→1     |   (CPU on screen)
        |                                | r=16: temp, gpio, cpu(now!)     |
        |                                | r=17: temp, cpu (still 95%)     |
--------+--------------------------------+---------------------------------+-------------------
d=6     | Temp !, GPIO-1 !, GPIO-2 !     | r=18: temp, gpio, cpu           |
--------+--------------------------------+---------------------------------+-------------------
d=7     | Temp !                         | r=21: temp, cpu                 |
--------+--------------------------------+---------------------------------+-------------------
d=8     | Temp !, GPIO-1 !, GPIO-2 !     | r=22: temp, gpio, cpu           |
--------+--------------------------------+---------------------------------+-------------------
d=9     | Temp !                         | r=25: temp, cpu                 |
--------+--------------------------------+---------------------------------+-------------------
d=10    | Boot !, Power !, CPU WARN ! ◀  | r=26: temp, gpio, cpu           | ♪♪  2 beeps
(35 s)  |   Temp !, Net !, GPIO-1 !,     | r=27: temp, cpu → 78% ✓        |   (CPU on screen)
        |   GPIO-2 !                     |   effective_every[cpu]: 1→5     |
        |                                | r=30: temp, gpio, cpu (78%)     |
--------+--------------------------------+---------------------------------+-------------------
d=11    | Temp  (no alert, ! gone)       | r=31: temp                      |
```

**Key observations:**
- CPU is read every 5 s while breached (`effective_every["cpu"] = 1`), but the CPU screen
  still only appears every 5th rotation — display cadence uses the base `cpu_every`, not the
  escalated value.
- Beep fires when the CPU screen is shown (d=5, d=10, …), not on every r_cycle read.
- When CPU clears mid-rotation (r=27 during d=10), `effective_every["cpu"]` restores to 5.
  Next CPU read is at r=30.

---

## Scenario 4 — Dual alert (temp + battery low)

**Thresholds: `temp_warn = 80 °C`, `bat_warn = 40 %`**

Both thresholds breached simultaneously at r=15 (during d=5).

```
d_cycle | Screens in rotation            | Reads / events                  | Audio
--------+--------------------------------+---------------------------------+-------------------
d=4     | Temp, GPIO-1, GPIO-2           | r=12–14: temp, gpio             |
--------+--------------------------------+---------------------------------+-------------------
d=5     | Power WARN ! ◀                 | r=15: temp ⚠ 83°C,             | ♪  1 long (bat)
(15 s)  |   CPU !, Temp WARN ! ◀         |       power ⚠ bat 25%          | ♪♪♪  3 beeps (temp)
        |                                |   effective_every[power]: 5→1  |
--------+--------------------------------+---------------------------------+-------------------
d=6     | Temp WARN !, GPIO-1 !, GPIO-2 !| r=18: temp, gpio, power         | ♪♪♪  3 beeps (temp)
--------+--------------------------------+---------------------------------+-------------------
d=7     | Temp WARN !                    | r=21: temp, power               | ♪♪♪  3 beeps (temp)
--------+--------------------------------+---------------------------------+-------------------
d=8     | Temp WARN !, GPIO-1 !, GPIO-2 !| r=22–24: …, power               | ♪♪♪  3 beeps (temp)
--------+--------------------------------+---------------------------------+-------------------
d=9     | Temp WARN !                    | r=25: temp, power               | ♪♪♪  3 beeps (temp)
--------+--------------------------------+---------------------------------+-------------------
d=10    | Boot !, Power WARN ! ◀         | r=26–29: …, power               | ♪  1 long (bat)
(35 s)  |   CPU !, Temp WARN ! ◀         |                                 | ♪♪♪  3 beeps (temp)
        |   Net !, GPIO-1 !, GPIO-2 !    |                                 |
```

**Key observations:**
- Each monitor plays its own beep pattern only when **its screen** is shown.
- Battery (Power screen) and Temperature (Temp screen) beeps never overlap within a rotation.
- Between d=6 and d=9, only the Temp screen appears; battery beep is silent until d=10 when
  Power screen returns.
- `effective_every["power"]` drops 5→1 so battery % is re-read every 5 s.

---

## Alert beep patterns

| Flag    | Condition                                           | Pattern               | Screen where beep fires |
|---------|-----------------------------------------------------|-----------------------|-------------------------|
| `temp`  | cpu_temp_c ≥ temp_warn                              | 3 × 200 ms, 100 ms gap| Temp                    |
| `cpu`   | cpu_avg_pct ≥ cpu_warn **or** mem_pct ≥ mem_warn    | 2 × 200 ms, 100 ms gap| CPU                     |
| `power` | battery_pct < bat_warn AND on battery               | 1 × 600 ms            | Power                   |

Beep also fires immediately (regardless of which screen is showing) when a **new** breach
is first detected, so the user gets instant feedback.

---

## Read escalation summary

When a threshold is breached `effective_every[flag]` drops to **1** so that monitor
is sampled every refresh cycle (5 s). Display cadence is unaffected — it always uses
the base `every` value from config.

| Monitor | Normal read    | Escalated read | Triggered by          |
|---------|----------------|----------------|-----------------------|
| temp    | 5 s (every=1)  | already 5 s    | `temp` flag breach    |
| cpu     | 25 s (every=5) | 5 s            | `cpu` flag breach     |
| power   | 25 s (every=5) | 5 s            | `power` flag breach   |
| boot    | 50 s (every=10)| —              | (no alert)            |
| net     | 50 s (every=10)| —              | (no alert)            |
| gpio    | 10 s (every=2) | —              | (no alert)            |
