import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pysrt

from subtitle_timing import align_words_to_frames


class SubtitleTimingTests(unittest.TestCase):
	def test_short_words_are_not_extended_to_180_ms(self):
		result = align_words_to_frames([
			("ONE", 1.0, 1.05), ("TWO", 1.1, 1.2)
		], 30)
		self.assertEqual(result, [("ONE", 1000, 1067), ("TWO", 1100, 1200)])

	def test_overlap_is_capped_at_next_start(self):
		result = align_words_to_frames([
			("ONE", 1.0, 1.3), ("TWO", 1.1, 1.2)
		], 30)
		self.assertEqual(result, [("ONE", 1000, 1100), ("TWO", 1100, 1200)])

	def test_speech_gap_is_preserved(self):
		self.assertEqual(align_words_to_frames([
			("ONE", 0.0, 0.2), ("TWO", 1.0, 1.2)
		], 30), [("ONE", 0, 200), ("TWO", 1000, 1200)])

	def test_same_frame_words_keep_all_text(self):
		self.assertEqual(align_words_to_frames([
			("ONE", 0.001, 0.005), ("TWO", 0.01, 0.08),
			("THREE", 0.04, 0.1)
		], 30), [("ONE TWO", 0, 33), ("THREE", 33, 100)])

	def test_zero_duration_word_gets_one_frame(self):
		self.assertEqual(align_words_to_frames([
			("ONE", 0.1, 0.1)
		], 30), [("ONE", 100, 133)])

	def test_negative_and_out_of_order_timestamps_keep_text(self):
		self.assertEqual(align_words_to_frames([
			("ONE", -0.1, 0.1), ("TWO", 0.2, 0.3),
			("THREE", 0.1, 0.4)
		], 30), [("ONE", 0, 100), ("TWO THREE", 200, 400)])

	def test_empty_input(self):
		self.assertEqual(align_words_to_frames([], 30), [])

	def test_invalid_fps(self):
		for fps in (0, -30, float("nan"), float("inf"), 1001):
			with self.subTest(fps=fps), self.assertRaises(ValueError):
				align_words_to_frames([], fps)

	def test_nonfinite_timestamps(self):
		for start, end in ((float("nan"), 1), (0, float("inf"))):
			with self.subTest(start=start, end=end), self.assertRaises(ValueError):
				align_words_to_frames([("ONE", start, end)], 30)

	def test_frame_boundaries_stay_positive_and_nonoverlapping(self):
		words = [(str(i), i / 100, i / 100 + 0.18) for i in range(1000)]
		cues = align_words_to_frames(words, 30)
		self.assertEqual(" ".join(cue[0] for cue in cues),
						 " ".join(word[0] for word in words))
		for index, (_, start, end) in enumerate(cues):
			self.assertLess(start, end)
			if index:
				self.assertLessEqual(cues[index - 1][2], start)
			for milliseconds in (start, end):
				nearest_frame = round(milliseconds * 30 / 1000)
				self.assertLessEqual(abs(milliseconds - nearest_frame * 1000 / 30), 0.5)

	def test_generated_srt_handles_overlap_across_segments(self):
		def word(text, start, end):
			return SimpleNamespace(word=text, start=start, end=end)

		segments = [SimpleNamespace(words=[word("one!", 1.0, 1.3)]),
					SimpleNamespace(words=None),
					SimpleNamespace(words=[word("...", 1.05, 1.1),
										   word("two", 1.1, 1.2)])]
		model = Mock()
		model.transcribe.return_value = (iter(segments), SimpleNamespace(language='en'))
		fake_whisper = SimpleNamespace(WhisperModel=Mock(return_value=model))
		path = Path(__file__).resolve().parents[1] / "transcriber.py"
		spec = importlib.util.spec_from_file_location("transcriber_test", path)
		module = importlib.util.module_from_spec(spec)
		with patch.dict("sys.modules", {"faster_whisper": fake_whisper}):
			spec.loader.exec_module(module)
		with tempfile.TemporaryDirectory() as folder, patch.object(module, 'align_phrases') as align:
			align.return_value = {'display_words': [('ONE', 1.0, 1.1), ('TWO', 1.1, 1.2)],
				'warnings': ['Test fallback notice']}
			notice = Mock()
			audio = str(Path(folder) / "sample.mp3")
			output = module.generate_srt(audio, "captions", on_warning=notice)
			align.assert_called_once_with(audio, [('ONE', 1.0, 1.1), ('TWO', 1.1, 1.2)], language='en')
			notice.assert_called_once()
			self.assertEqual(output, str(Path(folder) / "captions.srt"))
			cues = pysrt.open(output)
			self.assertEqual([(cue.index, cue.text, cue.start.ordinal, cue.end.ordinal)
							  for cue in cues],
							 [(1, "ONE", 1000, 1100), (2, "TWO", 1100, 1200)])
		model.transcribe.assert_called_once_with(audio, word_timestamps=True)


if __name__ == "__main__":
	unittest.main()
