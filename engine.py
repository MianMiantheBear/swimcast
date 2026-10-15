"""SwimCast task engine. No GUI or account configuration is required to import it."""
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import feedparser
import requests

APP_DIR = Path(os.path.abspath(__file__)).parent
USER_AGENT = 'SwimCast/3.0'
AUDIO_PROCESSING = {
    'compression_enabled': False, 'threshold_db': -28.0, 'ratio': 3.0,
    'attack_ms': 20.0, 'release_ms': 250.0, 'knee': 2.828427,
    'normalization_enabled': False, 'integrated_lufs': -14.0,
    'true_peak_dbtp': -2.0, 'loudness_range_lu': 7.0,
    'sample_rate': 44100, 'gain_db': 9.0, 'limiter_enabled': True,
    'limiter_ceiling_dbfs': -2.0, 'limiter_attack_ms': 5.0,
    'limiter_release_ms': 100.0,
}


class Stopped(Exception):
    pass


class RestartDownload(Exception):
    pass


class Control:
    def __init__(self, status=lambda key: None):
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.status = status

    def stop(self):
        self.stop_event.set()

    def pause(self):
        self.pause_event.set()
        self.status('pause_pending')

    def resume(self):
        self.pause_event.clear()
        self.status('running')

    def check_stop(self):
        if self.stop_event.is_set():
            raise Stopped()

    def checkpoint(self):
        self.check_stop()
        if self.pause_event.is_set():
            self.status('paused')
            while self.pause_event.is_set():
                if self.stop_event.wait(.1):
                    raise Stopped()
            self.status('running')
        self.check_stop()

    def delay(self, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.checkpoint()
            if self.stop_event.wait(.1):
                raise Stopped()


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return json.loads(json.dumps(default))
    # Do not silently discard a damaged existing history/configuration.
    with path.open(encoding='utf-8') as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError('Invalid JSON object: ' + str(path))
    return result


def save_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)


def safe_filename(value, max_length=140):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value)
    value = re.sub(r'\s+', ' ', value).strip(' .')[:max_length].rstrip()
    if value.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *('COM%d' % i for i in range(1, 10)), *('LPT%d' % i for i in range(1, 10))}:
        value = '_' + value
    return value or 'episode'


def find_audio_url(item):
    for part in item.get('enclosures', []) + item.get('links', []) + item.get('media_content', []):
        url = part.get('href') or part.get('url')
        kind = part.get('type', '')
        if url and (kind.startswith('audio/') or part.get('rel') == 'enclosure' or not kind):
            return url
    return None


def episode_key(item, audio_url):
    identity = item.get('id') or item.get('guid') or item.get('link') or audio_url or item.get('title', '')
    return hashlib.sha256(identity.encode('utf-8', errors='ignore')).hexdigest()


def duration_seconds(value):
    try:
        parts = str(value).strip().split(':')
        number = 0.0
        for part in parts:
            number = number * 60 + float(part)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


def ffmpeg_path():
    local = APP_DIR / 'ffmpeg.exe'
    return str(local) if local.is_file() else 'ffmpeg'


def run_process(command, control):
    # File-backed output prevents pipe-buffer deadlocks on long episodes.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while process.poll() is None:
                control.check_stop()
                control.stop_event.wait(.1)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        stdout.seek(0)
        stderr.seek(0)
        output = stdout.read().decode('utf-8', errors='replace')
        errors = stderr.read().decode('utf-8', errors='replace')
        if process.returncode:
            raise RuntimeError(errors[-4000:] or 'FFmpeg failed')
        return output, errors


def inspect_audio_details(path, control=None):
    """Decode the whole file, returning duration and nonfatal decoder diagnostics."""
    control = control or Control()
    output, errors = run_process([
        ffmpeg_path(), '-hide_banner', '-nostdin', '-v', 'error',
        '-i', str(path), '-map', '0:a:0', '-progress', 'pipe:1',
        '-f', 'null', '-',
    ], control)
    times = re.findall(r'^out_time_us=(\d+)$', output, re.MULTILINE)
    if not times or int(times[-1]) <= 0:
        raise RuntimeError('No decodable audio')
    return int(times[-1]) / 1_000_000, bool(errors.strip())


def inspect_audio(path, control=None):
    return inspect_audio_details(path, control)[0]


def atempo_filter(speed):
    speed = float(speed)
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError('Invalid playback speed')
    filters = []
    while speed > 2:
        filters.append('atempo=2.0')
        speed /= 2
    while speed < .5:
        filters.append('atempo=0.5')
        speed /= .5
    filters.append('atempo=%.6f' % speed)
    return ','.join(filters)


