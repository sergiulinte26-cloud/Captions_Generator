import functools
import math
import os
from pathlib import Path
import re
import warnings


def group_phrases(words, gap=0.2):
	if not math.isfinite(gap) or gap <= 0:
		raise ValueError('Phrase gap must be positive and finite')
	groups = []
	for word in words:
		if not groups or word[1] - groups[-1][-1][2] >= gap - 1e-9:
			groups.append([])
		groups[-1].append(word)
	return groups


def phrase_windows(groups, duration):
	windows = []
	for index, group in enumerate(groups):
		left = 0 if index == 0 else (groups[index - 1][-1][2] + group[0][1]) / 2
		right = duration if index + 1 == len(groups) else (group[-1][2] + groups[index + 1][0][1]) / 2
		start = max(0, left, group[0][1] - 0.25)
		end = min(duration, right, group[-1][2] + 0.35)
		if end <= start:
			raise ValueError('Phrase falls outside the audio')
		windows.append((start, end))
	return windows


def continuous_phrase(words):
	return [(text, start, words[index + 1][1] if index + 1 < len(words) else end)
			for index, (text, start, end) in enumerate(words)]


def encode_transcript(texts, labels):
	vocabulary = {label: index for index, label in enumerate(labels)}
	tokens = []
	ranges = []
	for text in texts:
		normalized = text.upper().replace('’', "'")
		if not re.fullmatch(r"[A-Z']+(?: [A-Z']+)*", normalized):
			raise ValueError('Unsupported English transcript text: ' + text)
		if tokens:
			tokens.append(vocabulary['|'])
		start = len(tokens)
		tokens.extend(vocabulary[c] for c in normalized.replace(' ', '|'))
		ranges.append((start, len(tokens)))
	return tokens, ranges


def word_intervals(texts, ranges, spans, seconds_per_frame):
	if not math.isfinite(seconds_per_frame) or seconds_per_frame <= 0:
		raise ValueError('Invalid acoustic frame duration')
	if len(texts) != len(ranges) or not ranges or ranges[-1][1] != len(spans):
		raise ValueError('Alignment token count does not match transcript')
	return [(text, spans[start].start * seconds_per_frame,
			 spans[end - 1].end * seconds_per_frame)
			for text, (start, end) in zip(texts, ranges)]


def decode_audio(path, sample_rate):
	import av
	import numpy as np

	resampler = av.AudioResampler(format='fltp', layout='mono', rate=sample_rate)
	chunks = []
	with av.open(str(path)) as container:
		for frame in container.decode(audio=0):
			chunks.extend(output.to_ndarray().reshape(-1)
						  for output in resampler.resample(frame))
		chunks.extend(output.to_ndarray().reshape(-1)
					  for output in resampler.resample(None))
	if not chunks:
		raise ValueError('Audio is empty')
	return np.concatenate(chunks)


@functools.lru_cache(maxsize=1)
def get_alignment_model():
	import torchaudio

	cache = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache')) / 'CaptionsGenerator' / 'models'
	cache.mkdir(parents=True, exist_ok=True)
	bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
	print('Loading English alignment model (first use may download weights)...', flush=True)
	model = bundle.get_model(dl_kwargs={'model_dir': str(cache)}).eval()
	return model, bundle


def align_phrase(clip, texts, offset, model, bundle):
	import torch
	import torchaudio

	tokens, ranges = encode_transcript(texts, bundle.get_labels())
	waveform = torch.from_numpy(clip).unsqueeze(0)
	with torch.inference_mode():
		emission, _ = model(waveform)
		log_probs = emission.log_softmax(-1)
		targets = torch.tensor([tokens], dtype=torch.int32)
		path, scores = torchaudio.functional.forced_align(log_probs, targets, blank=0)
		spans = torchaudio.functional.merge_tokens(path[0], scores[0].exp(), blank=0)
	if [span.token for span in spans] != tokens:
		raise ValueError('Aligned characters differ from supplied transcript')
	seconds_per_frame = len(clip) / bundle.sample_rate / emission.shape[1]
	words = [(text, offset + start, offset + end)
		for text, start, end in word_intervals(texts, ranges, spans, seconds_per_frame)]
	scores = [sum(span.score for span in spans[first:last]) / (last - first)
		for first, last in ranges]
	return words, scores


def align_phrases(audio_file, original, language='en', gap=0.2):
	groups = group_phrases(original, gap)
	result = {'words': [], 'display_words': [], 'scores': [], 'phrase_ids': [], 'warnings': []}
	if not groups:
		return result

	def append(group, scores, phrase_id):
		result['words'].extend(group)
		result['display_words'].extend(continuous_phrase(group))
		result['scores'].extend(scores)
		result['phrase_ids'].extend([phrase_id] * len(group))

	def fallback(group, phrase_id, reason):
		message = f'Phrase {phrase_id}: {reason}; using continuous Whisper timings.'
		result['warnings'].append(message)
		warnings.warn(message, UserWarning)
		append(group, [None] * len(group), phrase_id)

	if language != 'en':
		for phrase_id, group in enumerate(groups, 1):
			fallback(group, phrase_id, 'alignment model supports English only')
		return result

	# Validate text before downloading/loading a model that may not be usable.
	labels = tuple("-|ABCDEFGHIJKLMNOPQRSTUVWXYZ'")
	eligible = []
	for group in groups:
		try:
			encode_transcript([word[0] for word in group], labels)
			eligible.append(True)
		except ValueError:
			eligible.append(False)
	if not any(eligible):
		for phrase_id, group in enumerate(groups, 1):
			fallback(group, phrase_id, 'unsupported transcript characters')
		return result

	model, bundle = get_alignment_model()
	audio = decode_audio(audio_file, bundle.sample_rate)
	windows = phrase_windows(groups, len(audio) / bundle.sample_rate)
	for phrase_id, (group, window, supported) in enumerate(zip(groups, windows, eligible), 1):
		start, end = window
		print('Aligning phrase', phrase_id, 'of', len(groups), flush=True)
		if not supported:
			fallback(group, phrase_id, 'unsupported transcript characters')
			continue
		# Bound transformer attention memory without splitting words arbitrarily.
		if end - start > 30:
			fallback(group, phrase_id, 'phrase exceeds the 30-second alignment limit')
			continue
		first = int(start * bundle.sample_rate)
		last = int(end * bundle.sample_rate)
		if last - first < 400:
			fallback(group, phrase_id, 'audio window is too short for alignment')
			continue
		words, scores = align_phrase(audio[first:last], [word[0] for word in group],
			first / bundle.sample_rate, model, bundle)
		append(words, scores, phrase_id)
	return result
