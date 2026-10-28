import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from capcut_assets import AssetPicker, MEME_EXTENSIONS, scan_library
from capcut_generator import generate_project, project_hashes, read_json, write_json
from test_capcut_generator import fixture


class AutomaticAssetsTests(unittest.TestCase):
	def test_selection_matches_names_and_limits_repetition(self):
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			for name in ('phone.gif', 'dance.gif', 'notes.txt'):
				(root / name).write_bytes(b'test')
			paths = scan_library(root, MEME_EXTENSIONS)
			self.assertEqual(len(paths), 2)
			picker = AssetPicker(paths, root)
			self.assertEqual(picker.choose('phone calling').name, 'phone.gif')
			self.assertEqual(picker.choose('phone calling').name, 'dance.gif')

	def test_empty_library_is_rejected(self):
		with tempfile.TemporaryDirectory() as directory:
			with self.assertRaisesRegex(ValueError, 'No supported'):
				scan_library(directory, MEME_EXTENSIONS)

	def test_automatic_export_has_no_captions_or_transcription(self):
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			source = root / 'reference'
			source.mkdir()
			memes = root / 'memes'
			sounds = root / 'voices'
			memes.mkdir()
			sounds.mkdir()
			(memes / 'phone.mp4').write_bytes(b'meme')
			(sounds / 'phone.wav').write_bytes(b'sound')
			drawing = root / 'drawing.mp4'
			drawing.write_bytes(b'drawing')
			draft = fixture()
			overlay = copy.deepcopy(draft['tracks'][0])
			overlay['segments'] = [overlay['segments'][0]]
			overlay['segments'][0]['id'] = 'overlay'
			sound = copy.deepcopy(draft['tracks'][1])
			sound['segments'][0]['id'] = 'effect'
			draft['tracks'].extend([overlay, sound])
			write_json(source / 'draft_content.json', draft)
			write_json(source / 'draft_meta_info.json', {'draft_name': 'reference', 'draft_id': 'original'})
			before = project_hashes(source)
			captioner = Mock(side_effect=AssertionError('Must not transcribe'))
			with patch('capcut_generator.probe_media', return_value={'duration': 1000000, 'width': 64, 'height': 96}), patch(
				'capcut_generator.save_freeze', side_effect=lambda v, t, p: Path(p).write_bytes(b'freeze')):
				out, warnings = generate_project(source, drawing, {}, 0, 1, None, 'auto',
					progress=lambda _: None, captioner=captioner, automatic=True,
					meme_folder=memes, sound_folder=sounds, topic='phone')
			captioner.assert_not_called()
			self.assertEqual(before, project_hashes(source))
			result = read_json(out / 'draft_content.json')
			self.assertEqual(result['tracks'][2]['segments'], [])
			materials = {m['id']: m for m in result['materials']['audios']}
			joke = materials[result['tracks'][1]['segments'][0]['material_id']]
			self.assertIn('JOKE 01', joke['name'])
			with wave.open(joke['path'], 'rb') as audio:
				self.assertEqual(audio.getnframes(), 32000)
				self.assertFalse(any(audio.readframes(32000)))
			self.assertEqual(result['tracks'][4]['segments'][0]['speed'], 1.0)
			self.assertEqual(result['tracks'][4]['segments'][0]['target_timerange']['duration'], 1000000)
			self.assertTrue(any('filenames' in warning for warning in warnings))


if __name__ == '__main__':
	unittest.main()
