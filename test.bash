#!/bin/bash

COLORS=(
  "rgba(8be9fdff)"
  "rgba(ff79c6ff)"
  "rgba(57c7ffff)"
  "rgba(ff5da2ff)"
  "rgba(50fa7bff)"
  "rgba(00ff88ff)"
)

hyprctl keyword animation.border "1, 2000, myepiccurve, linear"


while true; do
  for c in "${COLORS[@]}"; do
    hyprctl keyword general:col.active_border "$c" >/dev/null
    sleep 1
  done
done
