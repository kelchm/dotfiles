---
name: gui-runs
description: Run desktop and GUI apps (tests, screenshots, recordings, memory measurements) without disrupting someone actively using the computer's display. Use before opening any desktop window on a local or remote machine.
---

# Running GUI apps without disrupting the user

Opening a desktop window in front of someone who is using the computer steals focus and interrupts their work. Creating and destroying a virtual display on every run is just as disruptive on macOS: WindowServer reconfigures displays and the Dock jumps each time. Check whether the display is in use first, and reuse one hidden display when it is.

## 1. Check whether someone is actively using the display

Before opening any window, measure how long the machine's input devices have been idle.

On macOS (works locally and over SSH):

```bash
ioreg -r -c IOHIDSystem | awk '/"HIDIdleTime"/ { printf "%.0f\n", $NF / 1e9; exit }'
```

`HIDIdleTime` is reported in nanoseconds; the command above prints idle time in whole seconds. Treat the computer as **actively used** when idle time is under a few minutes (for example, less than 5 minutes / 300 seconds), and **idle** otherwise.

- **If nobody is active:** run the app normally. No virtual display or window-placement workaround is needed.
- **If you cannot tell** whether someone is at the computer, or whether interrupting the screen is acceptable, **ask the user** before opening a window.

## 2. When someone is active

Pick the least disruptive option that fits the task:

- **Reuse one shared hidden display (macOS):** use `hidden-display` (below) so every run targets the same long-lived virtual monitor instead of attaching and detaching one per run.
- **Group GUI runs:** batch tests, screenshots, recordings, or measurements into one run or one short session rather than launching many brief GUI runs back to back.
- **Use another idle connected machine:** if another connected machine can run the task and its display is idle, consider running the GUI work there instead. Check its idle state first and ask if the choice is unclear.
- **Ask when in doubt:** if an app cannot be moved off the active display, needs real-screen interaction, or might still steal focus or sound, check with the user before starting it.

## 3. Shared hidden display on macOS (`hidden-display`)

`hidden-display` keeps one per-user `CGVirtualDisplay` (1600×1000 points at 2x Retina, placed past the far bottom-right corner of all active displays) alive across runs.

```bash
hidden-display ensure   # start once or reuse existing; prints `<display-id> <x> <y>`
hidden-display status   # check whether it is running (exits 0 if running, 1 otherwise)
hidden-display stop     # remove the virtual display and clean up its state file
```

### Handing the display to an app

`hidden-display ensure` prints one line: `<display-id> <x> <y>` (the CoreGraphics display ID and the display's origin in global screen coordinates). Parse those three fields and pass them to the app or harness using whatever flags or environment variables that project expects:

```bash
read -r display_id display_x display_y < <(hidden-display ensure)
```

For example, pass `$display_id` as the target display ID and `"$display_x,$display_y"` (or `$display_x` and `$display_y` separately) as the window origin. If the caller already specified a target display, preserve it rather than overriding it.

Keep the hidden display running across a batch of runs so macOS does not reconfigure displays between them.

### Removing the display when done

When all GUI runs are finished (or when no more hidden runs are planned), remove the virtual display:

```bash
hidden-display stop
```

Do not call `hidden-display stop` after every single test in a series—only once the batch of GUI work is over. On systems without `hidden-display` (Linux, Windows), do not silently fall back to opening windows on an active display; use the platform's headless/offscreen display if available, use an idle connected machine, or ask the user.
