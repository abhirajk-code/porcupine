# Porcupine — How It Works

A high-level pseudo-code walkthrough of the system from boot to steady-state.

---

## Bird's-eye view

```
┌─────────────────────────────────────────────────────────────────┐
│                         daemon.run()                            │
│  Orchestrator loop  ──► reads monitors ──► checks thresholds   │
│         │                                        │              │
│         ▼                                        ▼              │
│     Notifier                              Notifier.update()     │
│   (owns display)                       (update LCD + beep)      │
└────────────┬────────────────────────────────────┬───────────────┘
             │                                    │
      ┌──────▼──────┐                    ┌────────▼────────┐
      │  LCD thread │                    │  Buzzer worker  │
      │  (cycles    │                    │  (async queue)  │
      │   screens)  │                    └─────────────────┘
      └──────┬──────┘
             │ on_screen_advance callback
      ┌──────▼──────┐
      │  Button FSM │  ◄─── hardware GPIO events
      └─────────────┘
```

---

## 1. Startup

```
parse_args()
    load config file  (/etc/porcupine/porcupine.conf)
    merge: CLI flags > config file > hardcoded defaults
    result: refresh=5s, temp_warn=80°C, boot_every=10, cpu_every=5, …

_make_monitors(args)
    for each feature (boot, power, cpu, temp, net, gpio):
        if {feature}_every == 0:  skip (disabled)
        else:  create Monitor object, set monitor.every = N
    return [BootMonitor, PowerMonitor, CpuMemMonitor, TempMonitor, …]

create hardware:
    lcd    = LCD(i2c_addr)        # wraps HD44780 over I2C
    button = Button(pin)          # GPIO input, active-low
    buzzer = Buzzer(pin)          # PWM output, starts internal worker thread
    load custom CGRAM chars into LCD  # GPIO pin direction/level symbols

wire callbacks:
    button.on_press_start → buzzer.beep_async(1 short beep)  # instant feedback
    button.on_held        → buzzer.beep_async(1 long beep)   # "held long enough" cue
    ButtonController(button, lcd)     # wires button → FSM
    lcd.on_screen_advance → notifier.on_screen_advance       # LCD thread → notifier

initial pass:
    last_data    = _read_all(monitors, r_cycle=0)  # reads all monitors once
    breached     = {m.flag for m in monitors if m.has_breach(last_data)}
    effective_every = copy of monitor.every values (escalated when breaching)
    notifier.start(monitors, last_data, breached)  # builds screens, starts LCD cycling

button.start()          # begin polling GPIO
buzzer.beep_async(1)    # startup chime
```

---

## 2. Main loop

```
r_cycle = 0   # read cycle counter (increments every refresh seconds)
d_cycle = 0   # display cycle counter (increments when LCD completes a full rotation)

loop forever:
    sleep(refresh)                   # 5 seconds by default
    r_cycle += 1

    if notifier.consume_wrap():      # did the LCD finish a full rotation?
        d_cycle += 1

    data = _read_all(monitors, r_cycle, effective_every)
        for each monitor:
            if r_cycle % effective_every[monitor.flag] != 0: skip
            try: merged[...] = monitor.read()   # call the hardware/OS API
            except: log warning, continue

    if no new data AND LCD didn't wrap:
        continue                     # nothing changed — skip screen rebuild

    last_data = merge(last_data, data)

    breached = {m.flag for m in monitors if m.has_breach(last_data)}
        # e.g. cpu_avg_pct >= 90 → "cpu" in breached

    _apply_escalation(monitors, breached, effective_every)
        # alerting monitor: effective_every[flag] = 1   (read every cycle)
        # clear monitor:    effective_every[flag] = m.every (restore normal rate)

    notifier.update(monitors, last_data, breached, d_cycle)
        # see section 4 below
```

---

## 3. Each Monitor — uniform interface

Every monitor (boot, power, cpu/mem, temp, net, gpio) implements the same four methods:

```
monitor.read() → dict
    # calls the OS or hardware:
    #   boot   → reads /proc/uptime, counts reboots from a state file
    #   power  → reads INA219 over I2C (voltage, current, battery %)
    #   cpu    → psutil.cpu_percent(), virtual_memory()
    #   temp   → reads /sys/class/thermal/thermal_zone0/temp
    #   net    → reads /proc/net/dev byte counters, derives bps
    #   gpio   → reads /sys/class/gpio for each of 40 header pins

monitor.format_screens(data) → [(line1, line2), …]
    # converts raw data into one or two 16-char LCD screen tuples
    #   cpu:  (" CPU   Mem", "  23%   45%")
    #   gpio: two pages, 10 pin chars per row

monitor.has_breach(data) → bool
    # true when any threshold is exceeded
    #   temp:  cpu_temp_c >= temp_warn
    #   cpu:   cpu_avg_pct >= cpu_warn  OR  mem_pct >= mem_warn
    #   power: power_source == "Battery" AND battery_pct < bat_warn

monitor.beep_pattern() → {count, duration_ms, gap_ms}  or  None
    # non-alertable monitors (boot, net, gpio) return None
    #   temp:  3 beeps  (most urgent)
    #   cpu:   2 beeps
    #   power: 1 long beep
```

