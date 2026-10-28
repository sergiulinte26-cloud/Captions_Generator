"""Template-based CapCut draft generation. Never edits the reference project."""

import copy
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re
import shutil
import tempfile
import uuid


def read_json(path):
	return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
	Path(path).write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


def new_id():
	return str(uuid.uuid4()).upper()


def inspect_reference(folder):
	folder = Path(folder)
	draft = read_json(folder / 'draft_content.json')
	read_json(folder / 'draft_meta_info.json')
	if not isinstance(draft.get('tracks'), list) or not isinstance(draft.get('materials'), dict):
		raise ValueError('This is not a supported readable CapCut draft.')
	fps = float(draft.get('fps', 30))
	if not math.isfinite(fps) or not 1 <= fps <= 120:
		raise ValueError('Unsupported project frame rate.')
	materials = {m['id']: m for values in draft['materials'].values() if isinstance(values, list)
		for m in values if isinstance(m, dict) and 'id' in m}
	tracks = []
	for index, track in enumerate(draft['tracks']):
		if track.get('type') not in ('video', 'audio', 'text') or not track.get('segments'):
			continue
		slots = []
		for segment in sorted(track['segments'], key=lambda s: s['target_timerange']['start']):
			material = materials.get(segment['material_id'], {})
			label = material.get('name') or material.get('material_name') or PureWindowsPath(material.get('path', '')).name
			slots.append({'id': segment['id'], 'label': label or material.get('type', 'clip'),
				'start': segment['target_timerange']['start'], 'duration': segment['target_timerange']['duration']})
		tracks.append({'index': index, 'type': track['type'], 'slots': slots})
	return draft, tracks


def validate_selection(draft, video_track, audio_track, text_track, replacements, automatic=False):
	materials = draft['materials']
	videos = {m['id']: m for m in materials.get('videos', [])}
	speeds = {m['id']: m for m in materials.get('speeds', [])}
	selections = [(video_track, 'video'), (audio_track, 'audio')]
	if not automatic:
		selections.append((text_track, 'text'))
	for index, kind in selections:
		if not 0 <= index < len(draft['tracks']) or draft['tracks'][index]['type'] != kind:
			raise ValueError('Select valid drawing, voiceover and caption tracks.')
		segments = sorted(draft['tracks'][index]['segments'], key=lambda s: s['target_timerange']['start'])
		if not segments:
			raise ValueError('Selected tracks must not be empty.')
		previous_end = 0
		for segment in segments:
			time = segment['target_timerange']
			if time['start'] < previous_end or time['duration'] <= 0:
				raise ValueError('Selected tracks must have positive, nonoverlapping segments.')
			previous_end = time['start'] + time['duration']
			if kind != 'text':
				for reference in segment.get('extra_material_refs', []):
					if reference in speeds and speeds[reference].get('curve_speed'):
						raise ValueError('Curve-speed clips are not supported in this first version.')
				if segment.get('reverse'):
					raise ValueError('Reverse playback is not supported on replacement tracks.')
	video_segments = draft['tracks'][video_track]['segments']
	paths = {videos[s['material_id']].get('path') for s in video_segments
		if videos[s['material_id']].get('type') == 'video'}
	if len(paths) != 1:
		raise ValueError('Drawing track must use one source video plus optional freeze images.')
	for segment in video_segments:
		material = videos[segment['material_id']]
		if material.get('type') == 'photo' and not material.get('freeze'):
			raise ValueError('Drawing track contains a still image that is not a freeze frame.')
		if material.get('type') not in ('photo', 'video'):
			raise ValueError('Unsupported drawing material.')
		if material.get('type') == 'video' and (material.get('duration', 0) <= 0 or not segment.get('source_timerange')):
			raise ValueError('Drawing material is missing its source duration.')
	if automatic:
		return
	if set(replacements) != {s['id'] for s in draft['tracks'][audio_track]['segments']}:
		raise ValueError('Choose one replacement audio file for every voiceover slot.')
	text_id = draft['tracks'][text_track]['segments'][0]['material_id']
	text = next(m for m in materials['texts'] if m['id'] == text_id)
	content = json.loads(text['content'])
	if not content.get('text') or len(content.get('styles', [])) != 1:
		raise ValueError('Choose a caption track with a single uniform text style.')


