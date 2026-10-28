"""Standalone English forced-alignment experiment; not used by the GUI."""

import argparse
import csv
from pathlib import Path

from subtitle_timing import align_words_to_frames
from phrase_alignment import align_phrases, group_phrases


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('audio', type=Path)
	parser.add_argument('srt', type=Path)
	parser.add_argument('--output', type=Path, required=True)
	parser.add_argument('--fps', type=float, default=30)
	parser.add_argument('--phrase-gap', type=float, default=0.2)
	args = parser.parse_args()
	align_words_to_frames([], args.fps)
	group_phrases([], args.phrase_gap)
	if args.output.resolve() in (args.audio.resolve(), args.srt.resolve()):
		parser.error('Output must not overwrite either input')
	if args.output.exists() or args.output.with_suffix('.csv').exists():
		parser.error('Output already exists; choose a new output name')

	import pysrt

	subs = pysrt.open(str(args.srt), encoding='utf-8-sig')
	texts = [sub.text for sub in subs]
	if not texts:
		raise ValueError('Transcript is empty')
	original = [(sub.text, sub.start.ordinal / 1000, sub.end.ordinal / 1000) for sub in subs]
	result = align_phrases(args.audio, original, gap=args.phrase_gap)
	words = result['words']
	display_words = result['display_words']
	word_scores = result['scores']
	phrase_ids = result['phrase_ids']
	aligned = align_words_to_frames(display_words, args.fps)
	output = pysrt.SubRipFile()
	for index, (text, start, end) in enumerate(aligned, 1):
		output.append(pysrt.SubRipItem(index=index, text=text,
			start=pysrt.SubRipTime(milliseconds=start),
			end=pysrt.SubRipTime(milliseconds=end)))
	if ' '.join(cue.text for cue in output) != ' '.join(texts):
		raise ValueError('Output lost transcript text')
	if any(cue.end <= cue.start for cue in output) or any(
		left.end > right.start for left, right in zip(output, output[1:])
	):
		raise ValueError('Output has invalid or overlapping intervals')
	args.output.parent.mkdir(parents=True, exist_ok=True)
	output.save(str(args.output), encoding='utf-8')
	with args.output.with_suffix('.csv').open('w', newline='', encoding='utf-8') as report:
		writer = csv.writer(report)
		writer.writerow(['text', 'original_start', 'original_end',
			'aligned_start_unrounded', 'aligned_end_unrounded', 'mean_token_score',
			'phrase', 'display_end_unrounded'])
		for sub, (_, start, end), score, phrase_id, display in zip(
			subs, words, word_scores, phrase_ids, display_words
		):
			writer.writerow([sub.text, sub.start.ordinal / 1000, sub.end.ordinal / 1000,
				round(start, 4), round(end, 4), round(score, 4) if score is not None else '',
				phrase_id, round(display[2], 4)])
	print('Saved:', args.output.resolve(), flush=True)
	print('Phrase count:', len(set(phrase_ids)), flush=True)
	print('Token scores are diagnostic values, not calibrated accuracy.', flush=True)


if __name__ == '__main__':
	main()
