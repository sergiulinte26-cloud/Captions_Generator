import copy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

import pysrt

from capcut_generator import (
	drawing_source_map, fit_captions, generate_project, inspect_reference, project_hashes,
	read_json, replace_captions, save_freeze, validate_selection, write_json,
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
	def test_drawing_source_path_aliases_reuse_interval(self):
		draft = fixture()
		original = draft['materials']['videos'][0]
		original['path'] = 'C:/Drawing/old.mp4'
		alias = dict(original, id='alias', path='c:\\drawing\\OLD.mp4')
		draft['materials']['videos'].append(alias)
		segment = copy.deepcopy(draft['tracks'][0]['segments'][0])
		segment.update(id='repeat', material_id='alias')
		segment['target_timerange']['start'] = 2000000
		draft['tracks'][0]['segments'].append(segment)
		sources, total = drawing_source_map(draft, 0)
		self.assertEqual(total, 2000000)
		self.assertIs(sources['video'], sources['alias'])

	def test_drawing_source_validation(self):
		for path in ('', None):
			with self.subTest(path=path):
				draft = fixture()
				draft['materials']['videos'][0]['path'] = path
				with self.assertRaisesRegex(ValueError, 'video file'):
					validate_selection(draft, 0, 1, None, {}, automatic=True)
		for start, duration in ((-1, 1000000), (0, float('nan')), (2000000, 1), (0, 2100000)):
			with self.subTest(start=start, duration=duration):
				draft = fixture()
				draft['tracks'][0]['segments'][0]['source_timerange'] = {'start': start, 'duration': duration}
				with self.assertRaisesRegex(ValueError, 'source range'):
					drawing_source_map(draft, 0)
		draft = fixture()
		draft['materials']['videos'][1]['freeze']['source_material_id'] = 'missing'
		with self.assertRaisesRegex(ValueError, 'source video reference'):
			drawing_source_map(draft, 0)

	def test_multiple_sources_preserve_timeline_and_freeze_origins(self):
		draft = fixture()
		durations = [20900000, 19300000, 19300000, 16366666]
		segments = []
		materials = []
		offset = 0
		expected_ranges = []
		expected_freezes = []
		ratio = 90000000 / sum(durations)
		for index, duration in enumerate(durations):
			video = dict(draft['materials']['videos'][0], id=f'video{index}', duration=duration, path=f'old{index}.mp4')
			freeze = copy.deepcopy(draft['materials']['videos'][1])
			freeze['id'] = f'freeze{index}'
			extra = 16514 if index == 1 else 0
			freeze['freeze'].update(source_material_id=video['id'], source_material_path=video['path'], timestamp=duration + extra)
			moving = copy.deepcopy(draft['tracks'][0]['segments'][0])
			moving.update(id=f'moving{index}', material_id=video['id'])
			moving['target_timerange']['start'] = index * 2000000
			moving['source_timerange'] = {'start': 100000, 'duration': duration + extra - 100000}
			moving['common_keyframes'] = [{'property_type': 'KFTypeScaleX', 'keyframe_list': [
				{'time_offset': 100000, 'values': [1.0]}, {'time_offset': duration + extra, 'values': [1.5]}]}]
			still = copy.deepcopy(draft['tracks'][0]['segments'][1])
			still.update(id=f'still{index}', material_id=freeze['id'])
			still['target_timerange']['start'] = index * 2000000 + 1000000
			segments.extend([moving, still])
			materials.extend([video, freeze])
			first = round((offset + 100000) * ratio)
			last = round((offset + duration) * ratio)
			expected_ranges.append((first, last))
			expected_freezes.append(last - 1)
			offset += duration
		draft['tracks'][0]['segments'] = segments
		draft['materials']['videos'] = materials
		draft['duration'] = 8000000
		validate_selection(draft, 0, 1, None, {}, automatic=True)
		with tempfile.TemporaryDirectory() as temporary:
			root = Path(temporary)
			source = root / 'reference'
			source.mkdir()
			write_json(source / 'draft_content.json', draft)
			write_json(source / 'draft_meta_info.json', {'draft_id': 'original'})
			before = project_hashes(source)
			media = root / 'new.mp4'
			media.write_bytes(b'media')
			def freeze(video, timestamp, path):
				Path(path).write_bytes(b'freeze')
			with patch('capcut_generator.probe_media', return_value={'duration': 90000000, 'width': 1080, 'height': 1920}), patch(
				'capcut_generator.save_freeze', side_effect=freeze) as save:
				out, _ = generate_project(source, media, {'a1': media}, 0, 1, 2, 'generated', progress=lambda _: None, captioner=captioner)
			self.assertEqual([call.args[1] for call in save.call_args_list], expected_freezes)
			result = read_json(out / 'draft_content.json')
			self.assertEqual(before, project_hashes(source))
			self.assertEqual(result['duration'], draft['duration'])
			active = {m['id']: m for m in result['materials']['videos']}
			generated = result['tracks'][0]['segments']
			self.assertEqual([s['target_timerange'] for s in generated], [s['target_timerange'] for s in segments])
			for index, (first, last) in enumerate(expected_ranges):
				moving, still = generated[index * 2:index * 2 + 2]
				self.assertEqual(moving['source_timerange'], {'start': first, 'duration': last - first})
				self.assertEqual(moving['speed'], (last - first) / 1000000)
				self.assertEqual([k['time_offset'] for k in moving['common_keyframes'][0]['keyframe_list']], [first, last])
				self.assertEqual(active[still['material_id']]['freeze']['source_material_id'], moving['material_id'])

	def test_freeze_accepts_padded_rgb_rows(self):
		import numpy as np
		from PySide6.QtGui import QImage

		pixels = np.zeros((4, 8, 3), dtype=np.uint8)[:, :5, :]
		pixels[:] = [12, 34, 56]
		self.assertFalse(pixels.flags.c_contiguous)
		frame = Mock(pts=0)
		frame.to_ndarray.return_value = pixels
		container = MagicMock()
		container.__enter__.return_value = container
		container.streams.video = [SimpleNamespace(start_time=0, time_base=1)]
		container.decode.return_value = iter([frame])
		with tempfile.TemporaryDirectory() as directory, patch('av.open', return_value=container):
			output = Path(directory) / 'freeze.png'
			save_freeze('unused.mp4', 0, output)
			image = QImage(str(output))
			self.assertEqual((image.width(), image.height()), (5, 4))
			self.assertEqual(image.pixelColor(4, 3).getRgb(), (12, 34, 56, 255))

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
