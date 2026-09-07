"""
Measure whether a camera can support ANPR at all, before arguing about models.

On cam12 the pipeline recovered 8 of 10 characters and still failed validation,
and the reason was not the OCR: the plate was ~55x15 px, about 5 px per
character. No amount of upscaling recovers detail a sensor never captured. So
for any new camera the first question is the size of the plate in pixels, not
the accuracy of the read.

This saves every detection with its box size and the OCR string, so the answer
is a measurement rather than an impression.
"""
import os, sys, time, json
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
sys.path.insert(0, r"D:\Sentinel-Hackathone\backend")
os.chdir(r"D:\Sentinel-Hackathone\backend")
import cv2
import onnxruntime as ort
ort.set_default_logger_severity(4)
from urllib.parse import quote
from app.settings import settings
from app.vision import PlateDetector, frame_is_decodable
from app.plate_grammar import correct_plate

CAM = sys.argv[1] if len(sys.argv) > 1 else "cam14"
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 90
OUT = rf"C:\Users\Admin\AppData\Local\Temp\claude\d--Sentinel-Hackathone\68e6b571-dc2e-4e10-91db-f4792630746c\scratchpad\{CAM}"
os.makedirs(OUT, exist_ok=True)

auth = f"{quote(settings.sentinel_user_email, safe='')}:{quote(settings.sentinel_user_password, safe='')}@"
url = f"rtsp://{auth}{settings.sentinel_ip}:{settings.sentinel_rtsp_port}/stream/{CAM}"

detector = PlateDetector(tiled=True)
cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
print(f"{CAM} opened: {cap.isOpened()}", flush=True)

n = usable = saved = 0
settle = 0
rows = []
t0 = time.time()
scene_saved = False

while time.time() - t0 < SECONDS:
    ok, frame = cap.read()
    if not ok:
        break
    n += 1
    if settle < 30:
        settle += 1
        continue
    if n % 4:
        continue
    if not frame_is_decodable(frame):
        continue
    usable += 1

    if not scene_saved:
        cv2.imwrite(f"{OUT}\\{CAM}_scene.jpg", frame)
        print(f"frame size: {frame.shape[1]}x{frame.shape[0]}", flush=True)
        scene_saved = True

    for d in detector.detect(frame):
        x1, y1, x2, y2 = d.bbox
        w, h = x2 - x1, y2 - y1
        corrected = correct_plate(d.text)
        rows.append({
            "text": d.text, "corrected": corrected.text,
            "valid": corrected.valid, "state_ok": corrected.state_valid,
            "w": w, "h": h, "px_per_char": round(w / max(len(d.text), 1), 1),
            "det_conf": round(d.detector_confidence, 3),
            "ocr_conf": round(d.mean_confidence, 3),
        })
        print(f"  {d.text:12} -> {corrected.text:12} box={w}x{h} "
              f"px/char={w / max(len(d.text), 1):.1f} valid={corrected.valid}", flush=True)
        if saved < 10:
            shot = frame.copy()
            cv2.rectangle(shot, (x1, y1), (x2, y2), (0, 255, 0), 3)
            cv2.putText(shot, f"{d.text} ({w}x{h})", (max(0, x1 - 40), max(24, y1 - 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.imwrite(f"{OUT}\\{CAM}_hit{saved}.jpg", shot)
            pad = 14
            fh, fw = frame.shape[:2]
            crop = frame[max(0, y1 - pad):min(fh, y2 + pad), max(0, x1 - pad):min(fw, x2 + pad)]
            if crop.size:
                cv2.imwrite(f"{OUT}\\{CAM}_crop{saved}.jpg",
                            cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))
            saved += 1

cap.release()
json.dump(rows, open(f"{OUT}\\probe.json", "w"), indent=1)

print(f"\nframes={n} usable={usable} detections={len(rows)}", flush=True)
if rows:
    widths = [r["w"] for r in rows]
    pc = [r["px_per_char"] for r in rows]
    print(f"plate box width: min={min(widths)} max={max(widths)} "
          f"median={sorted(widths)[len(widths) // 2]}")
    print(f"px per character: min={min(pc)} max={max(pc)} "
          f"median={sorted(pc)[len(pc) // 2]}")
    print(f"fully valid reads: {sum(1 for r in rows if r['valid'] and r['state_ok'])}")
    seen = {}
    for r in rows:
        seen[r["text"]] = seen.get(r["text"], 0) + 1
    print("most repeated OCR strings:")
    for t, c in sorted(seen.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {t:14} x{c}")
else:
    print("no plate detected at all")
