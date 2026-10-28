import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pysrt

from capcut_generator import (
	fit_captions, generate_project, inspect_reference, project_hashes,
	read_json, replace_captions, validate_selection, write_json,
)


def fixture():
	def segment(identifier, material, start, duration):
		return {'id': identifier, 'material_id': material,
			'target_timerange': {'start': start, 'duration': duration},
			'source_timerange': {'start': 0, 'duration': duration}, 'extra_material_refs': [],
			'speed': 1.0, 'common_keyframes': [], 'keyframe_refs': []}
	video = segment('v1', 'video', 0, 1000000)
	freeze = segment('v2', 'freeze', 1000000, 1000000)
	voice = segment('a1', 'audio', 0, 2000000)
	caption = segment('t1', 'text', 0, 1000000)
	return {'id': 'timeline', 'fps': 30, 'duration': 2000000, 'tracks': [
		{'type': 'video', 'segments': [video, freeze]},
		{'type': 'audio', 'segments': [voice]},
		{'type': 'text', 'segments': [caption]}], 'materials': {
		'videos': [{'id': 'video', 'type': 'video', 'duration': 2000000, 'path': 'old.mp4'},
			{'id': 'freeze', 'type': 'photo', 'path': 'old.png', 'freeze': {
				'source_material_id': 'video', 'source_material_path': 'old.mp4', 'timestamp': 1000000}}],
		'audios': [{'id': 'audio', 'type': 'extract_music', 'path': 'old.mp3', 'duration': 2000000}],
		'texts': [{'id': 'text', 'content': json.dumps({'text': 'OLD', 'styles': [{'range': [0, 3]}]})}],
		'speeds': []}}


def captioner(audio, name, on_warning=None):
	path = Path(audio).with_name(name + '.srt')
	subs = pysrt.SubRipFile([
		pysrt.SubRipItem(index=1, text='A', start=pysrt.SubRipTime(milliseconds=0), end=pysrt.SubRipTime(milliseconds=500)),
		pysrt.SubRipItem(index=2, text='PIG', start=pysrt.SubRipTime(milliseconds=500), end=pysrt.SubRipTime(milliseconds=1000)),
	])
	subs.save(str(path), encoding='utf-8')
	return str(path)


class CapCutGeneratorTests(unittest.TestCase):
	def test_selection_requires_all_audio_slots(self):
		with self.assertRaisesRegex(ValueError, 'every voiceover slot'):
			validate_selection(fixture(), 0, 1, 2, {})

	def test_rejects_reverse_and_curve_speed(self):
		draft = fixture()
		draft['tracks'][0]['segments'][0]['reverse'] = True
		with self.assertRaisesRegex(ValueError, 'Reverse'):
			validate_selection(draft, 0, 1, 2, {'a1': 'a.mp3'})
		draft['tracks'][0]['segments'][0]['reverse'] = False
		draft['materials']['speeds'] = [{'id': 'speed', 'curve_speed': {'points': [1]}}]
		draft['tracks'][0]['segments'][0]['extra_material_refs'] = ['speed']
		with self.assertRaisesRegex(ValueError, 'Curve-speed'):
			validate_selection(draft, 0, 1, 2, {'a1': 'a.mp3'})

	def test_caption_style_and_short_words_preserved(self):
		draft = fixture()
		replace_captions(draft, 2, [('A', 0, 33333), ('TEST', 33333, 100000)])
		materials = {m['id']: m for m in draft['materials']['texts']}
		segments = draft['tracks'][2]['segments']
		self.assertEqual([json.loads(materials[s['material_id']]['content'])['text'] for s in segments], ['A', 'TEST'])
		self.assertEqual(json.loads(materials[segments[0]['material_id']]['content'])['styles'][0]['range'], [0, 1])
		self.assertEqual(segments[0]['extra_material_refs'], [])

	def test_caption_scaling_stays_in_slot(self):
		subs = pysrt.SubRipFile([pysrt.SubRipItem(index=1, text='A', start=pysrt.SubRipTime(milliseconds=0), end=pysrt.SubRipTime(milliseconds=500)),
			pysrt.SubRipItem(index=2, text='B', start=pysrt.SubRipTime(milliseconds=500), end=pysrt.SubRipTime(milliseconds=1000))])
		rows = fit_captions(subs, {'start': 1000000, 'duration': 2000000}, 1000000, 30)
		self.assertEqual(rows, [('A', 1000000, 2000000), ('B', 2000000, 3000000)])

	def test_project_publishing_and_overwrite_protection(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / 'reference'
			source.mkdir()
			draft = fixture()
			write_json(source / 'draft_content.json', draft)
			write_json(source / 'draft_meta_info.json', {'draft_id': 'original', 'draft_name': 'reference', 'draft_fold_path': source.as_posix()})
			nested = source / 'Timelines' / 'timeline'
			nested.mkdir(parents=True)
			write_json(nested / 'draft_content.json', draft)
			write_json(source / 'draft_content.json.bak', draft)
			before = project_hashes(source)
			video = root / 'new.mp4'
			audio = root / 'new.wav'
			video.write_bytes(b'video')
			audio.write_bytes(b'audio')
			def probe(path, kind):
				return {'duration': 4000000 if kind == 'video' else 1000000, 'width': 100, 'height': 200}
			def freeze(video, timestamp, path):
				self.assertEqual(timestamp, 2000000)
				Path(path).write_bytes(b'new freeze')
			with patch('capcut_generator.probe_media', side_effect=probe), patch('capcut_generator.save_freeze', side_effect=freeze):
				out, warnings = generate_project(source, video, {'a1': audio}, 0, 1, 2, 'generated', progress=lambda _: None, captioner=captioner)
			self.assertEqual(before, project_hashes(source))
			result = read_json(out / 'draft_content.json')
			self.assertEqual(result, read_json(out / 'Timelines' / 'timeline' / 'draft_content.json'))
			self.assertEqual(result, read_json(out / 'draft_content.json.bak'))
			self.assertNotEqual(read_json(out / 'draft_meta_info.json')['draft_id'], 'original')
			self.assertEqual(result['tracks'][0]['segments'][0]['speed'], 2.0)
			self.assertEqual(result['tracks'][1]['segments'][0]['speed'], 0.5)
			self.assertEqual(result['duration'], draft['duration'])
			self.assertEqual(len(result['tracks'][2]['segments']), 2)
			active = {m['id']: m for m in result['materials']['videos']}
			for s in result['tracks'][0]['segments']:
				self.assertTrue(Path(active[s['material_id']]['path']).is_file())
			with self.assertRaisesRegex(ValueError, 'already exists'):
				generate_project(source, video, {'a1': audio}, 0, 1, 2, 'generated', captioner=captioner)

	def test_failed_generation_leaves_no_partial_project(self):
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / 'reference'
			source.mkdir()
			write_json(source / 'draft_content.json', fixture())
			write_json(source / 'draft_meta_info.json', {'draft_id': 'original'})
			media = root / 'media.mp4'
			media.write_bytes(b'media')
			before = project_hashes(source)
			with patch('capcut_generator.probe_media', return_value={'duration': 2000000, 'width': 2, 'height': 2}), patch(
				'capcut_generator.save_freeze', side_effect=ValueError('decode failed')):
				with self.assertRaisesRegex(ValueError, 'decode failed'):
					generate_project(source, media, {'a1': media}, 0, 1, 2, 'failed', progress=lambda _: None, captioner=captioner)
			self.assertFalse((root / 'failed').exists())
			self.assertFalse(list(root.glob('.caption-draft-*')))
			self.assertEqual(before, project_hashes(source))


if __name__ == '__main__':
	unittest.main()
