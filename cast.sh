#!/usr/bin/env bash
# cast.sh — the channel source, without a browser.
#
# Renders a slate with ffmpeg (no Chromium, no Playwright) so the HLS pipeline is
# proven in minutes. Swapping in the Atrium is a source change, not a pipeline
# change: same encoder, same segments, same player.
#
#   ./cast.sh /var/lib/atrium-cast/hls/atrium
set -euo pipefail
OUT_DIR="${1:-/var/lib/atrium-cast/hls/atrium}"
TITLE="${TITLE:-HAL-fm Atrium}"
mkdir -p "$OUT_DIR"
exec ffmpeg -hide_banner -loglevel warning -re \
  -f lavfi -i "color=c=0x0b0d10:s=1280x720:r=25" \
  -vf "drawtext=text='${TITLE}':fontcolor=0xe8eaed:fontsize=44:x=(w-text_w)/2:y=(h-text_h)/2-30,drawtext=text='LIVE':fontcolor=0x1f6feb:fontsize=22:x=(w-text_w)/2:y=(h-text_h)/2+40" \
  -c:v libx264 -preset veryfast -tune zerolatency -g 50 -keyint_min 50 -sc_threshold 0 \
  -an -f hls -hls_time 2 -hls_list_size 6 \
  -hls_segment_filename "$OUT_DIR/seg%05d.ts" "$OUT_DIR/index.m3u8"
