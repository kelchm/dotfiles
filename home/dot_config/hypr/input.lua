-- Personal overrides, loaded after Omarchy's packaged defaults.
hl.config({
  input = {
    -- Caps Lock acts as Ctrl; swap Left Alt and Left Super.
    kb_options = "ctrl:nocaps,shift:both_capslock_cancel,altwin:swap_lalt_lwin",
    touchpad = {
      natural_scroll = true,
    },
  },
})

-- Three-finger horizontal swipe changes workspaces.
-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Gestures/
hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
hl.config({
  gestures = {
    workspace_swipe_distance = 1100, -- touchpad travel for a full swipe (default 300); high so fast, accelerated swipes still leave room to glide
    workspace_swipe_min_speed_to_force = 15, -- flick speed that switches regardless of distance (default 30)
    workspace_swipe_cancel_ratio = 0.15, -- fraction of a swipe needed to commit (default 0.5)
    workspace_swipe_create_new = false, -- stop at the last workspace instead of creating empty ones
  },
})
