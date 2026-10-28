import os
import string

import pysrt
from faster_whisper import WhisperModel

from config import MODEL, VIDEO_FPS, UPPERCASE
from subtitle_timing import align_words_to_frames
from phrase_alignment import align_phrases

print("Loading model...")

model = WhisperModel(
    MODEL,
    device="cpu",
    compute_type="int8"
)

print("Model loaded!")


def generate_srt(audio_file, output_name=None, on_warning=None):

    print("Starting transcription...")

    segments, info = model.transcribe(
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

    original = [(text, start / 1000, end / 1000)
                for text, start, end in align_words_to_frames(words, VIDEO_FPS)]
    result = align_phrases(audio_file, original, language=info.language)
    if result['warnings'] and on_warning is not None:
        on_warning("Some phrases used continuous Whisper timings instead of alignment:\n\n"
                   + "\n".join(result['warnings'][:5]))

    for index, (text, start_ms, end_ms) in enumerate(
        align_words_to_frames(result['display_words'], VIDEO_FPS), start=1
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