def set_speed(draft, segment, speed):
	if not math.isfinite(speed) or speed <= 0:
		raise ValueError('Invalid replacement playback speed.')
	segment['speed'] = speed
	speeds = draft['materials'].setdefault('speeds', [])
	ids = {m['id'] for m in speeds}
	segment['extra_material_refs'] = [i for i in segment.get('extra_material_refs', []) if i not in ids]
	material = {'id': new_id(), 'type': 'speed', 'mode': 0, 'speed': speed, 'curve_speed': None}
	speeds.append(material)
	segment['extra_material_refs'].append(material['id'])


def replace_material(draft, kind, segment, updates):
	items = draft['materials'][kind]
	old = next(m for m in items if m['id'] == segment['material_id'])
	material = copy.deepcopy(old)
	material.update(updates)
	material['id'] = new_id()
	if 'local_material_id' in material:
		material['local_material_id'] = ''
	if 'unique_id' in material:
		material['unique_id'] = new_id()
	items.append(material)
	segment['material_id'] = material['id']
	return material


def replace_captions(draft, text_track, captions):
	track = draft['tracks'][text_track]
	template_segment = copy.deepcopy(track['segments'][0])
	template = next(m for m in draft['materials']['texts'] if m['id'] == template_segment['material_id'])
	new_segments = []
	for text, start, end in captions:
		material = copy.deepcopy(template)
		material['id'] = new_id()
		content = json.loads(material['content'])
		content['text'] = text
		content['styles'][0]['range'] = [0, len(text.encode('utf-16-le')) // 2]
		material['content'] = json.dumps(content, ensure_ascii=False, separators=(',', ':'))
		for key in ('base_content', 'recognize_text', 'recognize_task_id'):
			if key in material:
				material[key] = ''
		for key in ('words', 'current_words'):
			if key in material:
				material[key] = {'start_time': [], 'end_time': [], 'text': []}
		draft['materials']['texts'].append(material)
		segment = copy.deepcopy(template_segment)
		segment.update(id=new_id(), material_id=material['id'],
			target_timerange={'start': start, 'duration': end - start}, source_timerange=None,
			extra_material_refs=[], common_keyframes=[], keyframe_refs=[], group_id='')
		new_segments.append(segment)
	track['segments'] = new_segments


def project_hashes(folder):
	result = {}
	for path in Path(folder).rglob('*'):
		if path.is_file():
			with path.open('rb') as stream:
				digest = hashlib.sha256()
				for block in iter(lambda: stream.read(1024 * 1024), b''):
					digest.update(block)
			result[path.relative_to(folder)] = digest.hexdigest()
	return result


def probe_media(path, kind):
	import av
	with av.open(str(path)) as container:
		streams = [s for s in container.streams if s.type == kind]
		if not streams:
			raise ValueError(f'{path} has no {kind} stream.')
		stream = streams[0]
		duration = round(float(stream.duration * stream.time_base) * 1e6) if stream.duration is not None else container.duration
		if not duration or duration <= 0:
			raise ValueError(f'Cannot determine duration of {path}.')
		return {'duration': duration, 'width': getattr(stream, 'width', 0),
			'height': getattr(stream, 'height', 0)}


def save_freeze(video, timestamp, output):
	import av
	import numpy as np
	from PySide6.QtGui import QImage
	with av.open(str(video)) as container:
		stream = container.streams.video[0]
		start = stream.start_time or 0
		container.seek(max(start, start + int(timestamp / 1e6 / float(stream.time_base))), stream=stream)
		selected = None
		for frame in container.decode(stream):
			selected = frame
			if frame.pts is not None and float((frame.pts - start) * stream.time_base) >= timestamp / 1e6:
				break
		if selected is None:
			raise ValueError('Could not decode replacement freeze frame.')
		pixels = np.ascontiguousarray(selected.to_ndarray(format='rgb24'))
		image = QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QImage.Format.Format_RGB888)
		if not image.save(str(output), 'PNG'):
			raise ValueError('Could not save replacement freeze frame.')


def remap_paths(value, roots, destination):
	if isinstance(value, dict):
		return {key: remap_paths(item, roots, destination) for key, item in value.items()}
	if isinstance(value, list):
		return [remap_paths(item, roots, destination) for item in value]
	if isinstance(value, str):
		normalized = value.replace('\\', '/')
		for root in roots:
			if normalized.lower().startswith(root.lower().rstrip('/') + '/'):
				return destination + normalized[len(root.rstrip('/')):]
	return value


