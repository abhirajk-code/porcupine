# Porcupine — Behavior Timeline & Scenarios

All examples use the default configuration (refresh = 5 s, all monitors enabled).

---

## Default values

| Monitor | `every` | Read interval | Screens on LCD |
|---------|---------|---------------|----------------|
| temp    | 1       | every 5 s     | 1 (Temp)       |
| gpio    | 2       | every 10 s    | 2 (GPIO-1, GPIO-2) |
| cpu     | 5       | every 25 s    | 1 (CPU)        |
| power   | 5       | every 25 s    | 1 (Power)      |
| boot    | 10      | every 50 s    | 1 (Boot)       |
| net     | 10      | every 50 s    | 1 (Net)        |

**7 screens total × 5 s each = 35 s per full display pass.**

LCD screen order: Boot → Power → CPU → Temp → Net → GPIO-1 → GPIO-2

---

## How the two counters work

| Counter   | Increments          | Controls                                      |
|-----------|---------------------|-----------------------------------------------|
| `r_cycle` | every 5 s (refresh) | which monitors are re-read this tick          |
| `d_cycle` | every 35 s (1 pass) | conceptual pass counter; audio fires per-screen|

A monitor is read when `r_cycle % effective_every[monitor] == 0`.
At startup (`r_cycle = 0`) all enabled monitors are read regardless.

---

## Scenario 1 — Normal steady state (no alerts)

```
Time  | Read (r_cycle)              | LCD screen  | Audio
------+-----------------------------+-------------+-------
0:00  | r= 0: ALL                   | — (blank)   | ♪ startup beep
0:05  | r= 1: temp                  | Power       | —
0:10  | r= 2: temp, gpio            | CPU         | —
0:15  | r= 3: temp                  | Temp        | —
0:20  | r= 4: temp, gpio            | Net         | —
0:25  | r= 5: temp, cpu, power      | GPIO-1      | —
0:30  | r= 6: temp, gpio            | GPIO-2      | —
0:35  | r= 7: temp                  | Boot ◀d→1   | — (no alerts)
0:40  | r= 8: temp, gpio            | Power       | —
0:45  | r= 9: temp                  | CPU         | —
0:50  | r=10: ALL                   | Temp        | —
0:55  | r=11: temp                  | Net         | —
1:00  | r=12: temp, gpio            | GPIO-1      | —
1:05  | r=13: temp                  | GPIO-2      | —
1:10  | r=14: temp, gpio            | Boot ◀d→2   | — (no alerts)
```

"ALL" reads occur every 50 s (r = 0, 10, 20, …) — the LCM of all `every` values.
`◀d→N` marks when the display completes a full pass (Boot screen shown after GPIO-2).

---

## Scenario 2 — Temperature threshold breach

**Threshold: `temp_warn = 80.0 °C` (default)**

At `r=11` (t = 0:55) the CPU temperature rises to **83 °C**.

```
Time  | Read (r_cycle)              | LCD screen        | Audio
------+-----------------------------+-------------------+-------------------
0:50  | r=10: ALL                   | Temp  (72 °C)     | —
0:55  | r=11: temp → 83 °C ⚠       | Net               | —
1:00  | r=12: temp, gpio            | GPIO-1            | —
1:05  | r=13: temp                  | GPIO-2            | —
1:10  | r=14: temp, gpio            | Boot ◀d→2         | —
1:15  | r=15: temp, cpu, power      | Power             | —
1:20  | r=16: temp, gpio            | CPU               | —
1:25  | r=17: temp  (still 83 °C)   | Temp WARN ◀       | ♪♪♪  3 beeps
1:30  | r=18: temp, gpio            | Net               | —
1:35  | r=19: temp                  | GPIO-1            | —
1:40  | r=20: ALL                   | GPIO-2            | —
1:45  | r=21: temp  (still 83 °C)   | Boot ◀d→3         | —
1:50  | r=22: temp, gpio            | Power             | —
1:55  | r=23: temp                  | CPU               | —
2:00  | r=24: temp, gpio            | Temp WARN ◀       | ♪♪♪  3 beeps
2:05  | r=25: temp, cpu, power      | Net               | —
2:10  | r=26: temp, gpio            | GPIO-1            | —
2:15  | r=27: temp → 75 °C ✓        | GPIO-2            | —
2:20  | r=28: temp, gpio            | Boot ◀d→4         | —
2:25  | r=29: temp                  | Power             | —
2:30  | r=30: temp, gpio, cpu       | CPU               | —
2:35  | r=31: temp                  | Temp  (75 °C) ◀   | —  (cleared)
```

**Key observations:**
- Breach detected at 0:55 while Net is on screen; WARN first visible at 1:25 (Temp screen).
- **Beep fires exactly when the Temp screen is shown** — WARN and audio are simultaneous.
- Beep repeats every full pass (~35 s) as long as the breach persists.
- `effective_every["temp"]` stays at 1 (temp was already read every cycle, no escalation needed).

---

## Scenario 3 — CPU usage breach + read escalation

**Threshold: `cpu_warn = 90.0 %` (default)**

