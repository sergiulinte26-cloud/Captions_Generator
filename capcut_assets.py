"""Local, filename-based asset selection for editable rough cuts."""

from collections import Counter
from pathlib import Path, PureWindowsPath
import re
import shutil
import wave


MEME_EXTENSIONS = {'.mp4', '.mov', '.webm', '.gif', '.png', '.jpg', '.jpeg'}
SOUND_EXTENSIONS = {'.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac'}


def tokens(value):
	return {word for word in re.findall(r'[^\W_]+', str(value).lower())
		if len(word) > 2 and not word.isdigit() and word not in {'mp3', 'mp4', 'gif', 'wav', 'png', 'jpg', 'sound', 'effect', 'meme'}}


def scan_library(folder, extensions):
	root = Path(folder)
	if not root.is_dir():
		raise ValueError(f'Asset folder does not exist: {folder}')
	paths = sorted((p.resolve() for p in root.rglob('*') if p.is_file()
		and not p.is_symlink() and p.suffix.lower() in extensions), key=lambda p: str(p).lower())
	if not paths:
		raise ValueError(f'No supported media in {folder}')
	return paths


class AssetPicker:
	def __init__(self, paths, root):
		self.paths = paths
		self.root = Path(root).resolve()
		self.used = Counter()

	def choose(self, context):
		query = tokens(context)
		minimum = min(self.used[p] for p in self.paths)
		candidates = [p for p in self.paths if self.used[p] == minimum]
		best = min(candidates, key=lambda p: (-len(query & tokens(p.relative_to(self.root))), str(p).lower()))
		self.used[best] += 1
		return best


def write_silence(path, duration):
	frames = max(1, round(duration * 16000 / 1e6))
	with wave.open(str(path), 'wb') as stream:
		stream.setnchannels(1)
		stream.setsampwidth(2)
		stream.setframerate(16000)
		while frames:
			count = min(frames, 16000)
			stream.writeframesraw(b'\0\0' * count)
			frames -= count


def assemble_automatic(draft, video_track, audio_track, assets, final_assets,
		meme_folder, sound_folder, topic, progress, warnings):
	from capcut_generator import probe_media, replace_material, set_speed

	meme_picker = AssetPicker(scan_library(meme_folder, MEME_EXTENSIONS), meme_folder)
	sound_picker = AssetPicker(scan_library(sound_folder, SOUND_EXTENSIONS), sound_folder)
	lookup = {m['id']: m for values in draft['materials'].values() if isinstance(values, list)
		for m in values if isinstance(m, dict) and 'id' in m}
	copies = {}

	def copy_asset(path):
		if path not in copies:
			name = f'library_{len(copies):04d}{path.suffix.lower()}'
			shutil.copy2(path, assets / name)
			copies[path] = (final_assets / name).as_posix()
		return copies[path]

	for track_index, track in enumerate(draft['tracks']):
		kind = track['type']
		if kind == 'text':
			track['segments'] = []
			continue
		if kind == 'sticker':
			track['segments'] = []
			warnings.append('Reference stickers removed; local memes replace video overlays, not CapCut sticker assets.')
			continue
		if track_index == video_track:
			for segment in track['segments']:
				segment['volume'] = 0.0
			continue
		if kind not in ('video', 'audio'):
			continue
		kept = []
		for index, segment in enumerate(sorted(track['segments'], key=lambda s: s['target_timerange']['start'])):
			slot = segment['target_timerange']
			original = lookup.get(segment['material_id'], {})
			if track_index == audio_track:
				name = f'joke_{index + 1:02d}.wav'
				write_silence(assets / name, slot['duration'])
				label = f'JOKE {index + 1:02d} - add your line ({slot["duration"] / 1e6:.1f}s)'
				replace_material(draft, 'audios', segment, {'path': (final_assets / name).as_posix(),
					'name': label, 'duration': slot['duration'], 'wave_points': [], 'type': 'extract_music',
					'music_id': '', 'resource_id': '', 'effect_id': '', 'text_id': '', 'video_id': ''})
				segment.update(source_timerange={'start': 0, 'duration': slot['duration']},
					desc=label, common_keyframes=[], keyframe_refs=[], extra_material_refs=[], volume=1.0, reverse=False)
				set_speed(draft, segment, 1.0)
				progress(f'{label} at {slot["start"] / 1e6:.2f}s')
				kept.append(segment)
				continue
			picker = meme_picker if kind == 'video' else sound_picker
			context = f'{topic} {PureWindowsPath(original.get("path", "")).stem} {original.get("name", "")}'
			path = picker.choose(context)
			try:
				still = kind == 'video' and path.suffix.lower() in {'.png', '.jpg', '.jpeg'}
				if still:
					from PySide6.QtGui import QImageReader
					size = QImageReader(str(path)).size()
					if not size.isValid():
						raise ValueError('Unreadable image')
					info = {'duration': slot['duration'], 'width': size.width(), 'height': size.height()}
				else:
					info = probe_media(path, kind)
				final_path = copy_asset(path)
			except (OSError, ValueError, RuntimeError) as error:
				warnings.append(f'Skipped slot: could not read {path.name}: {error}')
				continue
			updates = {'path': final_path, 'duration': info['duration']}
			if kind == 'video':
				updates.update(type='photo' if still else 'video', width=info['width'], height=info['height'],
					material_name=path.name, freeze=None)
				segment['volume'] = 0.0
			else:
				updates.update(name=path.name, wave_points=[], type='extract_music', music_id='',
					resource_id='', effect_id='', text_id='', video_id='')
			replace_material(draft, 'videos' if kind == 'video' else 'audios', segment, updates)
			# Keep native speed. Short media leaves room rather than becoming slow-motion audio.
			duration = slot['duration'] if still else min(slot['duration'], info['duration'])
			segment.update(source_timerange={'start': 0, 'duration': duration},
				target_timerange={'start': slot['start'], 'duration': duration},
				common_keyframes=[], keyframe_refs=[], extra_material_refs=[], reverse=False, is_loop=False)
			set_speed(draft, segment, 1.0)
			progress(f'Auto-selected {path.name} at {slot["start"] / 1e6:.2f}s')
			kept.append(segment)
		track['segments'] = kept
	warnings.extend([
		'Automatic selection uses filenames/folder names and limited repetition, not visual or humor understanding.',
		'JOKE clips are silent placeholders in the original voiceover slots. Existing drawing freezes are retained; other joke slots may have moving footage.',
		'All reference text, speech, music and stickers are removed or replaced. Only reference effect tracks are reused; no CapCut catalog downloads.',
		'Memes and sounds use template positions; short files end early and long files are trimmed. Review volume, cropping and timing.'
	])
