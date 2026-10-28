"""Create a separate local CapCut test project without archives or dependencies."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid


DEFAULT_SOURCE = Path(r'C:\Users\Denisa\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft\pig-test')


def hashes(root):
	return {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
		for p in root.rglob('*') if p.is_file()}


def read_json(path):
	return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, data):
	path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


def create_test(source, target):
	source = source.resolve()
	target = target.resolve()
	if target.exists() or source == target or source in target.parents or target in source.parents:
		raise ValueError('Destination must be a new folder outside the original project.')
	before = hashes(source)
	original = read_json(source / 'draft_content.json')
	metadata = read_json(source / 'draft_meta_info.json')
	segments = [segment for track in original['tracks'] if track['type'] == 'text'
		for segment in track['segments']]
	if not segments:
		raise ValueError('No caption segments found.')
	first = min(segments, key=lambda segment: segment['target_timerange']['start'])
	material_id = first['material_id']
	material = next(text for text in original['materials']['texts'] if text['id'] == material_id)
	if json.loads(material['content']).get('text') != "LET'S":
		raise ValueError("Expected the first caption to be LET'S. No project was created.")
	target.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.TemporaryDirectory(prefix='capcut-copy-', dir=target.parent) as temporary:
		stage = Path(temporary) / 'project'
		shutil.copytree(source, stage)
		changed = set()
		for path in stage.rglob('*'):
			if not path.is_file() or path.suffix not in ('.json', '.bak', '.tmp'):
				continue
			try:
				data = read_json(path)
			except (UnicodeError, ValueError):
				continue
			if not isinstance(data, dict) or not isinstance(data.get('materials'), dict):
				continue
			old = json.loads(json.dumps(data))
			modified = False
			for text in data['materials'].get('texts', []):
				if text.get('id') != material_id:
					continue
				content = json.loads(text['content'])
				if content.get('text') != "LET'S":
					continue
				content['text'] = 'TEST!'
				text['content'] = json.dumps(content, ensure_ascii=False, separators=(',', ':'))
				modified = True
			if modified:
				check = json.loads(json.dumps(data))
				for text in check['materials']['texts']:
					if text.get('id') == material_id:
						text['content'] = next(t['content'] for t in old['materials']['texts'] if t['id'] == material_id)
				if check != old:
					raise ValueError('Unexpected timeline change.')
				write_json(path, data)
				changed.add(path.relative_to(stage))
		if Path('draft_content.json') not in changed:
			raise ValueError('Main caption was not updated.')
		for path in (source / 'Timelines').glob('*/draft_content.json'):
			if read_json(path).get('id') == original.get('id') and path.relative_to(source) not in changed:
				raise ValueError('Active timeline copy was not updated.')
		old_folder = metadata.get('draft_fold_path', '').replace('\\', '/').rstrip('/')
		metadata['draft_name'] = target.name
		metadata['draft_id'] = str(uuid.uuid4()).upper()
		metadata['draft_fold_path'] = target.as_posix()
		metadata['draft_root_path'] = target.parent.as_posix()
		cover = metadata.get('draft_cover')
		if old_folder and isinstance(cover, str):
			metadata['draft_cover'] = cover.replace('\\', '/').replace(old_folder + '/', target.as_posix() + '/')
		write_json(stage / 'draft_meta_info.json', metadata)
		changed.add(Path('draft_meta_info.json'))
		after = hashes(stage)
		if set(before) != set(after) or {p for p in before if before[p] != after[p]} != changed:
			raise ValueError('Unexpected file changes in copy.')
		if hashes(source) != before:
			raise ValueError('Source changed during copying. Close CapCut and retry.')
		if target.exists():
			raise ValueError('Destination appeared during copying; refusing to replace it.')
		stage.rename(target)
	return target


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
	parser.add_argument('--output', type=Path, help='Defaults to pig-test-caption-check beside the original.')
	args = parser.parse_args()
	target = args.output or args.source.parent / 'pig-test-caption-check'
	print('Close CapCut before running this script. The original will not be edited.')
	try:
		result = create_test(args.source, target)
	except (OSError, ValueError, KeyError, StopIteration) as error:
		parser.exit(1, f'Could not create test project: {error}\n')
	print('Created:', result)
	print("First caption: LET'S -> TEST! Original files verified unchanged.")
	print('Reopen CapCut and look for', result.name)
	print('If it is not listed, do not overwrite the original; report the result.')


if __name__ == '__main__':
	main()
