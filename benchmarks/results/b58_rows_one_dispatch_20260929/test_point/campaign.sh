#!/bin/zsh
# B5.8: B6's recipe (benchmarks/README.md "The test point") with B5.6's five
# stacks, the forced Phase B as the selection sends it (rows, now one
# dispatch and keyed on geometry) and phase_b_records beside it; then the
# native navigation and the 8.a play (B5.6's seek_frames.py and
# complete_frame.py). One run at a time, the conditions at each run's start
# and end. The instrumented python run is left out.
set -u
cd /Users/taylorjweidman/Projects/ManimLive/maniml-b5
PY=/Users/taylorjweidman/Projects/ManimLive/maniml/.venv/bin/python
W=${W:?scratch folder}
D=$W/runs
E=${E:?episode tree}
mkdir -p $D
for v in ${(k)parameters[(I)MANIML_*]}; do unset $v; done
export PYTHONPATH=$PWD
F=(--tick-updaters --play-frames)
B=(phase_b_retained phase_b_retained_records)
conditions() {
  { echo "== $1 $(date '+%Y-%m-%dT%H:%M:%S')"; uptime;
    for i in 1 2 3; do ioreg -r -c IOAccelerator -d 1 | grep -o '"Device Utilization %"=[0-9]*'; sleep 1; done;
    ps -Ao pcpu,pid,comm -r | awk 'NR>1 && $1>10'; } >> $D/conditions.log
}
run() {
  local name=$1; shift
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
for which in "$@"; do
  case $which in
    b2) scene b2 $E/Blocks/B2_Supply/03_Code.py EpisodeB2 307 ;;
    b3) scene b3 $E/Blocks/B3_Equilibrium/Animate.py PriceDiscovery 63 ;;
  esac
done
echo "all done $(date)" >> $D/conditions.log
