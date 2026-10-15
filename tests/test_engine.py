import contextlib
import hashlib
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import engine

FFMPEG = str(Path(__file__).parent.parent / 'ffmpeg.exe') if (Path(__file__).parent.parent / 'ffmpeg.exe').exists() else shutil.which('ffmpeg')
if FFMPEG:
    engine.ffmpeg_path = lambda: FFMPEG


class AudioTests(unittest.TestCase):
    def test_locate_audio_file_with_stale_history(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            root = Path(root)
            record = {'podcast': 'Example', 'file': str(root / 'old' / 'episode.mp3')}
            self.assertIsNone(engine.locate_audio_file(record, root))
            actual = root / 'Example' / 'episode.mp3'
            actual.parent.mkdir()
            actual.write_bytes(b'audio')
            self.assertEqual(engine.locate_audio_file(record, root), actual)
            actual.rename(root / 'episode.mp3')
            self.assertEqual(engine.locate_audio_file(record, root), root / 'episode.mp3')

    @unittest.skipUnless(FFMPEG, 'FFmpeg is required')
    def test_end_to_end_duration_and_transfer(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            root = Path(root)
            source, target = root / 'source.mp3', root / 'out.mp3'
            engine.run_process([FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i',
                                'sine=frequency=440:duration=6', '-codec:a', 'libmp3lame', str(source)], engine.Control())
            original_duration = engine.inspect_audio(source)
            engine.convert_audio(source, target, 2)
            output_duration = engine.inspect_audio(target)
            engine.verify_processed(original_duration, output_duration, 2)
            self.assertLess(output_duration, original_duration * .6)
            destination = root / 'player' / 'out.mp3'
            self.assertEqual(engine.transfer_file(target, destination), 'copied')
            self.assertEqual(engine.transfer_file(target, destination), 'identical')
            self.assertEqual(hashlib.sha256(target.read_bytes()).digest(), hashlib.sha256(destination.read_bytes()).digest())
            (root / 'other.mp3').write_bytes(b'different')
            self.assertEqual(engine.transfer_file(root / 'other.mp3', destination), 'conflict')
            self.assertEqual(engine.transfer_file(root / 'other.mp3', destination, replace=True), 'copied')

    def test_move_deletes_source_only_after_verified_transfer(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            root = Path(root)
            source, destination = root / 'download.mp3', root / 'player' / 'download.mp3'
            source.write_bytes(b'audio bytes' * 100)
            self.assertEqual(engine.transfer_audio(source, destination, mode='move'), 'moved')
            self.assertFalse(source.exists())
            self.assertEqual(destination.read_bytes(), b'audio bytes' * 100)
            source.write_bytes(b'new audio')
            self.assertEqual(engine.transfer_audio(source, destination, mode='move'), 'conflict')
            self.assertTrue(source.exists())
            self.assertEqual(destination.read_bytes(), b'audio bytes' * 100)

    def test_stop_and_pause(self):
        controller = engine.Control()
        controller.pause()
        finished = threading.Event()
        thread = threading.Thread(target=lambda: (controller.checkpoint(), finished.set()))
        thread.start()
        self.assertFalse(finished.wait(.2))
        controller.resume()
        self.assertTrue(finished.wait(2))
        thread.join()
        controller.stop()
        with self.assertRaises(engine.Stopped):
            controller.checkpoint()

    @unittest.skipUnless(FFMPEG, 'FFmpeg is required')
    def test_stop_interrupts_ffmpeg(self):
        control = engine.Control()
        outcome = []
        def run():
            try:
                engine.run_process([FFMPEG, '-re', '-v', 'error', '-f', 'lavfi', '-i',
                                    'sine=duration=20', '-f', 'null', '-'], control)
            except engine.Stopped:
                outcome.append('stopped')
        thread = threading.Thread(target=run)
        thread.start()
        time.sleep(.3)
        control.stop()
        thread.join(timeout=4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, ['stopped'])

    def test_short_output_rejected(self):
        with self.assertRaises(RuntimeError):
            engine.verify_processed(2400, 600, 2)

    @unittest.skipUnless(FFMPEG, 'FFmpeg is required')
    def test_recoverable_mp3_damage_is_warning(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            root = Path(root)
            clean, damaged, output = root / 'clean.mp3', root / 'damaged.mp3', root / 'output.mp3'
            engine.run_process([FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i',
                                'sine=frequency=440:duration=8', '-codec:a', 'libmp3lame', str(clean)], engine.Control())
            data = clean.read_bytes()
            midpoint = len(data) // 2
            damaged.write_bytes(data[:midpoint] + b'\0' * 400 + data[midpoint:])
            source_duration, warnings = engine.inspect_audio_details(damaged)
            self.assertTrue(warnings)
            conversion_warnings = engine.convert_audio(damaged, output, 2)
            self.assertTrue(conversion_warnings)
            engine.verify_processed(source_duration, engine.inspect_audio(output), 2)

    @unittest.skipUnless(FFMPEG, 'FFmpeg is required')
    def test_adopts_existing_file_without_downloading(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            root = Path(root)
            output = root / 'output'
            target = output / 'Test' / 'Episode_2x.mp3'
            target.parent.mkdir(parents=True)
            engine.run_process([FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i',
                                'sine=frequency=440:duration=3', '-codec:a', 'libmp3lame', str(target)], engine.Control())
            feed = b'<?xml version="1.0"?><rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><title>Test</title><item><title>Episode</title><guid>one</guid><itunes:duration>6</itunes:duration><enclosure url="https://example.test/audio" type="audio/mpeg"/></item></channel></rss>'
            class Response:
                content = feed
                def raise_for_status(self): pass
            def get(url, **kwargs):
                self.assertTrue(url.endswith('/feed'), 'Audio URL must not be fetched')
                return Response()
            with patch.object(engine.requests, 'get', side_effect=get):
                history = root / 'history.json'
                result = engine.update_library([{'name': 'Test', 'rss': 'https://example.test/feed',
                                                'speed': 2, 'episodes': 1}], output, history, {},
                                               engine.Control(), lambda *args: None)
                self.assertEqual(result['skipped'], 1)
                record = next(iter(json.loads(history.read_text(encoding='utf-8'))['episodes'].values()))
                self.assertTrue(record['legacy_existing'])
                self.assertFalse(record['verified'])

    def test_download_rejects_short_content_length(self):
        class ShortResponse:
            status_code = 200
            headers = {'Content-Length': '1000', 'Content-Type': 'audio/mpeg'}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self): pass
            def iter_content(self, _): yield b'abc'
        with patch.object(engine.requests, 'get', return_value=ShortResponse()):
            with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
                path = Path(root) / 'download.part'
                with self.assertRaises(RuntimeError):
                    engine.download_file('https://example.test/audio', path, attempts=1)
                self.assertFalse(path.exists())

    @unittest.skipUnless(FFMPEG, 'FFmpeg is required')
    def test_feed_to_verified_history(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            root = Path(root)
            source = root / 'source.mp3'
            engine.run_process([FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i',
                                'sine=frequency=440:duration=6', '-codec:a', 'libmp3lame', str(source)], engine.Control())
            class Response:
                status_code = 200
                def __init__(self, content, kind):
                    self.content = content
                    self.headers = {'Content-Length': str(len(content)), 'Content-Type': kind}
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def raise_for_status(self): pass
                def iter_content(self, _): yield self.content
            feed = b'<?xml version="1.0"?><rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><title>Test</title><item><title>Episode</title><guid>one</guid><itunes:duration>6</itunes:duration><enclosure url="https://example.test/audio" type="audio/mpeg"/></item></channel></rss>'
            def get(url, **kwargs):
                return Response(feed, 'application/rss+xml') if url.endswith('/feed') else Response(source.read_bytes(), 'audio/mpeg')
            with patch.object(engine.requests, 'get', side_effect=get):
                history = root / 'history.json'
                config = [{'name': 'Test', 'rss': 'https://example.test/feed',
                           'speed': 2, 'episodes': 1}]
                logs = []
                result = engine.update_library(config, root / 'output', history, {}, engine.Control(),
                                               lambda *args: logs.append(args))
                self.assertEqual(result['success'], 1, logs)
                record = next(iter(json.loads(history.read_text(encoding='utf-8'))['episodes'].values()))
                self.assertTrue(record['verified'])
                self.assertTrue(Path(record['file']).is_file())
                self.assertAlmostEqual(record['source_seconds'] / record['output_seconds'], 2, delta=.1)
                self.assertEqual(engine.update_library(config, root / 'output', history, {}, engine.Control(),
                                                       lambda *args: None)['skipped'], 1)


if __name__ == '__main__':
    unittest.main()