---

## 4. Notifier — display and beep decisions

```
notifier.update(monitors, data, breached, d_cycle):

    screens, tags = _build_screens_tagged(monitors, data, d_cycle)
        # tags is a parallel list: tags[i] = monitor.flag for screens[i]
        # d_cycle filtering: monitor only included if d_cycle % monitor.every == 0
        # gpio monitor produces 2 screens (2 pages of 40 pins)

    if only_alert mode AND breached:
        keep only the screens whose tag is in breached
        turn LCD on if it was off (via ButtonController.set_lcd_on)
    elif only_alert mode AND not breached:
        turn LCD off

    overlay alert indicator:
        if any breach: append "!" to column 15 of every screen's first line

    lcd.update_screens(final_screens)   # replaces screen list in-place

    beep for newly-crossed thresholds:
        for flag in (breached - previously_breached):
            pattern = monitors[flag].beep_pattern()
            buzzer.beep_async(**pattern)   # non-blocking, queued

    save new state: self._breached, self._tags, self._beep_patterns


notifier.on_screen_advance(index):   ← called by LCD thread on every screen change
    if index == 0:  signal "LCD wrapped" (d_cycle will increment next loop pass)
    if tags[index] is in breached:
        buzzer.beep_async(**beep_patterns[flag])   # beep as the breached screen appears
```

---

## 5. LCD thread — independent cycling

```
# Runs for the entire lifetime of the daemon in a background daemon thread.

_cycle_loop(refresh_s):
    while not stop_event:
        sleep(refresh_s)
        with lock:
            if in_menu: continue          # static menu screen — don't advance
            index = (index + 1) % len(screens)
            current = screens[index]

        if display_enabled:               # backlight on?
            render current to hardware    # write line1, line2 to LCD
        # always fire callback, even when display is off:
        if screen_cb:
            screen_cb(index)              # → notifier.on_screen_advance
```

`pause()` / `resume()` only flip `display_enabled` — the thread and counter keep running so `d_cycle` increments and beeps fire even when the backlight is off.

---

## 6. Button FSM — press sequences to actions

```
States: idle → after_first → after_second_start → counting

Short press (LCD on, state=idle):
    state = "after_first"
    start 5-second window timer

Window expires (no follow-up):
    lcd.pause()   # backlight off, monitoring continues
    state = "idle"

Short press (LCD off, state=idle):
    lcd.resume()
    state = "idle"

Second press-down detected (state=after_first):
    cancel window timer
    state = "after_second_start"

Short + short (state=after_second_start):
    begin 20-second reboot countdown

Short + long  (state=after_second_start):
    begin 20-second shutdown countdown

Short press during countdown (state=counting):
    set cancel event → countdown thread exits, LCD shows "Cancelled"

Long press while idle:
    toggle only_alert mode (writes config, restarts service)
```

All LCD state changes (on/off) go through `ButtonController.set_lcd_on()` so the FSM's internal `_lcd_on` flag stays in sync with external callers (e.g. only_alert logic).

---

## 7. Buzzer — async beep queue

```
# Worker thread started in Buzzer.__init__, runs for daemon lifetime.

_beep_worker():
    loop:
        item = queue.get()     # blocks until work arrives
        if item is None: return  # cleanup signal
        beep(**item)           # blocks for the duration of the beep sequence

beep_async(count, duration_ms, gap_ms):
    queue.put({"count": count, ...})   # fire-and-forget from any thread

beep(count, duration_ms, gap_ms):
    for i in count:
        play_tone(duration_ms)         # lgpio PWM or RPi.GPIO PWM or stub
        if i < count-1: sleep(gap_ms)
```

All beeps from notifier, button feedback, and the startup chime go through `beep_async()` so the caller never blocks waiting for audio.

---

## 8. Shutdown

```
KeyboardInterrupt (or SIGTERM → converted to KeyboardInterrupt):
    buzzer.beep(1, 150ms)   # synchronous shutdown chime
    button.stop()           # remove GPIO edge detection
    lcd.stop()              # set stop_event, join cycle thread
    buzzer.cleanup()        # drain queue, join worker, release GPIO
```
