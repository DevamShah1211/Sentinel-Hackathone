# Live demonstration runbook

**Recognising a real plate in front of the jury.**

The seeded data is enough for the recorded videos. A live presentation is a
different problem: a jury will want to see the pipeline read a plate it has
never seen, in the room, with nothing prepared. This is how that is done
reliably.

---

## The decision, and why

**Do not attempt the live read on a sandbox camera.** This is measured, not a
guess:

| Camera | Pixels per plate character | Validated reads |
|---|---|---|
| cam12, Tri Mandir Adalaj toll plaza | ~5 | 0 |
| cam14, Delight red-light camera | ~10 | 0 |
| Your own phone at the roadside | 40+ | reliable |
| Synthetic clip (measured baseline) | 16 median | 89 of 99 |

Both government cameras are sited for wide-area observation. The pipeline
recovers eight of ten characters and the Indian plate grammar correctly refuses
them. Nothing you can do on the day changes what those sensors captured, and a
demonstration that depends on a vehicle happening to stop near the camera can
fail in front of the jury - a four-minute capture of cam14 returned **zero
detections** because the junction had emptied.

The playbook already anticipates this and asks for your own feed for the
demonstration: *"a phone video of a road with a readable plate is fine,
restreamed as RTSP."* So the live read runs on a feed you control, through the
**identical** production pipeline - same detector, same tiled inference, same
track-level voting, same grammar, same watchlist matching. Nothing is faked and
nothing is special-cased. The only difference from the sandbox is the camera.

This is also the more honest demonstration, because it lets you say the true
thing out loud: the software works, and the government's cameras need different
optics.

---

## Before the day

### 1. Get a phone streaming RTSP

Install an IP-camera app on the phone. Any of these work and are free:

- **IP Webcam** (Android) - starts an HTTP/MJPEG server, easiest
- **RTSP Camera Server** (Android)
- **Larix Broadcaster** (Android and iOS)

Start the server. The app shows a URL such as `http://192.168.1.42:8080/video`
or `rtsp://192.168.1.42:8554/live`. **The phone and the laptop must be on the
same network.** A phone hotspot that the laptop joins is the most reliable
option at a venue, because it does not depend on their Wi-Fi.

### 2. Prepare the vehicle

You need one plate that is unambiguously readable. Options, best first:

- **A parked car.** Frame the plate so it fills roughly a quarter of the frame width.
- **Your own vehicle**, so no consent question arises.
- **A printed plate** on card, correctly formatted, held at a realistic distance. Say plainly that it is printed if you use it.

### 3. Rehearse the check

```
cd backend
python tools/live_demo.py --source "rtsp://192.168.1.42:8554/live" --check
```

It reports pixels per character and whether reads pass validation. **READY**
means present it. **TOO FAR** means move closer or zoom in. Rehearse until you
get READY twice in a row from a standing start.

---

## At the venue, before you present

Run these in order. Budget ten minutes.

```
# 1. Backend and frontend up
cd backend && python run_server.py
cd frontend && npm run dev

# 2. Phone streaming, laptop on the same network. Confirm the feed:
cd backend
python tools/live_demo.py --source "rtsp://<phone-ip>:8554/live" --check
```

If the check does not say READY, fix it now, not during the presentation.
Move closer, improve the light, get a more front-on angle.

```
# 3. Arm the watchlist with the plate you will show,
#    so recognising it raises a visible alert.
python tools/live_demo.py --source "rtsp://<phone-ip>:8554/live" --arm GJ01AB1234
```

---

## The live sequence

Have two windows visible: the terminal and the browser on the Alerts page.

```
python tools/live_demo.py --source "rtsp://<phone-ip>:8554/live"
```

1. **Say what is about to happen.** "This is a live phone feed, running the same pipeline as the government cameras. Nothing is pre-recorded."
2. **Point the phone at the plate.** Within a few seconds the terminal prints the plate, its confidence, and the number of frames voted.
3. **The alert fires.** `*** WATCHLIST ALERT ***` appears, and the browser shows it arriving over the live socket without a refresh.
4. **Click the alert.** The detail panel opens with the evidence crop, the watchlist match and the sighting.
5. **Open Plate Search** and search the plate. The sighting and its route are there.

Then say the honest part, which is your strongest moment:

> "We ran this same pipeline against the department's own cameras. At the Adalaj
> toll plaza it recovered eight of the ten characters of a real truck plate,
> twenty-five times. It could not validate them, because that camera gives about
> five pixels per character and the red-light camera at Delight gives about ten.
> This feed gives forty. The limit is the optics, not the software, and that is a
> lens specification for procurement, not a research problem."

---

## If something fails

| Symptom | Do this |
|---|---|
| `could not open` the source | Phone and laptop on the same network? URL exactly as the app shows it? Try the phone's hotspot. |
| No plate detected | Move closer. The plate should fill about a quarter of the frame width. |
| Detected but never validated | The read is too small or too angled. Get more front-on, and closer. |
| Backend refused the detection | Is `run_server.py` still running? Check the terminal. |
| Everything fails | Fall back to the recorded video. Say plainly that the network is not cooperating and play Video 1. This is why the recording exists. |

**Have Video 1 open in a tab before you start.** A presenter who switches to a
recording in five seconds looks prepared. One who debugs a network for two
minutes does not.

---

## What to say if the jury asks for the government feed specifically

Be direct. Do not improvise around it:

> "I can run it on any of the thirty right now, and I will. What you will see is
> the detector finding the plate and the recogniser reading most of it, and our
> grammar check refusing it rather than indexing a guess. We measured why: five
> pixels per character at the toll plaza, ten at the red-light camera, against
> the twenty to thirty that ANPR needs. We would rather show you a correct
> refusal than a fabricated read."

Then run it on cam12 and show the partial read, which is stored, searchable, and
badged unverified. That answer is stronger than a lucky read would be, because
it shows the system knows what it does not know.
