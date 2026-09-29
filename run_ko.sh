#!/bin/sh
# Taisen Hot Gimmick Kairakuten 한글 개발판 실행 (out/hgkairak.zip, 먼저 tools/khpatch.py build) — MAME 0.289 (Flatpak, user)
# 기본 보기: 1P(왼쪽) 화면만. 두 화면 보기는 ./run.sh -view "Left-to-Right"
cd "$(dirname "$0")"
exec flatpak run --user --command=mame org.mamedev.MAME hgkairak \
  -rompath "$PWD/out" -cfg_directory "$PWD/run_test/cfg" \
  -nvram_directory "$PWD/run_test/nvram" -snapshot_directory "$PWD/run_test/snap" \
  -window -skip_gameinfo -view "Screen 0 Standard (4:3)" "$@"
