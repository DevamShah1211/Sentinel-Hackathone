# Training the recogniser - the assessment, and the decision

**Short version.** We built the training path, ran the feasibility assessment
against our own data, and did not train. The data cannot support it, and the
measured limit on the government cameras is optics rather than the model. This
document is the working, so the decision can be checked rather than taken on
trust.

---

## 1. The question

Fine-tuning the plate recogniser on Indian registrations is the obvious way to
improve accuracy. Time was not the obstacle - twenty CPU cores can fine-tune a
small OCR head in a few hours. So the question is only whether the available
data supports it.

`tools/train_ocr.py --assess` answers that, and refuses to train when the answer
is no.

## 2. What the assessment found

Run against the dataset built from every crop this deployment has produced:

```
  labelled crops     : 123
  distinct plates    : 13
  from real cameras  : 0 (0%)
  synthetic          : 123
  crops per plate    : min 1  median 4  max 32
```

Three blockers, each with a threshold chosen for a reason rather than by feel:

| Requirement | Have | Need | Why that number |
|---|---|---|---|
| Labelled crops | 123 | 500 | Below this a held-out split is too small for a reported accuracy to mean anything |
| Distinct registrations | 13 | 100 | Below this the model memorises specific plates instead of learning to read characters |
| From real cameras | 0% | 60% | Synthetic crops share one font on a clean background; a model trained on them learns the font |

For scale, published Indian ANPR work uses **10,000 to 100,000** annotated real
crops. 123 is roughly one percent of the low end, and none of it is real.

## 3. Why training on this data would have made the submission worse

**It would overfit invisibly.** Trained on thirteen registrations and validated
on images of the same thirteen, it would report near-perfect accuracy. Our
end-to-end benchmark would still show 6/6, because that benchmark uses the same
synthetic clip. The failure would appear for the first time in front of the
jury.

**It would not move the real limit.** The measured ceiling on the sandbox is
**5 pixels per character at cam12** and **10 at cam14**, against the 20-30 that
ANPR needs (see MEASUREMENTS sections 2b and 2c). No model reads characters the
sensor never captured. A better recogniser does not change that number.

**It is the claim a reviewer will test hardest.** "We trained our own OCR"
invites: on what data, labelled by whom, what was held out, how do you know it
generalises. "We used a pretrained recogniser and put the India-specific
knowledge in a layer you can read and test" is answerable, and it is what we
did.

## 4. What the training path looks like, if the data existed

The tools are written and work today:

```
# Capture real crops from a phone, webcam or NVR feed
python tools/collect_dataset.py --source "rtsp://192.168.1.42:8554/live"

# Label them - the recogniser proposes, you confirm or correct (~2s each)
python tools/collect_dataset.py --label

# Check whether the dataset can support training
python tools/train_ocr.py --assess
```

Two design decisions in there are worth stating, because both were mistakes
first:

**Provenance is recorded, not inferred.** The first version guessed whether a
crop was real from its filename and plate, and reported a wholly synthetic
dataset as *81% real* - the demonstration seeder stamps camera names like
`cam01` onto crops taken from a rendered clip. A training tool whose first
measurement flatters the data is worse than no tool, so `source` became a column
written at capture time.

**The split is by registration, never by crop.** Splitting by crop puts
different photographs of the same plate on both sides, so a model scores well by
memorising registrations it has already seen. Splitting by plate is the only
division that measures reading.

The training loop itself is deliberately not implemented. Writing an untested
loop against data that cannot run it would look finished and would not be. When
a dataset passes the assessment, the shape is a CTC head over the existing
backbone, trained here and exported to ONNX so `app/vision.py` loads it
unchanged.

## 5. What we did instead

The accuracy work went into layers that can be tested and explained:

| Change | Effect |
|---|---|
| Complete character confusion model | Grammar benchmark 23/24 to 24/24 |
| Ambiguity-aware RTO / series splitting | Fixed `GJ0LAB1234`, protected Delhi's `DL8C` |
| Refinement pass on failed tracks | Rescues without degrading; retried votes accepted only if valid |
| Real RTO district data | Reports the district, breaks ties toward one that exists |
| Multi-office city grouping | Ahmedabad is GJ-01 *and* GJ-27; a district search no longer misses half |
| Learned plate prior | Settles genuine ties from what the deployment has indexed |

End state: **24/24** on real captured OCR strings, **6/6 with no false
positives** end to end, **98 unit tests**.

## 6. If this project continues

The order that would actually pay:

1. **Collect real crops.** 500 to start, from cameras sited for ANPR rather than area overview. `collect_dataset.py` does the capture and labelling.
2. **Re-run the assessment.** It says when training becomes defensible.
3. **Fix the optics first anyway.** A camera giving 25 pixels per character with the pretrained model beats one giving 10 with a fine-tuned model. That is the finding from cam12 and cam14, and it is a procurement decision, not a research one.
