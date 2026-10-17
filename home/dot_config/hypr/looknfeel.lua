-- Personal appearance overrides; keep all other Omarchy defaults.
hl.config({
  general = {
    border_size = 1,
  },
})

-- Slide between workspaces (Omarchy disables this) so swipe gestures glide to rest instead of snapping.
hl.curve("swipeGlide", { type = "bezier", points = { { 0.33, 1 }, { 0.68, 1 } } }) -- easeOutCubic: softer start than easeOutQuint
hl.animation({ leaf = "workspaces", enabled = true, speed = 4.5, bezier = "swipeGlide", style = "slide" })