def audio_filter(speed, settings=None):
    settings = settings or AUDIO_PROCESSING
    filters = []
    if settings['compression_enabled']:
        filters.append('acompressor=threshold=%.8f:ratio=%s:attack=%s:release=%s:knee=%s:makeup=1:detection=rms:link=maximum' % (
            10 ** (settings['threshold_db'] / 20), settings['ratio'], settings['attack_ms'], settings['release_ms'], settings['knee']))
    filters.append(atempo_filter(speed))
    if settings['normalization_enabled']:
        filters.append('loudnorm=I=%s:TP=%s:LRA=%s:linear=false' % (
            settings['integrated_lufs'], settings['true_peak_dbtp'], settings['loudness_range_lu']))
        filters.append(r'aeval=exprs=if(isnan(val(ch))\,0\,val(ch)):c=same')
    gain = float(settings['gain_db'])
    if not math.isfinite(gain):
        raise ValueError('Invalid gain')
    if gain:
        filters.append('volume=%sdB:precision=double' % gain)
    if settings['limiter_enabled']:
        ceiling = float(settings['limiter_ceiling_dbfs'])
        if not -24 <= ceiling <= 0:
            raise ValueError('Invalid peak ceiling')
        filters.append('alimiter=limit=%.8f:attack=%s:release=%s:level=false:latency=true' % (
            10 ** (ceiling / 20), settings['limiter_attack_ms'], settings['limiter_release_ms']))
    return ','.join(filters)


def convert_audio(source, target, speed, settings=None, control=None):
    settings = settings or AUDIO_PROCESSING
    _output, errors = run_process([ffmpeg_path(), '-y', '-nostdin', '-hide_banner', '-v', 'error',
                 '-i', str(source), '-vn', '-filter:a', audio_filter(speed, settings),
                 '-ar', str(settings['sample_rate']), '-codec:a', 'libmp3lame',
                 '-b:a', '128k', str(target)], control or Control())
    return bool(errors.strip())


def verify_processed(source_duration, output_duration, speed):
    expected = source_duration / float(speed)
    # Allow encoder delay/atempo boundary effects, but never a half-length output.
    if abs(output_duration - expected) > max(2.0, expected * .02):
        raise RuntimeError('Duration mismatch: expected %.2fs, actual %.2fs' % (expected, output_duration))


def download_file(url, target, control=None, log=lambda *args: None, attempts=3):
    control = control or Control()
    failures = 0
    while failures < attempts:
        control.checkpoint()
        try:
            with requests.get(url, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'},
                              timeout=(10, 15), stream=True, allow_redirects=True) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise RuntimeError('Unexpected partial HTTP response: %s' % response.status_code)
                if 'text/html' in response.headers.get('Content-Type', '').lower():
                    raise RuntimeError('Audio URL returned HTML')
                expected = response.headers.get('Content-Length')
                expected = int(expected) if expected and expected.isdigit() and not response.headers.get('Content-Encoding') else None
                total = 0
                with Path(target).open('wb') as stream:
                    for chunk in response.iter_content(64 * 1024):
                        control.check_stop()
                        if control.pause_event.is_set():
                            raise RestartDownload()
                        if chunk:
                            stream.write(chunk)
                            total += len(chunk)
                if not total or (expected is not None and total != expected):
                    raise RuntimeError('Download size mismatch: %s / %s' % (total, expected))
                return {'bytes': total, 'http_content_length': expected,
                        'content_type': response.headers.get('Content-Type', '')}
        except RestartDownload:
            # Close the connection before pausing. No fragile indefinite idle socket.
            Path(target).unlink(missing_ok=True)
            log('download_restart')
            control.checkpoint()
        except Stopped:
            Path(target).unlink(missing_ok=True)
            raise
        except (requests.RequestException, RuntimeError, OSError):
            Path(target).unlink(missing_ok=True)
            failures += 1
            if failures >= attempts:
                raise
            log('retry', failures + 1, attempts)
            control.delay(min(2 ** failures, 8))


def fetch_feed(url, control, log):
    for attempt in range(3):
        control.checkpoint()
        try:
            response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=(10, 15))
            response.raise_for_status()
            control.checkpoint()
            feed = feedparser.parse(response.content)
            if not feed.entries:
                raise RuntimeError('RSS contains no episodes')
            return feed.entries
        except (requests.RequestException, RuntimeError):
            if attempt == 2:
                raise
            log('retry', attempt + 2, 3)
            control.delay(2 ** (attempt + 1))


