The device's GPU part, two ways of stamping (2026-09-30 00:35-00:36, the
OrbsScene pilot streams: samples 2, warmups 1, replays 1, navigations 2;
format 8, four stamped and four plain rounds each; calib.py over them).
"all": both ends of every pass stamped (the native instrument's way);
"bracket": the beginning of the first pass and the end of the present
pass. gpu in ms over the class's stamped samples; done the median wait
for onSubmittedWorkDone in the plain rounds; passes a message.

all
phase_a_f8
  seek             n=  4 gpu mean 3.178 med 3.113 min 2.163  done med 13.68  page med 0.465 passes 2.0
  camera           n=108 gpu mean 2.067 med 1.901 min 0.983  done med 2.88  page med 0.035 passes 2.0
  play             n= 36 gpu mean 1.651 med 1.507 min 1.049  done med 3.09  page med 0.245 passes 2.0
  navigation_base  n= 16 gpu mean 1.810 med 1.671 min 1.049  done med 3.17  page med 0.230 passes 2.0
  navigation       n= 16 gpu mean 1.860 med 1.868 min 1.114  done med 3.03  page med 0.212 passes 2.0
phase_b_forced_f8
  seek             n=  4 gpu mean 9.798 med 9.208 min 8.323  done med 15.40  page med 2.250 passes 3.0
  camera           n=108 gpu mean 2.245 med 1.901 min 1.114  done med 2.66  page med 0.050 passes 2.0
  play             n= 36 gpu mean 4.287 med 4.456 min 2.490  done med 4.16  page med 0.387 passes 73.0
  navigation_base  n= 16 gpu mean 2.748 med 2.490 min 1.966  done med 4.08  page med 2.237 passes 3.0
  navigation       n= 16 gpu mean 2.818 med 2.490 min 1.769  done med 4.10  page med 2.025 passes 3.0

bracket
phase_a_f8
  seek             n=  4 gpu mean 3.342 med 3.572 min 2.425  done med 15.05  page med 0.470 passes 2.0
  camera           n=108 gpu mean 2.056 med 1.769 min 1.376  done med 2.30  page med 0.030 passes 2.0
  play             n= 36 gpu mean 1.804 med 1.704 min 1.311  done med 2.57  page med 0.203 passes 2.0
  navigation_base  n= 16 gpu mean 1.819 med 1.704 min 1.376  done med 2.35  page med 0.252 passes 2.0
  navigation       n= 16 gpu mean 1.806 med 1.704 min 1.376  done med 2.37  page med 0.183 passes 2.0
phase_b_forced_f8
  seek             n=  4 gpu mean 9.404 med 9.241 min 9.241  done med 14.93  page med 2.095 passes 3.0
  camera           n=108 gpu mean 1.941 med 1.835 min 1.114  done med 3.21  page med 0.050 passes 2.0
  play             n= 36 gpu mean 3.448 med 3.015 min 1.573  done med 4.80  page med 0.375 passes 73.0
  navigation_base  n= 16 gpu mean 2.626 med 2.556 min 1.966  done med 4.85  page med 2.248 passes 3.0
  navigation       n= 16 gpu mean 2.650 med 2.556 min 1.901  done med 4.59  page med 2.135 passes 3.0

The probe before it (probe.html): an empty compute pass stamps 0 for both
ends; consecutive working passes stamp in steps of 131072 ns (2^17), the
end of one the beginning of the next; performance.now steps of 5 us with
the page cross-origin isolated.