def fit_captions(subs, slot, audio_duration, fps):
	from subtitle_timing import align_words_to_frames
	start = slot['start']
	end = start + slot['duration']
	factor = slot['duration'] / audio_duration
	words = [(sub.text, (start + sub.start.ordinal * 1000 * factor) / 1e6,
		(start + sub.end.ordinal * 1000 * factor) / 1e6) for sub in subs]
	result = []
	for text, first, last in align_words_to_frames(words, fps):
		first = max(start, first * 1000)
		last = min(end, last * 1000)
		if last <= first:
			raise ValueError('A caption cannot fit its audio slot; use a shorter voiceover or a longer template slot.')
		result.append((text, first, last))
	return result


def generate_project(reference, drawing, replacements, video_track, audio_track, text_track,
		project_name, progress=print, captioner=None, automatic=False, meme_folder=None, sound_folder=None, topic=''):
	import pysrt

	reference = Path(reference).resolve()
	drawing = Path(drawing).resolve()
	if not project_name.strip() or project_name != project_name.strip() or re.search(r'[<>:"/\\|?*\x00-\x1f]', project_name) or project_name.endswith('.'):
		raise ValueError('Use a simple new project name without path separators or reserved characters.')
	if project_name in ('.', '..') or project_name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
		raise ValueError('That project name is reserved by Windows.')
	target = reference.parent / project_name
	if target.exists():
		raise ValueError('A project with that name already exists. Choose a new name.')
	if any(p.is_symlink() for p in reference.rglob('*')):
		raise ValueError('Reference contains symbolic links; use a normal local project copy.')
	draft, _ = inspect_reference(reference)
	validate_selection(draft, video_track, audio_track, text_track, replacements, automatic=automatic)
	if automatic:
		from capcut_assets import scan_library, MEME_EXTENSIONS, SOUND_EXTENSIONS
		scan_library(meme_folder, MEME_EXTENSIONS)
		scan_library(sound_folder, SOUND_EXTENSIONS)
	replacements = {key: Path(value).resolve() for key, value in replacements.items()}
	if not drawing.is_file() or any(not p.is_file() for p in replacements.values()):
		raise ValueError('A replacement media file does not exist.')
	video_info = probe_media(drawing, 'video')
	audio_info = {key: probe_media(path, 'audio') for key, path in replacements.items()}
	before = project_hashes(reference)
	warnings = ['Template duration, zooms, memes, effects and other sounds are retained. Review framing and playback speeds in CapCut.',
		'Caption font and outline are retained; per-word animations are removed to avoid hiding short words.']
	if automatic:
		warnings = ['Template pacing, cuts, zooms and reference effects are retained. Review the new draft in CapCut.']
	if captioner is None and not automatic:
		from transcriber import generate_srt
		captioner = generate_srt
	metadata = read_json(reference / 'draft_meta_info.json')
	old_root = metadata.get('draft_fold_path', '').replace('\\', '/').rstrip('/')
	roots = [str(reference).replace('\\', '/')]
	if old_root:
		roots.append(old_root)
	fps = float(draft.get('fps', 30))
	with tempfile.TemporaryDirectory(prefix='.caption-draft-', dir=reference.parent) as temporary:
		stage = Path(temporary) / 'project'
		progress('Copying reference project...')
		shutil.copytree(reference, stage)
		assets_name = 'generator_media_' + uuid.uuid4().hex[:8]
		assets = stage / assets_name
		assets.mkdir()
		final_assets = target / assets_name
		video_copy = assets / ('drawing' + drawing.suffix.lower())
		shutil.copy2(drawing, video_copy)
		final_video = (final_assets / video_copy.name).as_posix()
		videos = {m['id']: copy.deepcopy(m) for m in draft['materials']['videos']}
		for index, segment in enumerate(draft['tracks'][video_track]['segments']):
			original = videos[segment['material_id']]
			updates = {'path': final_video, 'width': video_info['width'], 'height': video_info['height'],
				'material_name': drawing.name}
			if original['type'] == 'video':
				ratio = video_info['duration'] / original['duration']
				source = segment['source_timerange']
				first = round(source['start'] * ratio)
				last = min(video_info['duration'], round((source['start'] + source['duration']) * ratio))
				if first < 0 or last <= first:
					raise ValueError('Drawing source range falls outside replacement video.')
				segment['source_timerange'] = {'start': first, 'duration': last - first}
				set_speed(draft, segment, (last - first) / segment['target_timerange']['duration'])
				updates['duration'] = video_info['duration']
			else:
				freeze = copy.deepcopy(original['freeze'])
				source_video = videos.get(freeze.get('source_material_id'))
				if not source_video or source_video.get('duration', 0) <= 0:
					raise ValueError('Freeze frame has no valid source video reference.')
				timestamp = min(video_info['duration'] - 1, max(0, round(freeze['timestamp'] * video_info['duration'] / source_video['duration'])))
				progress(f'Creating freeze frame {index + 1}...')
				image_name = f'freeze_{index}.png'
				save_freeze(video_copy, timestamp, assets / image_name)
				freeze.update(timestamp=timestamp, source_material_path=final_video, reverse_material_path='')
				updates.update(path=(final_assets / image_name).as_posix(), freeze=freeze, material_name='Freeze')
			replace_material(draft, 'videos', segment, updates)
		# Freeze metadata must refer to a replacement source, not to the old drawing.
		active_videos = {m['id']: m for m in draft['materials']['videos']}
		new_video_id = next(s['material_id'] for s in draft['tracks'][video_track]['segments'] if active_videos[s['material_id']]['type'] == 'video')
		for segment in draft['tracks'][video_track]['segments']:
			material = active_videos[segment['material_id']]
			if material.get('freeze'):
				material['freeze']['source_material_id'] = new_video_id
		if automatic:
			from capcut_assets import assemble_automatic
			assemble_automatic(draft, video_track, audio_track, assets, final_assets,
				meme_folder, sound_folder, topic or drawing.stem, progress, warnings)
		captions = []
		voice_segments = [] if automatic else draft['tracks'][audio_track]['segments']
		for index, segment in enumerate(sorted(voice_segments, key=lambda s: s['target_timerange']['start'])):
			path = replacements[segment['id']]
			info = audio_info[segment['id']]
			local = assets / (f'voice_{index:03d}' + path.suffix.lower())
			shutil.copy2(path, local)
			progress(f'Generating captions for voiceover {index + 1}...')
			srt = captioner(str(local), f'voice_{index:03d}', on_warning=warnings.append)
			subs = pysrt.open(str(srt), encoding='utf-8-sig')
			if not subs:
				raise ValueError(f'No speech captions found in {path.name}; check the selected voiceover.')
			captions.extend(fit_captions(subs, segment['target_timerange'], info['duration'], fps))
			speed = info['duration'] / segment['target_timerange']['duration']
			if not 0.75 <= speed <= 1.35:
				warnings.append(f'Voiceover {index + 1} is fitted at {speed:.2f}x speed; review its pacing.')
			replace_material(draft, 'audios', segment, {'path': (final_assets / local.name).as_posix(),
				'name': path.name, 'duration': info['duration'], 'wave_points': [], 'type': 'extract_music',
				'music_id': '', 'resource_id': '', 'effect_id': '', 'text_id': ''})
			segment.update(source_timerange={'start': 0, 'duration': info['duration']},
				common_keyframes=[], keyframe_refs=[], is_tone_modify=True)
			set_speed(draft, segment, speed)
		captions.sort(key=lambda c: c[1])
		if any(a[2] > b[1] for a, b in zip(captions, captions[1:])):
			raise ValueError('Generated captions overlap after fitting voiceovers.')
		if not automatic:
			replace_captions(draft, text_track, captions)
		draft = remap_paths(draft, roots, target.as_posix())
		for path in stage.rglob('*'):
			if not path.is_file() or path.suffix not in ('.json', '.bak', '.tmp'):
				continue
			try:
				data = read_json(path)
			except (UnicodeError, ValueError):
				continue
			if isinstance(data, dict) and data.get('id') == draft.get('id') and isinstance(data.get('tracks'), list):
				data = draft
			else:
				data = remap_paths(data, roots, target.as_posix())
			write_json(path, data)
		write_json(stage / 'draft_content.json', draft)
		metadata = remap_paths(metadata, roots, target.as_posix())
		metadata.update(draft_name=project_name, draft_id=new_id(), draft_fold_path=target.as_posix(),
			draft_root_path=target.parent.as_posix())
		write_json(stage / 'draft_meta_info.json', metadata)
		used_ids = {s['material_id'] for t in draft['tracks'] for s in t['segments']}
		for kind in ('videos', 'audios', 'stickers'):
			for material in draft['materials'].get(kind, []):
				path = material.get('path', '')
				if material['id'] in used_ids and path and not path.startswith('##_draftpath_') and not path.startswith(target.as_posix() + '/') and not Path(path).exists():
					warnings.append('Inherited media not found on this computer: ' + path)
		progress('Verifying reference and publishing new project...')
		if project_hashes(reference) != before:
			raise ValueError('Reference changed during generation. Close CapCut and try again.')
		if target.exists():
			raise ValueError('Destination already exists; refusing to overwrite it.')
		stage.rename(target)
	return target, list(dict.fromkeys(warnings))