def settings_for(podcast, defaults):
    settings = dict(AUDIO_PROCESSING, **defaults)
    settings.update(podcast.get('audio') or {})
    return settings


def update_library(podcasts, output_dir, history_file, defaults, control, log,
                   force=False, reprocess=False, keep_originals=True, error_log=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = output_dir / '.swimcast_originals'
    cache.mkdir(exist_ok=True)
    history = load_json(history_file, {'episodes': {}})
    episodes = history.setdefault('episodes', {})
    result = {'success': 0, 'skipped': 0, 'failed': 0, 'stopped': False}
    try:
        for podcast in podcasts:
            control.checkpoint()
            log('podcast', podcast['name'])
            try:
                entries = fetch_feed(podcast['rss'], control, log)[:int(podcast.get('episodes', 1))]
            except Stopped:
                raise
            except Exception as error:
                result['failed'] += 1
                record_error(error_log, podcast['name'], error)
                log('failed', str(error))
                continue
            for item in entries:
                control.checkpoint()
                url = find_audio_url(item)
                title = item.get('title', 'episode')
                log('episode', title)
                if not url:
                    result['failed'] += 1
                    log('no_audio')
                    continue
                key = episode_key(item, url)
                previous = episodes.get(key, {})
                if previous and not force and not reprocess:
                    result['skipped'] += 1
                    log('skipped')
                    continue
                target = output_dir / safe_filename(podcast['name']) / ('%s_%gx.mp3' % (safe_filename(title), float(podcast.get('speed', 1.5))))
                if target.is_file() and not force and not reprocess:
                    try:
                        duration, warnings = inspect_audio_details(target, control)
                        advertised = duration_seconds(item.get('itunes_duration'))
                        expected_output = advertised / float(podcast.get('speed', 1.5)) if advertised else None
                        if expected_output and duration < expected_output * .8 and expected_output - duration > 15:
                            raise RuntimeError('Existing file is much shorter than RSS duration after speed conversion')
                        episodes[key] = {
                            'podcast': podcast['name'], 'title': title, 'rss': podcast['rss'],
                            'audio_url': url, 'speed': float(podcast.get('speed', 1.5)),
                            'file': str(target), 'output_seconds': duration,
                            'rss_seconds': advertised,
                            'output_bytes': target.stat().st_size, 'verified': False,
                            'decode_checked': True, 'decode_warnings': warnings,
                            'legacy_existing': True,
                            'processed_at': datetime.now().isoformat(timespec='seconds'),
                        }
                        save_json(history_file, history)
                        result['skipped'] += 1
                        log('existing_adopted', duration)
                        if warnings:
                            log('decode_warning')
                        continue
                    except Stopped:
                        raise
                    except Exception as error:
                        log('existing_invalid', str(error))
                process_episode(item, podcast, key, url, previous, output_dir, cache,
                                history, history_file, defaults, control, log, result,
                                force, reprocess, keep_originals, error_log)
    except Stopped:
        result['stopped'] = True
        log('stopped')
    return result


def process_episode(item, podcast, key, url, previous, output_dir, cache,
                    history, history_file, defaults, control, log, result,
                    force, reprocess, keep_originals, error_log):
    title = item.get('title', 'episode')
    folder = output_dir / safe_filename(podcast['name'])
    folder.mkdir(exist_ok=True)
    speed = float(podcast.get('speed', 1.5))
    settings = settings_for(podcast, defaults)
    target = folder / ('%s_%gx.mp3' % (safe_filename(title), speed))
    temporary = folder / ('.swimcast-%s.part.mp3' % key[:16])
    raw = cache / (key + '.download')
    original = cache / (key + '.audio')
    try:
        metadata = {}
        source = original if reprocess and original.is_file() else raw
        for attempt in range(3):
            if source == raw:
                log('downloading')
                metadata = download_file(url, raw, control, log)
            control.checkpoint()
            try:
                log('checking_source')
                source_duration, source_warnings = inspect_audio_details(source, control)
                if source_warnings:
                    log('decode_warning')
                expected = duration_seconds(item.get('itunes_duration'))
                metadata.update(source_seconds=source_duration, rss_seconds=expected)
                if expected and source_duration < expected * .8 and expected - source_duration > 30:
                    raise RuntimeError('Source is much shorter than RSS: %.1fs / %.1fs; incomplete download or shortened feed version' % (source_duration, expected))
                break
            except Stopped:
                raise
            except RuntimeError:
                if source != raw or attempt == 2:
                    raise
                log('retry', attempt + 2, 3)
                control.checkpoint()
        control.checkpoint()
        log('converting')
        conversion_warnings = convert_audio(source, temporary, speed, settings, control)
        if conversion_warnings and not source_warnings:
            log('decode_warning')
        log('checking_output')
        output_duration, output_warnings = inspect_audio_details(temporary, control)
        if output_warnings:
            log('decode_warning')
        verify_processed(source_duration, output_duration, speed)
        control.check_stop()
        if keep_originals and source == raw:
            raw.replace(original)
        temporary.replace(target)
        history['episodes'][key] = {
            'podcast': podcast['name'], 'title': title, 'rss': podcast['rss'],
            'audio_url': url, 'speed': speed, 'audio': settings, 'file': str(target),
            'original_file': str(original) if original.is_file() else None,
            'output_seconds': output_duration, 'output_bytes': target.stat().st_size,
            'verified': True,
            'decode_warnings': source_warnings or conversion_warnings or output_warnings,
            **metadata,
            'processed_at': datetime.now().isoformat(timespec='seconds'),
        }
        save_json(history_file, history)
        result['success'] += 1
        log('complete', source_duration, output_duration)
        control.checkpoint()
    except Stopped:
        raise
    except Exception as error:
        result['failed'] += 1
        record_error(error_log, '%s | %s' % (podcast['name'], title), error)
        log('failed', str(error))
    finally:
        raw.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)


