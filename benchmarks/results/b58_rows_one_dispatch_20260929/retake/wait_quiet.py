"""Wait until three ioreg samples a second apart all read the GPU at or
below 10%, for at most argv[1] seconds. Prints how long it waited and the
last samples; exits 0 when quiet, 1 when it gave up."""
import re, subprocess, sys, time
limit = float(sys.argv[1])
start = time.time()
while True:
    samples = []
    for index in range(3):
        if index:
            time.sleep(1)
        text = subprocess.run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"], capture_output=True, text=True).stdout
        match = re.search(r'"Device Utilization %"=(\d+)', text)
        samples.append(int(match.group(1)) if match else 0)
    if max(samples) <= 10:
        print(f"quiet after {time.time() - start:.0f}s, samples {samples}", flush=True)
        sys.exit(0)
    if time.time() - start > limit:
        print(f"NOT QUIET: gave up after {time.time() - start:.0f}s, last samples {samples}", flush=True)
        sys.exit(1)
    time.sleep(5)
