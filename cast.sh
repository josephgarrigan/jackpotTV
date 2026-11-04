#!/usr/bin/env bash
# cast.sh — the channel source, without a browser.
#
# The first version renders a slate with ffmpeg (no Chromium, no Playwright): it
# proves HLS end to end in minutes. Swapping in the Atrium is a source change
# (x11grab / screenshots), not a pipeline change — same encoder, same segments.
#
#   ./cast.sh /var/lib/atrium-cast/hls/atrium
set -euo pipefail
OUT_DIR="${1:-/var/lib/atrium-cast/hls/atrium}"
TITLE="${TITLE:-HAL-fm · the Atrium}"
mkdir -p "$OUT_DIR"
exec ffmpeg -hide_banner -loglevel warning -re \
  -f lavfi -i "color=c=0x0b0d10:s=1280x720:r=25" \
  -vf "drawtext=text='${TITLE}':fontcolor=0xe8eaed:fontsize=44:x=(w-text_w)/2:y=(h-text_h)/2-40,\
drawtext=text='live':fontcolor=0x1f6feb:fontsize=22:x=(w-text_w)/2:y=(h-text_h)/2+30,\
drawtext=text='%{localtime\\:%H\\\\:%M\\\\:%S}':fontcolor=0x7d8796:fontsize=20:x=40:y=h-60" \
  -c:v libx264 -preset veryfast -tune zerolatency -g 50 -keyint_min 50 -sc_threshold 0 \
  -c:a none -f hls -hls_time 2 -hls_list_size 6 \
  -hls_segment_filename "$OUT_DIR/seg%05d.ts" "$OUT_DIR/index.m3u8"