CPU is normally read every 25 s (`cpu_every = 5`).
When the threshold is breached `effective_every["cpu"]` drops to **1** (every 5 s).

At `r=15` (t = 1:15) CPU reads **95 %**.

```
Time  | Read (r_cycle)              | LCD screen        | Audio
------+-----------------------------+-------------------+-------------------
1:10  | r=14: temp, gpio            | Boot ◀d→2         | —
1:15  | r=15: temp, cpu ⚠ → 95%    | Power             | —
      |   effective_every[cpu]: 5→1 |                   |
1:20  | r=16: temp, gpio, cpu(now!) | CPU WARN ◀        | ♪♪  2 beeps
1:25  | r=17: temp, cpu             | Temp              | —
1:30  | r=18: temp, gpio, cpu       | Net               | —
1:35  | r=19: temp, cpu             | GPIO-1            | —
1:40  | r=20: ALL + cpu every cycle | GPIO-2            | —
1:45  | r=21: temp, cpu             | Boot ◀d→3         | —
1:50  | r=22: temp, gpio, cpu       | Power             | —
1:55  | r=23: temp, cpu             | CPU WARN ◀        | ♪♪  2 beeps
2:00  | r=24: temp, gpio, cpu       | Temp              | —
...
2:10  | r=26: temp, gpio, cpu       | CPU WARN ◀        | ♪♪  2 beeps
2:15  | r=27: temp, cpu → 78% ✓     | GPIO-2            | —
      |   effective_every[cpu]: 1→5 |                   |
2:20  | r=28: temp, gpio            | Boot ◀d→4         | —
2:25  | r=29: temp                  | Power             | —
2:30  | r=30: temp, gpio, cpu       | CPU  (78%) ◀      | —  (cleared)
```

**Key observations:**
- CPU was read at r=15 because `15 % 5 == 0` (normal schedule).
- From r=16 onward CPU is read every cycle (`effective_every["cpu"] = 1`) — values on screen update every 5 s instead of every 25 s.
- When CPU clears at r=27, `effective_every["cpu"]` restores to 5; next CPU read is at r=30.

---

## Scenario 4 — Dual alert (temp + battery low)

**Thresholds: `temp_warn = 80 °C`, `bat_warn = 40 %`**

Both breaches active simultaneously.

```
Time  | Read (r_cycle)              | LCD screen        | Audio
------+-----------------------------+-------------------+-------------------
1:10  | r=14: temp, gpio            | Boot ◀d→2         | —
1:15  | r=15: temp ⚠ 83°C, cpu,    | Power WARN ◀      | ♪  1 long beep (bat)
      |       power ⚠ bat 25%       |                   |
1:20  | r=16: temp, gpio            | CPU               | —
1:25  | r=17: temp                  | Temp WARN ◀       | ♪♪♪  3 beeps (temp)
1:30  | r=18: temp, gpio            | Net               | —
1:35  | r=19: temp                  | GPIO-1            | —
1:40  | r=20: ALL                   | GPIO-2            | —
1:45  | r=21: temp                  | Boot ◀d→3         | —
1:50  | r=22: temp, gpio, power     | Power WARN ◀      | ♪  1 long beep (bat)
1:55  | r=23: temp                  | CPU               | —
2:00  | r=24: temp, gpio, power     | Temp WARN ◀       | ♪♪♪  3 beeps (temp)
```

**Key observations:**
- Each monitor plays its own pattern only when its screen is shown — alerts never overlap.
- Battery: 1 × 600 ms beep (Power screen). Temperature: 3 × 200 ms beeps (Temp screen).
- `effective_every["power"]` drops 5 → 1 so battery % is re-read every 5 s.

---

## Alert beep patterns

| Alert key | Condition                              | Pattern               | Monitor screen |
|-----------|----------------------------------------|-----------------------|----------------|
| `temp`    | cpu_temp_c ≥ temp_warn                 | 3 × 200 ms, 100 ms gap| Temp           |
| `cpu`     | cpu_avg_pct ≥ cpu_warn                 | 2 × 200 ms, 100 ms gap| CPU            |
| `mem`     | mem_pct ≥ mem_warn                     | 2 × 200 ms, 100 ms gap| CPU            |
| `bat`     | battery_pct < bat_warn AND on battery  | 1 × 600 ms            | Power          |

---

## Read escalation summary

When a threshold is breached `effective_every[flag]` drops to **1** so that monitor
is sampled every refresh cycle (5 s) instead of its configured cadence.
When the value clears, the cadence restores automatically.

| Monitor | Normal read cadence | Escalated cadence | Triggered by    |
|---------|---------------------|-------------------|-----------------|
| temp    | 5 s (every=1)       | already 5 s       | temp alert      |
| cpu     | 25 s (every=5)      | 5 s               | cpu or mem alert|
| power   | 25 s (every=5)      | 5 s               | bat alert       |
| boot    | 50 s (every=10)     | —                 | (no alert)      |
| net     | 50 s (every=10)     | —                 | (no alert)      |
| gpio    | 10 s (every=2)      | —                 | (no alert)      |
