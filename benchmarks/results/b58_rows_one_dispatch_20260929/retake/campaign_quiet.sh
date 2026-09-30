#!/bin/zsh
# B5.8 fix pass: the test point retaken (the archive's campaign.sh, B6's
# recipe with B5.6's five stacks), every run waiting first for a quiet GPU
# (three ioreg samples at or below 10%, as B5.7's pass 3 waited): up to
# FIRST_WAIT s before the first run, up to NEXT_WAIT s before each later
# one; a run whose wait gave up is logged NOT QUIET and runs anyway. Then
# the native navigation in three more passes of eight rounds (records and
# rows alternating round by round within each), the 8.a and 3.a.4 plays
# (six replays, alternating), and the plays' GPU attribution with the two
# sources alternating replay by replay (complete_frame.py stamps=1).
set -u
cd /Users/taylorjweidman/Projects/ManimLive/maniml-b5
PY=/Users/taylorjweidman/Projects/ManimLive/maniml/.venv/bin/python
W=${W:?scratch folder}
D=$W/runs
E=${E:?episode tree}
FIRST_WAIT=${FIRST_WAIT:-900}
NEXT_WAIT=${NEXT_WAIT:-120}
WAIT=$FIRST_WAIT
mkdir -p $D
for v in ${(k)parameters[(I)MANIML_*]}; do unset $v; done
export PYTHONPATH=$PWD
F=(--tick-updaters --play-frames)
B=(phase_b_retained phase_b_retained_records)
conditions() {
  { echo "== $1 $(date '+%Y-%m-%dT%H:%M:%S')"; uptime; pmset -g batt | head -1;
    for i in 1 2 3; do ioreg -r -c IOAccelerator -d 1 | grep -o '"Device Utilization %"=[0-9]*'; sleep 1; done;
    ps -Ao pcpu,pid,comm -r | awk 'NR>1 && $1>10'; } >> $D/conditions.log
}
run() {
  local name=$1; shift
  echo "-- wait $name $(date '+%H:%M:%S') $($PY $W/wait_quiet.py $WAIT)" >> $D/conditions.log
  WAIT=$NEXT_WAIT
  conditions "start $name"
  "$@" > $D/$name.log 2>&1
  echo "exit $? $name" >> $D/conditions.log
  conditions "end $name"
}
scene() {
  local tag=$1 file=$2 cls=$3 gate=$4
  local S=($file $cls)
  local d=$D/$tag
  mkdir -p $d
  run ${tag}_frames_a $PY -m benchmarks.episode_frames --scene $S --variants retained default gpu_border $F --output $d/frames_a
  run ${tag}_frames_b $PY -m benchmarks.episode_frames --scene $S --variants $B gpu_border $F --output $d/frames_b
  run ${tag}_gpu1 $PY -m benchmarks.episode_frames --scene $S --variants gpu_border retained default $B $F --gpu-timestamps --output $d/gpu1
  run ${tag}_browser $PY -m benchmarks.browser_frames --scene $S --variants phase_a default phase_b_forced phase_b_forced_records $F --deltas --realm main --rounds 5 --output $d/browser
  run ${tag}_page $PY -m benchmarks.test_point page --stream $d/browser/phase_a --revision main --rounds 5 --output $d/page
  run ${tag}_serialize $PY -m benchmarks.test_point serialize --scene $S $F --output $d/serialize
  run ${tag}_gpu2 $PY -m benchmarks.episode_frames --scene $S --variants gpu_border retained default $B $F --gpu-timestamps --output $d/gpu2
  run ${tag}_table $PY -m benchmarks.test_point table --serialize $d/serialize --browser $d/browser --page $d/page --gpu $d/gpu1 $d/gpu2 --pixels $d/frames_b $d/frames_a --output $d/table
  run ${tag}_seek $PY benchmarks/results/b56_rows_source_20260929/seek_frames.py $file $cls 4
  run ${tag}_play $PY benchmarks/results/b56_rows_source_20260929/complete_frame.py $file $cls $gate 6 0
}
extra() {
  local tag=$1 file=$2 cls=$3 gate=$4
  for pass in 1 2 3; do
    run ${tag}_seek8_$pass $PY benchmarks/results/b56_rows_source_20260929/seek_frames.py $file $cls 8
  done
  run ${tag}_play_stamps $PY benchmarks/results/b56_rows_source_20260929/complete_frame.py $file $cls $gate 6 1
}
{ git diff HEAD -- maniml tests | shasum -a 256; shasum -a 256 maniml/web/static/wgsl/row_finalize_table.wgsl; git rev-parse HEAD; } > $D/tree.sha
for which in "$@"; do
  case $which in
    b2) scene b2 $E/Blocks/B2_Supply/03_Code.py EpisodeB2 307 ;;
    b3) scene b3 $E/Blocks/B3_Equilibrium/Animate.py PriceDiscovery 63 ;;
    x2) extra b2 $E/Blocks/B2_Supply/03_Code.py EpisodeB2 307 ;;
    x3) extra b3 $E/Blocks/B3_Equilibrium/Animate.py PriceDiscovery 63 ;;
  esac
done
echo "all done $(date)" >> $D/conditions.log
