"""episode_frames report.json -> each pixel pair's worst frame per class
(the still pausepoints; the play frames compared, strictly inside each
play), with the frames compared. argv: <frames_b>/report.json."""
import json, sys
r = json.load(open(sys.argv[1]))
worst, n = {}, {}
for f in r["frames"]:
    play = f.get("play") or {}
    for kind, px, frames in (("still", f.get("pixels", {}), 1), ("play", play.get("pixels", {}), len(play.get("pixel_frames", [])))):
        for k, v in px.items():
            key = (k, kind)
            n[key] = n.get(key, 0) + frames
            cur = (v["fraction_pixels_rgb_over24"], v["max_rgba"])
            if key not in worst or cur > worst[key][0]:
                worst[key] = (cur, f["checkpoint"])
for k in sorted(worst):
    print(k, "frames", n[k], "worst", worst[k])
