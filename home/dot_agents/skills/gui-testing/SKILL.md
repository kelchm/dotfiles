---
name: gui-testing
description: Run agent-driven desktop GUI tests, visual checks, screenshots, recordings, or measurements without disrupting someone actively using the computer. Use before launching a GUI app yourself to test or verify it—especially in repeated edit-test loops or when multiple agents share a machine. Does not apply when opening an app for the user to look at.
---

# Agent-driven GUI testing

When an agent launches a desktop app to test, screenshot, record, or measure it, windows popping up on an active screen steal focus and break the user's flow. This matters most in **repeated test loops** (edit → build → launch → check → close) or when several agents run GUI checks on the same machine: even naive per-run virtual displays make macOS attach and detach a monitor on every iteration, reconfiguring displays and jumping the Dock each time.

Only apply this when *you* are launching the app to test or inspect it—not when the user asked you to open an app for them to see.

## 1. Check whether someone is actively using the display

Before starting GUI test runs, check how long the machine's input devices have been idle.

On macOS (works locally and over SSH):

```bash
ioreg -r -c IOHIDSystem | awk '/"HIDIdleTime"/ { printf "%.0f\n", $NF / 1e9; exit }'
```

`HIDIdleTime` is in nanoseconds; this prints idle time in whole seconds. Treat the display as **actively used** under a few minutes (for example, less than 5 minutes / 300 seconds) and **idle** otherwise.

- **If nobody is active:** run the GUI app normally. No virtual display or workaround is needed.
- **If you cannot tell** whether the screen is in use, **ask** before starting a GUI test run.

## 2. When someone is active

Keep GUI launches minimal and off the active screen, especially for repeated runs:

- **Keep the tight loop headless when possible:** lean on unit/headless checks between edits and batch GUI launches into fewer passes rather than spawning many short GUI runs back to back.
- **Reuse one shared hidden display (macOS):** use `hidden-display` (below) so every run targets the same long-lived virtual monitor instead of creating and tearing down one per run. Note that `hidden-display` only provides a display ID and `(x, y)` origin—the app or test harness still has to place its windows there (and avoid stealing focus or playing sound).
- **Consider another idle connected machine:** if another connected machine can run the test loop and its display is idle, consider running the GUI tests there instead. Check its idle state first and ask if the choice is unclear.
- **Ask when in doubt:** if the app cannot be directed off the active display, needs real-screen focus, or might still steal focus or audio, check with the user first—especially before running a repeated test loop.

## 3. Shared hidden display on macOS (`hidden-display`)

`hidden-display` keeps one per-user `CGVirtualDisplay` (1600×1000 points at 2x Retina, placed off the far bottom-right corner of the furthest online display) alive across runs.

```bash
hidden-display ensure   # start once or reuse existing; prints `<display-id> <x> <y>`
hidden-display status   # check whether it is running (exits 0 if running, 1 otherwise)
hidden-display stop     # remove the virtual display and clean up its state file
```

### Handing the display to a test run

Verify `hidden-display` is installed first (it is skipped when dotfiles bootstrap is off), and check its exit status before parsing so a failure never silently falls back to opening windows on the active screen:

```bash
command -v hidden-display >/dev/null 2>&1 || { echo "hidden-display not installed" >&2; exit 1; }
display_line=$(hidden-display ensure) || exit 1
read -r display_id display_x display_y <<<"$display_line"
```

If `hidden-display` is missing or fails, stop and ask the user instead of launching on an active display. Over SSH on macOS, `ioreg` works directly, while creating a virtual display or opening GUI windows requires the logged-in user's Aqua session (for example, prefixing with `launchctl asuser "$(id -u)"`).

Pass `$display_id` as the target display ID and `"$display_x,$display_y"` (or `$display_x` and `$display_y` separately) using whatever flags or environment variables the app or test harness expects. Preserve any caller-supplied target display instead of overriding it.

### Leaving it up vs. stopping it

Leave the hidden display running across a batch of test runs so macOS does not reconfigure displays between them. Because the display is shared per user, avoid calling `hidden-display stop` if another agent or GUI test run might still be using it—only stop it when you are done with GUI testing and confident nothing else is relying on it:

```bash
hidden-display stop
```

On systems without `hidden-display` (Linux, Windows), do not silently fall back to opening windows on an active display; use the platform's headless/offscreen display if available, use an idle connected machine, or ask the user.
