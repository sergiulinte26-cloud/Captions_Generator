import math


def align_words_to_frames(words, fps):
	if not math.isfinite(fps) or fps <= 0 or fps > 1000:
		raise ValueError("FPS must be positive and no greater than 1000.")

	cues = []

	for text, start, end in words:
		if not math.isfinite(start) or not math.isfinite(end):
			raise ValueError("Word timestamps must be finite.")

		start_frame = max(0, math.floor(start * fps + 0.5))
		if cues:
			start_frame = max(start_frame, cues[-1][1])
		end_frame = max(start_frame + 1, math.floor(end * fps + 0.5))

		if cues and start_frame == cues[-1][1]:
			previous_text, _, previous_end = cues[-1]
			cues[-1] = (previous_text + " " + text, start_frame,
						max(previous_end, end_frame))
		else:
			cues.append((text, start_frame, end_frame))

	aligned = []

	for index, (text, start_frame, end_frame) in enumerate(cues):
		if index + 1 < len(cues):
			end_frame = min(end_frame, cues[index + 1][1])

		start_ms = math.floor(start_frame * 1000 / fps + 0.5)
		end_ms = math.floor(end_frame * 1000 / fps + 0.5)
		aligned.append((text, start_ms, end_ms))

	return aligned