def record_error(path, title, error):
    if path:
        # URLs may carry subscription tokens: keep this local and out of Git.
        with Path(path).open('a', encoding='utf-8') as stream:
            stream.write('[%s] %s | %s\n' % (datetime.now().isoformat(timespec='seconds'), title, error))


def hash_file(path, control):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while True:
            control.checkpoint()
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def locate_audio_file(record, output_dir):
    """Find an existing download after its recorded path becomes stale."""
    recorded = Path(record.get('file') or '')
    if recorded.is_file():
        return recorded
    filename = recorded.name
    if not filename or filename == '.':
        return None
    root = Path(output_dir)
    if not root.is_dir():
        return None
    direct = root / safe_filename(record.get('podcast', '')) / filename
    if direct.is_file():
        return direct
    flat = root / filename
    if flat.is_file():
        return flat
    # A uniquely matching file may have been moved to another folder under the
    # configured library. Never guess if two candidates share the same name.
    matches = [candidate for candidate in root.rglob(filename) if candidate.is_file()]
    return matches[0] if len(matches) == 1 else None


def transfer_file(source, destination, control=None, replace=False):
    control = control or Control()
    source, destination = Path(source), Path(destination)
    if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(destination)):
        raise ValueError('Source and destination are the same file')
    # Snapshot source hash before copy; detect source edits during transmission.
    source_hash = hash_file(source, control)
    source_size = source.stat().st_size
    if destination.exists():
        if destination.stat().st_size == source_size and hash_file(destination, control) == source_hash:
            return 'identical'
        if not replace:
            return 'conflict'
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Unique task-owned temporary file; never delete another user's partial file.
    fd, temp_name = tempfile.mkstemp(prefix='.swimcast-', suffix='.part', dir=str(destination.parent))
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as input_stream:
            while True:
                control.checkpoint()
                chunk = input_stream.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if temporary.stat().st_size != source_size or hash_file(temporary, control) != source_hash:
            raise RuntimeError('Transfer checksum mismatch')
        if hash_file(source, control) != source_hash:
            raise RuntimeError('Source changed during transfer')
        control.checkpoint()
        if destination.exists() and not replace:
            return 'conflict'
        temporary.replace(destination)
        if destination.stat().st_size != source_size or hash_file(destination, control) != source_hash:
            raise RuntimeError('Final destination checksum mismatch')
        return 'copied'
    finally:
        temporary.unlink(missing_ok=True)


def transfer_audio(source, destination, mode='copy', control=None, replace=False):
    """Copy, or delete source only after a verified destination is in place."""
    if mode not in ('copy', 'move'):
        raise ValueError('Unknown transfer mode')
    control = control or Control()
    outcome = transfer_file(source, destination, control, replace)
    if mode == 'move' and outcome in ('copied', 'identical'):
        control.checkpoint()
        Path(source).unlink()
        return 'moved'
    return outcome
