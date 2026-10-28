import os
import string

import pysrt
from faster_whisper import WhisperModel

from config import MODEL, VIDEO_FPS, UPPERCASE
from subtitle_timing import align_words_to_frames

print("Loading model...")

model = WhisperModel(
    MODEL,
    device="cpu",
    compute_type="int8"
)

print("Model loaded!")


def generate_srt(audio_file, output_name=None):

    print("Starting transcription...")

    segments, _ = model.transcribe(
        audio_file,
        word_timestamps=True
    )

    print("Generating SRT...")

    subs = pysrt.SubRipFile()

    words = []

    for segment in segments:

        if segment.words is None:
            continue

        for word in segment.words:

            REMOVE = ".,!?;:\""

            text = word.word.strip()

            for c in REMOVE:
                text = text.replace(c, "")

            if not text:
                continue

            if UPPERCASE:
                text = text.upper()

            words.append((text, word.start, word.end))

    for index, (text, start_ms, end_ms) in enumerate(
        align_words_to_frames(words, VIDEO_FPS), start=1
    ):
        subs.append(
            pysrt.SubRipItem(
                index=index,
                text=text,
                start=pysrt.SubRipTime(milliseconds=start_ms),
                end=pysrt.SubRipTime(milliseconds=end_ms)
            )
        )

    folder = os.path.dirname(audio_file)

    if output_name:
        output = os.path.join(folder, output_name + ".srt")
    else:
        output = os.path.splitext(audio_file)[0] + ".srt"

    subs.save(output)

    print(f"Saved to {output}")

    return output
