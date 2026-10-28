from types import SimpleNamespace
import unittest
from unittest.mock import patch

from phrase_alignment import (
	align_phrases, continuous_phrase, encode_transcript, group_phrases, phrase_windows, word_intervals
)
from subtitle_timing import align_words_to_frames


class AlignmentExperimentTests(unittest.TestCase):
	labels = tuple("-|ABCDEFGHIJKLMNOPQRSTUVWXYZ'")

	def test_empty_transcript_does_not_load_model(self):
		with patch('phrase_alignment.get_alignment_model') as load:
			self.assertEqual(align_phrases('unused.mp3', [])['display_words'], [])
			load.assert_not_called()

	def test_other_language_preserves_words_without_loading_english_model(self):
		words = [('EU', 0, 0.1), ('A', 0.15, 0.2)]
		with patch('phrase_alignment.get_alignment_model') as load, self.assertWarns(UserWarning):
			result = align_phrases('unused.mp3', words, language='ro')
		self.assertEqual(result['display_words'], [('EU', 0, 0.15), ('A', 0.15, 0.2)])
		self.assertTrue(result['warnings'])
		load.assert_not_called()

	def test_unsupported_text_is_preserved_with_warning(self):
		with patch('phrase_alignment.get_alignment_model') as load, self.assertWarns(UserWarning):
			result = align_phrases('unused.mp3', [('123', 0, 1)])
		self.assertEqual(result['display_words'], [('123', 0, 1)])
		load.assert_not_called()

	def test_alignment_preserves_single_letters_and_continuity(self):
		import numpy as np
		original = [('DRAW', 0.1, 0.2), ('A', 0.2, 0.3), ('PIG', 0.3, 0.5)]
		acoustic = [('DRAW', 0.11, 0.19), ('A', 0.23, 0.25), ('PIG', 0.31, 0.55)]
		with patch('phrase_alignment.get_alignment_model', return_value=(object(), SimpleNamespace(sample_rate=16000))), patch(
			'phrase_alignment.decode_audio', return_value=np.zeros(16000, dtype=np.float32)
		), patch('phrase_alignment.align_phrase', return_value=(acoustic, [0.8] * 3)):
			result = align_phrases('unused.mp3', original)
		self.assertEqual(result['display_words'], [('DRAW', 0.11, 0.23), ('A', 0.23, 0.31), ('PIG', 0.31, 0.55)])
		self.assertFalse(result['warnings'])

	def test_long_phrase_has_explicit_fallback(self):
		import numpy as np
		with patch('phrase_alignment.get_alignment_model', return_value=(object(), SimpleNamespace(sample_rate=16000))), patch(
			'phrase_alignment.decode_audio', return_value=np.zeros(32 * 16000, dtype=np.float32)
		), patch('phrase_alignment.align_phrase') as align, self.assertWarns(UserWarning):
			result = align_phrases('unused.mp3', [('LONG', 0, 31)])
		self.assertEqual(result['display_words'], [('LONG', 0, 31)])
		align.assert_not_called()

	def test_internal_gaps_close_without_changing_phrase_edges(self):
		words = [('ONE', 1.0, 1.1), ('TWO', 1.2, 1.3), ('THREE', 1.4, 1.6)]
		self.assertEqual(align_words_to_frames(continuous_phrase(words), 30),
			[('ONE', 1000, 1200), ('TWO', 1200, 1400), ('THREE', 1400, 1600)])

	def test_long_pauses_separate_phrases(self):
		words = [('ONE', 0.0, 0.1), ('TWO', 0.15, 0.3), ('THREE', 0.6, 0.8)]
		groups = group_phrases(words)
		self.assertEqual(groups, [words[:2], words[2:]])
		self.assertEqual(continuous_phrase(groups[0])[-1][2], 0.3)

	def test_exact_gap_boundary(self):
		self.assertEqual(len(group_phrases([('A', 1.0, 1.2), ('B', 1.4, 1.5)])), 2)

	def test_windows_are_disjoint_and_clamped_to_audio(self):
		groups = [[('A', 0.0, 0.5)], [('B', 0.8, 1.0)], [('C', 1.3, 1.9)]]
		windows = phrase_windows(groups, 2.0)
		self.assertEqual(windows[0][0], 0)
		self.assertEqual(windows[-1][1], 2.0)
		for left, right in zip(windows, windows[1:]):
			self.assertLessEqual(left[1], right[0])

	def test_single_word_and_empty_phrase(self):
		self.assertEqual(continuous_phrase([('A', 1, 2)]), [('A', 1, 2)])
		self.assertEqual(continuous_phrase([]), [])
		self.assertEqual(group_phrases([]), [])

	def test_invalid_phrase_gap(self):
		for gap in (0, -1, float('nan'), float('inf')):
			with self.subTest(gap=gap), self.assertRaises(ValueError):
				group_phrases([], gap)

	def test_preserves_apostrophe_and_word_ranges(self):
		tokens, ranges = encode_transcript(["LET’S", "DRAW"], self.labels)
		self.assertEqual(''.join(self.labels[t] for t in tokens), "LET'S|DRAW")
		self.assertEqual(ranges, [(0, 5), (6, 10)])

	def test_grouped_caption_keeps_internal_separator(self):
		tokens, ranges = encode_transcript(['A PIG', 'YES'], self.labels)
		self.assertEqual(''.join(self.labels[t] for t in tokens), 'A|PIG|YES')
		self.assertEqual(ranges, [(0, 5), (6, 9)])

	def test_unsupported_text_is_not_silently_dropped(self):
		for text in ('123', 'HELLO!', '', '你好'):
			with self.subTest(text=text), self.assertRaises(ValueError):
				encode_transcript([text], self.labels)

	def test_word_times_exclude_surrounding_separator(self):
		spans = [SimpleNamespace(start=i * 2, end=i * 2 + 1) for i in range(4)]
		self.assertEqual(word_intervals(['AB', 'C'], [(0, 2), (3, 4)], spans, 0.02),
			[('AB', 0.0, 0.06), ('C', 0.12, 0.14)])

	def test_mismatched_alignment_is_rejected(self):
		with self.assertRaises(ValueError):
			word_intervals(['AB'], [(0, 2)], [], 0.02)

	def test_invalid_time_scale_is_rejected(self):
		for scale in (0, -1, float('nan')):
			with self.subTest(scale=scale), self.assertRaises(ValueError):
				word_intervals([], [], [], scale)


if __name__ == '__main__':
	unittest.main()
