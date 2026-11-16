"""
Vitarg Comprehensive 4-Tier User Requirements Test Suite.
Requirement-driven opaque-box verification across:
- Tier 1: Feature Coverage (24 tests)
- Tier 2: Boundary & Corner Cases (22 tests)
- Tier 3: Cross-Feature Combinations (8 tests)
- Tier 4: Real-World Application Scenarios (5 tests)
Total: 59 tests matching TEST_INFRA.md specification.
"""
from __future__ import annotations

import gc
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure Qt offscreen platform before PySide6 loads plugins
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Ensure workspace root in sys.path
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

try:
    from PySide6.QtCore import Qt, QPointF, QPoint, QEvent, QTimer, QSize
    from PySide6.QtGui import QMouseEvent, QKeyEvent
    from PySide6.QtWidgets import (
        QApplication, QDialog, QSlider, QComboBox, QLineEdit, QSpinBox,
        QLabel, QPushButton, QWidget
    )
    qt_app = QApplication.instance()
    if qt_app is None:
        qt_app = QApplication(sys.argv if sys.argv else ["vitarg_test"])
    HAS_QT = True
except ImportError:
    HAS_QT = False
    qt_app = None

from vitarg import settings as S
from vitarg import tools
from vitarg import engine
from vitarg import undo
from vitarg.dialogs import FormDialog, ActionConfirmDialog
from vitarg.wheel import Wheel
from vitarg.engine import ConversionError


class UserRequirementsTestBase(unittest.TestCase):
    """Base fixture providing full filesystem, settings, undo, and Qt isolation."""

    def setUp(self):
        self._orig_appdata = os.environ.get("APPDATA")
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_dir.name)
        os.environ["APPDATA"] = str(self.tmp)
        self.st = S.Settings()

        # Reset UndoManager singleton to isolated directory
        undo.UndoManager._instance = None
        self.undo_mgr = undo.UndoManager.get()
        undo.undo_manager = self.undo_mgr
        self.undo_mgr._backup_dir = self.tmp / "vitarg-backups"
        self.undo_mgr._backup_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        gc.collect()
        if HAS_QT and qt_app is not None:
            qt_app.processEvents()
        undo.UndoManager._instance = None
        undo.undo_manager = undo.UndoManager.get()
        if self._orig_appdata is not None:
            os.environ["APPDATA"] = self._orig_appdata
        else:
            os.environ.pop("APPDATA", None)
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def _create_sample_file(self, name: str, size: int = 1024, data: bytes = None) -> Path:
        """Create a mock media file in the sandboxed temporary directory."""
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if data is not None else (b"\x00" * size))
        return p

    @contextmanager
    def mock_ffmpeg_and_probe(self, video: bool = True, audio: bool = True, duration: float = 5.0):
        """
        Boundary interception of FFmpeg and probe calls for deterministic,
        hardware-independent command argument and parameter flow verification.
        """
        captured_args: list[list[str]] = []

        def fake_run_ffmpeg(args, *a, **k):
            captured_args.append(list(args))
            out_path = Path(args[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if not out_path.exists():
                out_path.write_bytes(b"mock_media_transcoded_data")

        def fake_probe(path):
            return {
                "duration": duration,
                "video": video,
                "audio": audio,
                "width": 1280 if video else 0,
                "height": 720 if video else 0,
            }

        with patch("vitarg.engine.probe", side_effect=fake_probe), \
             patch("vitarg.engine.run_ffmpeg", side_effect=fake_run_ffmpeg), \
             patch("vitarg.tools.probe", side_effect=fake_probe), \
             patch("vitarg.tools.run_ffmpeg", side_effect=fake_run_ffmpeg):
            yield captured_args


# ============================================================================
# Tier 1: Feature Coverage (24 tests)
# ============================================================================
class TestTier1FeatureCoverage(UserRequirementsTestBase):
    """Direct functional verification of all 4 major features with >=5 tests per feature."""

    # --- Feature 1.1: FormDialog File Drop Handling (6 tests) ---
    def test_tier1_form_dialog_drop_instantiation_without_name_error(self):
        """FormDialog opens on file drop with no NameError and initializes rename_edit."""
        src = self._create_sample_file("sample_video.mp4")
        dlg = FormDialog(tools.BY_ID["volume"], self.st, preview_paths=[str(src)])
        try:
            self.assertIsNotNone(dlg.rename_edit, "FormDialog rename_edit should be created on drop")
            self.assertEqual(dlg.rename_edit.text(), "sample_video")
        finally:
            dlg.deleteLater()

    def test_tier1_form_dialog_multi_file_drop_default_pattern(self):
        """Multi-file drop defaults rename pattern to '{name}'."""
        f1 = self._create_sample_file("clip1.mp4")
        f2 = self._create_sample_file("clip2.mp4")
        dlg = FormDialog(tools.BY_ID["volume"], self.st, preview_paths=[str(f1), str(f2)])
        try:
            self.assertIsNotNone(dlg.rename_edit)
            self.assertEqual(dlg.rename_edit.text(), "{name}")
        finally:
            dlg.deleteLater()

    def test_tier1_form_dialog_target_compress_preset_isolation(self):
        """settings.compress_preset does not overwrite target_compress preset."""
        self.st.compress_preset = "Strong"
        dlg = FormDialog(tools.BY_ID["target_compress"], self.st)
        try:
            self.assertIn("preset", dlg.widgets)
            curr = dlg.widgets["preset"].currentText()
            self.assertNotEqual(curr, "Strong", "target_compress preset must not be overwritten by settings.compress_preset")
            self.assertEqual(curr, "<25 MB (Discord)")
        finally:
            dlg.deleteLater()

    def test_tier1_form_dialog_eq_preset_isolation(self):
        """settings.compress_preset does not overwrite audio equalizer preset."""
        self.st.compress_preset = "Strong"
        dlg = FormDialog(tools.BY_ID["eq"], self.st)
        try:
            self.assertIn("preset", dlg.widgets)
            curr = dlg.widgets["preset"].currentText()
            self.assertNotEqual(curr, "Strong", "eq preset must not be overwritten by settings.compress_preset")
            self.assertTrue("Bass" in curr)
        finally:
            dlg.deleteLater()

    def test_tier1_form_dialog_values_returns_custom_name(self):
        """FormDialog.values() includes customized rename string."""
        src = self._create_sample_file("track.mp3")
        dlg = FormDialog(tools.BY_ID["volume"], self.st, preview_paths=[str(src)])
        try:
            dlg.rename_edit.setText("MyCustomTrackName")
            vals = dlg.values()
            self.assertIsInstance(vals, dict)
            self.assertEqual(vals.get("custom_name"), "MyCustomTrackName")
        finally:
            dlg.deleteLater()

    def test_tier1_form_dialog_audio_listen_preview_button_present(self):
        """Audio preview button present for audio/video preview tools."""
        src = self._create_sample_file("voice.wav")
        dlg = FormDialog(tools.BY_ID["volume"], self.st, preview_paths=[str(src)])
        try:
            self.assertTrue(hasattr(dlg, "play_btn") and dlg.play_btn is not None)
            self.assertIn("Listen Preview Sample", dlg.play_btn.text())
        finally:
            dlg.deleteLater()

    # --- Feature 1.2: ActionConfirmDialog Audio Options (6 tests) ---
    def test_tier1_action_confirm_audio_options_controls_exist(self):
        """ActionConfirmDialog presents volume slider, bass dropdown, and bitrate selector."""
        src = self._create_sample_file("input.mp4")
        dlg = ActionConfirmDialog("MP4 → MP3", [str(src)], "mp3", is_conv=True)
        try:
            self.assertTrue(hasattr(dlg, "vol_slider") or hasattr(dlg, "vol_spin"))
            self.assertTrue(hasattr(dlg, "eq_combo") or hasattr(dlg, "bass_combo"))
            self.assertTrue(hasattr(dlg, "bitrate_combo"))
        finally:
            dlg.deleteLater()

    def test_tier1_action_confirm_values_contract_structure(self):
        """ActionConfirmDialog.values() returns dict matching the interface contract."""
        src = self._create_sample_file("podcast.mp4")
        dlg = ActionConfirmDialog("MP4 → MP3", [str(src)], "mp3", is_conv=True)
        try:
            dlg.name_edit.setText("Episode_42")
            if hasattr(dlg, "vol_spin"):
                dlg.vol_spin.setValue(180)
            vals = dlg.values()
            self.assertIsInstance(vals, dict)
            self.assertEqual(vals.get("custom_name"), "Episode_42")
            self.assertIn("volume", vals)
            self.assertEqual(vals["volume"], 180)
            self.assertIn("bass_preset", vals)
            self.assertIn("bitrate_k", vals)
        finally:
            dlg.deleteLater()

    def test_tier1_action_confirm_video_options_controls_exist(self):
        """Video conversion options presented for video targets."""
        src = self._create_sample_file("source.mov")
        dlg = ActionConfirmDialog("MOV → MP4", [str(src)], "mp4", is_conv=True)
        try:
            self.assertTrue(getattr(dlg, "has_audio_options", False) or getattr(dlg, "is_video_target", False))
            vals = dlg.values()
            self.assertIsInstance(vals, dict)
        finally:
            dlg.deleteLater()

    def test_tier1_action_confirm_rename_quick_templates(self):
        """Quick template buttons update output rename edit."""
        src = self._create_sample_file("mysong.wav")
        dlg = ActionConfirmDialog("WAV → MP3", [str(src)], "mp3", is_conv=True)
        try:
            buttons = {b.text().strip(): b for b in dlg.findChildren(QPushButton)}
            if "+ Date" in buttons:
                buttons["+ Date"].click()
                self.assertEqual(dlg.name_edit.text(), "mysong_{date}")
            if "+ 01" in buttons:
                buttons["+ 01"].click()
                self.assertEqual(dlg.name_edit.text(), "mysong_{num}")
            if "-vitarg" in buttons:
                buttons["-vitarg"].click()
                self.assertEqual(dlg.name_edit.text(), "mysong-vitarg")
            if "Original" in buttons:
                buttons["Original"].click()
                self.assertEqual(dlg.name_edit.text(), "mysong")
        finally:
            dlg.deleteLater()

    def test_tier1_action_confirm_preview_badge_rendered(self):
        """Estimate badge rendered in dialog body."""
        src = self._create_sample_file("sample.mp4")
        dlg = ActionConfirmDialog("MP4 → MP3", [str(src)], "mp3", is_conv=True)
        try:
            labels = dlg.findChildren(QLabel)
            has_badge = any("📊" in lbl.text() or "est" in lbl.text().lower() for lbl in labels)
            self.assertTrue(has_badge, "Summary preview badge should be present")
        finally:
            dlg.deleteLater()

    def test_tier1_action_confirm_non_conversion_mode(self):
        """Non-conversion tool confirmation uses 'Start Action'."""
        src = self._create_sample_file("sample.mp4")
        dlg = ActionConfirmDialog("Volume", [str(src)], "volume", is_conv=False)
        try:
            self.assertFalse(dlg.is_conv)
            buttons = dlg.findChildren(QPushButton)
            self.assertTrue(any("Start Action" in b.text() for b in buttons))
        finally:
            dlg.deleteLater()

    # --- Feature 1.3: Wheel Display & Layout (6 tests) ---
    def test_tier1_wheel_stays_on_top_hint(self):
        """Wheel flags include Qt.WindowStaysOnTopHint."""
        w = Wheel(self.st)
        try:
            flags = w.windowFlags()
            self.assertTrue(bool(flags & Qt.WindowStaysOnTopHint), "Wheel must have WindowStaysOnTopHint")
        finally:
            w.deleteLater()

    def test_tier1_wheel_resilient_to_activation_change(self):
        """Wheel does not dismiss prematurely on ActivationChange."""
        src = self._create_sample_file("video.mp4")
        w = Wheel(self.st)
        try:
            w.present("conv", [str(src)], 400, 400, interactive=True)
            self.assertTrue(w.isVisible())
            # Send ActivationChange event
            qt_app.sendEvent(w, QEvent(QEvent.ActivationChange))
            self.assertTrue(w.isVisible(), "Wheel should remain open across focus/activation changes")
        finally:
            w.dismiss()
            w.deleteLater()

    def test_tier1_wheel_all_11_video_tools_visible(self):
        """All 11 video tool petals visible (no [:10] truncation)."""
        src = self._create_sample_file("video.mp4")
        w = Wheel(self.st)
        try:
            w.set_content("tools", [str(src)])
            item_ids = [item[0] for item in w.items]
            self.assertGreaterEqual(len(item_ids), 11, "All 11 video tools should be present")
            self.assertIn("inspect", item_ids, "11th tool 'inspect' must not be truncated")
        finally:
            w.deleteLater()

    def test_tier1_wheel_hit_test_all_petals(self):
        """Radial hit testing works for all 11 petals."""
        src = self._create_sample_file("video.mp4")
        w = Wheel(self.st)
        try:
            w.set_content("tools", [str(src)])
            n = len(w.items)
            self.assertGreaterEqual(n, 11)
            for i in range(n):
                lx = w._layout_cache[i]["lx"]
                ly = w._layout_cache[i]["ly"]
                hit = w._hit(QPointF(lx, ly))
                self.assertEqual(hit, i, f"Hit test at petal {i} should return index {i}")
        finally:
            w.deleteLater()

    def test_tier1_wheel_chosen_signal_on_petal_click(self):
        """Mouse click on petal emits chosen signal."""
        src = self._create_sample_file("video.mp4")
        w = Wheel(self.st)
        try:
            w.set_content("tools", [str(src)])
            emitted = []
            w.chosen.connect(lambda k, i, p: emitted.append((k, i, p)))
            lx = w._layout_cache[0]["lx"]
            ly = w._layout_cache[0]["ly"]
            m_event = QMouseEvent(QEvent.MouseButtonPress, QPointF(lx, ly), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            qt_app.sendEvent(w, m_event)
            qt_app.processEvents()
            self.assertEqual(len(emitted), 1)
            self.assertEqual(emitted[0][0], "tools")
            self.assertEqual(emitted[0][1], w.items[0][0])
        finally:
            w.deleteLater()

    def test_tier1_wheel_escape_key_dismissal(self):
        """Escape key closes wheel."""
        src = self._create_sample_file("video.mp4")
        w = Wheel(self.st)
        try:
            w.present("conv", [str(src)], 400, 400, interactive=True)
            self.assertTrue(w.isVisible())
            k_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
            qt_app.sendEvent(w, k_event)
            self.assertFalse(w.isVisible(), "Escape key must dismiss wheel")
        finally:
            w.deleteLater()

    # --- Feature 1.4: Engine Parameterized Flow (6 tests) ---
    def test_tier1_engine_convert_batch_accepts_params(self):
        """convert_batch accepts params dict."""
        src = self._create_sample_file("video.mp4")
        with self.mock_ffmpeg_and_probe() as captured:
            outs, errs = engine.convert_batch([str(src)], "mp3", self.st, params={"volume": 150, "bass_preset": "Bass Boost"})
            self.assertEqual(len(outs), 1)
            self.assertEqual(errs, [])
            self.assertTrue(any("-filter:a" in args for args in captured))

    def test_tier1_engine_convert_media_volume_filter_applied(self):
        """convert_media applies volume={factor:.2f} filter."""
        src = self._create_sample_file("video.mp4")
        out = self.tmp / "out.mp3"
        with self.mock_ffmpeg_and_probe() as captured:
            engine.convert_media(src, "mp3", out, self.st, engine._noop, None, params={"volume": 75})
            self.assertGreater(len(captured), 0)
            args = captured[0]
            self.assertIn("-filter:a", args)
            af = args[args.index("-filter:a") + 1]
            self.assertIn("volume=0.75", af)

    def test_tier1_engine_convert_media_bass_preset_applied(self):
        """convert_media applies bass equalizer filter."""
        src = self._create_sample_file("video.mp4")
        out = self.tmp / "out.mp3"
        with self.mock_ffmpeg_and_probe() as captured:
            engine.convert_media(src, "mp3", out, self.st, engine._noop, None, params={"bass_preset": "Bass Boost"})
            self.assertGreater(len(captured), 0)
            args = captured[0]
            self.assertIn("-filter:a", args)
            af = args[args.index("-filter:a") + 1]
            self.assertIn("bass=g=8:f=100", af)

    def test_tier1_engine_convert_media_bitrate_override(self):
        """convert_media overrides audio bitrate."""
        src = self._create_sample_file("video.mp4")
        out = self.tmp / "out.mp3"
        with self.mock_ffmpeg_and_probe() as captured:
            engine.convert_media(src, "mp3", out, self.st, engine._noop, None, params={"bitrate_k": 320})
            self.assertGreater(len(captured), 0)
            args = captured[0]
            self.assertIn("-b:a", args)
            self.assertEqual(args[args.index("-b:a") + 1], "320k")

    def test_tier1_tools_volume_boost_execution_with_custom_name(self):
        """Volume boost tool produces customized output."""
        src = self._create_sample_file("audio.wav")
        with self.mock_ffmpeg_and_probe():
            outs, errs = tools.run_tool("volume", [str(src)], {"volume": 200, "custom_name": "DoubleVol"}, self.st)
            self.assertEqual(len(outs), 1)
            self.assertEqual(errs, [])
            self.assertTrue(Path(outs[0]).name.startswith("DoubleVol"))

    def test_tier1_tools_eq_all_presets_execution(self):
        """All 6 equalizer presets execute successfully."""
        src = self._create_sample_file("audio.wav")
        presets = ["Bass Boost", "Ultra Bass", "Vocal Boost", "Treble Boost", "Loudness & Clarity", "Flat"]
        with self.mock_ffmpeg_and_probe():
            for pr in presets:
                outs, errs = tools.run_tool("eq", [str(src)], {"preset": pr}, self.st)
                self.assertEqual(len(outs), 1)
                self.assertEqual(errs, [])
                self.assertTrue(Path(outs[0]).exists())


# ============================================================================
# Tier 2: Boundary & Corner Cases (22 tests)
# ============================================================================
class TestTier2BoundaryCornerCases(UserRequirementsTestBase):
    """Rigorous boundary, resource stress, and invalid-input testing."""

    # --- Boundary 2.1: FormDialog Boundaries (6 tests) ---
    def test_tier2_form_dialog_empty_preview_paths(self):
        """Empty preview_paths opens without crash."""
        dlg = FormDialog(tools.BY_ID["volume"], self.st, preview_paths=[])
        try:
            self.assertEqual(dlg.paths, [])
            self.assertIsNone(dlg.rename_edit)
            vals = dlg.values()
            self.assertIsInstance(vals, dict)
        finally:
            dlg.deleteLater()

    def test_tier2_form_dialog_nonexistent_preview_file(self):
        """Nonexistent file handled gracefully."""
        dlg = FormDialog(tools.BY_ID["volume"], self.st, preview_paths=["nonexistent_track_99.mp4"])
        try:
            self.assertEqual(dlg.duration, 0.0)
        finally:
            dlg.deleteLater()

    def test_tier2_form_dialog_whitespace_only_rename(self):
        """Whitespace rename stripped cleanly."""
        src = self._create_sample_file("clip.mp4")
        dlg = FormDialog(tools.BY_ID["volume"], self.st, preview_paths=[str(src)])
        try:
            dlg.rename_edit.setText("    ")
            vals = dlg.values()
            self.assertEqual(vals.get("custom_name", "").strip(), "")
        finally:
            dlg.deleteLater()

    def test_tier2_form_dialog_special_characters_in_rename(self):
        """Special characters in rename handled without crash."""
        src = self._create_sample_file("clip.mp4")
        dlg = FormDialog(tools.BY_ID["volume"], self.st, preview_paths=[str(src)])
        try:
            dlg.rename_edit.setText("track:special*chars?<>|")
            vals = dlg.values()
            self.assertEqual(vals.get("custom_name"), "track:special*chars?<>|")
        finally:
            dlg.deleteLater()

    def test_tier2_form_dialog_zero_duration_media(self):
        """Zero duration media handled without division-by-zero."""
        src = self._create_sample_file("zero_dur.mp4")
        with patch("vitarg.engine.probe", return_value={"duration": 0.0, "video": True, "audio": True, "width": 1280, "height": 720}):
            dlg = FormDialog(tools.BY_ID["trim"], self.st, preview_paths=[str(src)])
            try:
                self.assertEqual(dlg.duration, 0.0)
            finally:
                dlg.deleteLater()

    def test_tier2_form_dialog_tool_without_form(self):
        """Tools with no form fields handled cleanly."""
        dlg = FormDialog(tools.BY_ID["metadata"], self.st)
        try:
            self.assertEqual(dlg.widgets, {})
            self.assertEqual(dlg.values(), {})
        finally:
            dlg.deleteLater()

    # --- Boundary 2.2: ActionConfirmDialog & Conversion Boundaries (6 tests) ---
    def test_tier2_action_confirm_volume_boundary_minimum_10_percent(self):
        """Volume slider minimum 10% generates volume=0.10."""
        src = self._create_sample_file("clip.mp4")
        dlg = ActionConfirmDialog("MP4 → MP3", [str(src)], "mp3", is_conv=True)
        try:
            if hasattr(dlg, "vol_slider"):
                dlg.vol_slider.setValue(10)
            vals = dlg.values()
            self.assertEqual(vals["volume"], 10)
            with self.mock_ffmpeg_and_probe() as captured:
                engine.convert_media(src, "mp3", self.tmp / "min.mp3", self.st, engine._noop, None, params=vals)
                af = captured[0][captured[0].index("-filter:a") + 1]
                self.assertIn("volume=0.10", af)
        finally:
            dlg.deleteLater()

    def test_tier2_action_confirm_volume_boundary_maximum_600_percent(self):
        """Volume slider maximum 600% generates volume=6.00."""
        src = self._create_sample_file("clip.mp4")
        dlg = ActionConfirmDialog("MP4 → MP3", [str(src)], "mp3", is_conv=True)
        try:
            if hasattr(dlg, "vol_slider"):
                dlg.vol_slider.setValue(600)
            vals = dlg.values()
            self.assertEqual(vals["volume"], 600)
            with self.mock_ffmpeg_and_probe() as captured:
                engine.convert_media(src, "mp3", self.tmp / "max.mp3", self.st, engine._noop, None, params=vals)
                af = captured[0][captured[0].index("-filter:a") + 1]
                self.assertIn("volume=6.00", af)
        finally:
            dlg.deleteLater()

    def test_tier2_action_confirm_extreme_bitrates(self):
        """Extreme bitrates (32k, 500k) passed without crash."""
        src = self._create_sample_file("clip.mp4")
        for br in (32, 500):
            with self.mock_ffmpeg_and_probe() as captured:
                engine.convert_media(src, "mp3", self.tmp / f"out_{br}.mp3", self.st, engine._noop, None, params={"bitrate_k": br})
                args = captured[0]
                self.assertIn("-b:a", args)
                self.assertEqual(args[args.index("-b:a") + 1], f"{br}k")

    def test_tier2_action_confirm_empty_paths_list(self):
        """Empty paths list handled without IndexError."""
        dlg = ActionConfirmDialog("Test", [], "mp3", is_conv=True)
        try:
            self.assertEqual(dlg.paths, [])
            self.assertEqual(dlg.output_name(), "{name}")
        finally:
            dlg.deleteLater()

    def test_tier2_action_confirm_unicode_and_emojis_in_custom_name(self):
        """Custom names with UTF-8 / Turkish / emojis preserved."""
        src = self._create_sample_file("clip.mp4")
        dlg = ActionConfirmDialog("MP4 → MP3", [str(src)], "mp3", is_conv=True)
        try:
            name_val = "🎵 Şarkı — Vitarg 2026 🚀"
            dlg.name_edit.setText(name_val)
            vals = dlg.values()
            self.assertEqual(vals["custom_name"], name_val)
        finally:
            dlg.deleteLater()

    def test_tier2_action_confirm_unknown_bass_preset_fallback(self):
        """Unknown preset falls back safely."""
        src = self._create_sample_file("clip.mp4")
        with self.mock_ffmpeg_and_probe() as captured:
            engine.convert_media(src, "mp3", self.tmp / "fallback.mp3", self.st, engine._noop, None, params={"bass_preset": "UnknownPreset123"})
            self.assertGreater(len(captured), 0)

    # --- Boundary 2.3: Wheel Boundaries (5 tests) ---
    def test_tier2_wheel_empty_paths_content(self):
        """Empty paths shows 'NO OPTIONS' or 'DROP HERE'."""
        w = Wheel(self.st)
        try:
            w.set_content("conv", [])
            self.assertIn(w.center_text(), ("NO OPTIONS", "DROP HERE"))
        finally:
            w.deleteLater()

    def test_tier2_wheel_single_item_petal_geometry(self):
        """Single petal wheel rendered without math error."""
        w = Wheel(self.st)
        try:
            w.items = [("mp3", "MP3", "")]
            w._rebuild()
            self.assertEqual(len(w._shape_cache), 1)
        finally:
            w.deleteLater()

    def test_tier2_wheel_large_item_count(self):
        """16+ items rendered without geometry inversion."""
        w = Wheel(self.st)
        try:
            w.items = [(f"item_{i}", f"LABEL_{i}", "") for i in range(16)]
            w._rebuild()
            self.assertEqual(len(w._shape_cache), 16)
        finally:
            w.deleteLater()

    def test_tier2_wheel_hit_test_out_of_bounds(self):
        """Center click and distant clicks return -1."""
        src = self._create_sample_file("test.mp4")
        w = Wheel(self.st)
        try:
            w.set_content("tools", [str(src)])
            self.assertEqual(w._hit(QPointF(220, 220)), -1)
            self.assertEqual(w._hit(QPointF(10000, 10000)), -1)
        finally:
            w.deleteLater()

    def test_tier2_wheel_rapid_presentation_toggle(self):
        """Rapid present/dismiss toggle does not crash."""
        src = self._create_sample_file("test.mp4")
        w = Wheel(self.st)
        try:
            for _ in range(5):
                w.present("conv", [str(src)], 300, 300, interactive=True)
                w.dismiss()
            self.assertFalse(w.isVisible())
        finally:
            w.deleteLater()

    # --- Boundary 2.4: Tools & Engine Boundaries (5 tests) ---
    def test_tier2_tools_volume_boost_video_without_audio_fails_gracefully(self):
        """Volume boost on video without audio reports graceful error."""
        src = self._create_sample_file("video_only.mp4")
        with self.mock_ffmpeg_and_probe(video=True, audio=False):
            outs, errs = tools.run_tool("volume", [str(src)], {"volume": 200}, self.st)
            self.assertEqual(outs, [])
            self.assertEqual(len(errs), 1)
            self.assertIn("no audio stream", errs[0][1].lower())

    def test_tier2_tools_eq_video_without_audio_fails_gracefully(self):
        """Equalizer on video without audio reports graceful error."""
        src = self._create_sample_file("video_only.mp4")
        with self.mock_ffmpeg_and_probe(video=True, audio=False):
            outs, errs = tools.run_tool("eq", [str(src)], {"preset": "Bass Boost"}, self.st)
            self.assertEqual(outs, [])
            self.assertEqual(len(errs), 1)
            self.assertIn("no audio stream", errs[0][1].lower())

    def test_tier2_tools_target_compress_insufficient_bitrate_error(self):
        """Over-aggressive target size reports graceful error."""
        src = self._create_sample_file("long_video.mp4")
        with self.mock_ffmpeg_and_probe(video=True, audio=True, duration=3600.0):
            outs, errs = tools.run_tool("target_compress", [str(src)], {"preset": "Custom MB", "custom_mb": 0.01}, self.st)
            self.assertEqual(outs, [])
            self.assertEqual(len(errs), 1)
            self.assertIn("too small", errs[0][1].lower())

    def test_tier2_engine_convert_batch_empty_sources(self):
        """Empty sources list returns empty output without error."""
        outs, errs = engine.convert_batch([], "mp3", self.st)
        self.assertEqual(outs, [])
        self.assertEqual(errs, [])

    def test_tier2_engine_convert_media_params_none_backward_compatible(self):
        """params=None preserves default conversion."""
        src = self._create_sample_file("clip.mp4")
        out = self.tmp / "compat.mp3"
        with self.mock_ffmpeg_and_probe() as captured:
            engine.convert_media(src, "mp3", out, self.st, engine._noop, None, params=None)
            self.assertGreater(len(captured), 0)
            self.assertNotIn("-filter:a", captured[0])


# ============================================================================
# Tier 3: Cross-Feature Combinations (8 tests)
# ============================================================================
class TestTier3CrossFeatureCombinations(UserRequirementsTestBase):
    """Pairwise combinatorial interactions across options, dialogs, wheel, and engine."""

    def test_tier3_video_to_mp3_with_volume_and_bass_boost(self):
        """Video to MP3 with volume attenuation + Bass Boost."""
        src = self._create_sample_file("podcast.mp4")
        with self.mock_ffmpeg_and_probe() as captured:
            outs, errs = engine.convert_batch([str(src)], "mp3", self.st, params={"volume": 60, "bass_preset": "Bass Boost"})
            self.assertEqual(len(outs), 1)
            self.assertEqual(errs, [])
            af = captured[0][captured[0].index("-filter:a") + 1]
            self.assertIn("volume=0.60", af)
            self.assertIn("bass=g=8:f=100", af)

    def test_tier3_video_to_mp3_with_high_volume_and_ultra_bass(self):
        """Video to MP3 with volume amplification (300%) + Ultra Bass."""
        src = self._create_sample_file("clip.mp4")
        with self.mock_ffmpeg_and_probe() as captured:
            outs, errs = engine.convert_batch([str(src)], "mp3", self.st, params={"volume": 300, "bass_preset": "Ultra Bass"})
            self.assertEqual(len(outs), 1)
            self.assertEqual(errs, [])
            af = captured[0][captured[0].index("-filter:a") + 1]
            self.assertIn("volume=3.00", af)
            self.assertIn("bass=g=14:f=80", af)

    def test_tier3_video_to_mp3_with_custom_bitrate_and_custom_name(self):
        """Video to MP3 with custom bitrate (320k) and custom output name."""
        src = self._create_sample_file("clip.mp4")
        with self.mock_ffmpeg_and_probe() as captured:
            outs, errs = engine.convert_batch([str(src)], "mp3", self.st, custom_name="HighQuality_Track", params={"bitrate_k": 320})
            self.assertEqual(len(outs), 1)
            self.assertEqual(Path(outs[0]).name, "HighQuality_Track.mp3")
            args = captured[0]
            self.assertIn("-b:a", args)
            self.assertEqual(args[args.index("-b:a") + 1], "320k")

    def test_tier3_wheel_selection_to_action_confirm_dialog_flow(self):
        """Wheel selection to ActionConfirmDialog to conversion pipeline."""
        src = self._create_sample_file("clip.mp4")
        w = Wheel(self.st)
        dlg = None
        try:
            w.set_content("conv", [str(src)])
            dlg = ActionConfirmDialog("MP4 → MP3", [str(src)], "mp3", is_conv=True)
            dlg.name_edit.setText("FlowSelected")
            if hasattr(dlg, "vol_slider"):
                dlg.vol_slider.setValue(140)
            if hasattr(dlg, "eq_combo"):
                dlg.eq_combo.setCurrentText("Bass Boost (+8dB)")
            vals = dlg.values()
            with self.mock_ffmpeg_and_probe() as captured:
                outs, errs = engine.convert_batch([str(src)], "mp3", self.st, custom_name=vals["custom_name"], params=vals)
                self.assertEqual(len(outs), 1)
                self.assertEqual(Path(outs[0]).name, "FlowSelected.mp3")
                af = captured[0][captured[0].index("-filter:a") + 1]
                self.assertIn("volume=1.40", af)
                self.assertIn("bass=g=8:f=100", af)
        finally:
            w.deleteLater()
            if dlg:
                dlg.deleteLater()

    def test_tier3_wheel_tool_drop_to_form_dialog_flow(self):
        """Wheel tool drop to FormDialog to tool execution."""
        src = self._create_sample_file("audio.wav")
        w = Wheel(self.st)
        dlg = None
        try:
            w.set_content("tools", [str(src)])
            dlg = FormDialog(tools.BY_ID["volume"], self.st, preview_paths=[str(src)])
            if "volume" in dlg.widgets:
                dlg.widgets["volume"].setValue(250)
            dlg.rename_edit.setText("Vol_250pct")
            params = dlg.values()
            with self.mock_ffmpeg_and_probe():
                outs, errs = tools.run_tool("volume", [str(src)], params, self.st)
                self.assertEqual(len(outs), 1)
                self.assertEqual(errs, [])
                self.assertTrue(Path(outs[0]).name.startswith("Vol_250pct"))
        finally:
            w.deleteLater()
            if dlg:
                dlg.deleteLater()

    def test_tier3_form_dialog_target_compress_custom_mb_with_rename(self):
        """FormDialog target compress custom MB with rename template."""
        src = self._create_sample_file("clip.mp4")
        dlg = FormDialog(tools.BY_ID["target_compress"], self.st, preview_paths=[str(src)])
        try:
            dlg.widgets["preset"].setCurrentText("Custom MB")
            dlg.widgets["custom_mb"].setValue(15)
            dlg.rename_edit.setText("{name}_compressed")
            params = dlg.values()
            with self.mock_ffmpeg_and_probe(video=True, audio=True, duration=10.0) as captured:
                outs, errs = tools.run_tool("target_compress", [str(src)], params, self.st)
                self.assertEqual(len(outs), 1)
                self.assertEqual(errs, [])
                self.assertTrue(Path(outs[0]).exists())
                self.assertEqual(len(captured), 2, "2-pass compression should execute pass 1 and pass 2")
        finally:
            dlg.deleteLater()

    def test_tier3_audio_equalizer_vocal_boost_with_date_rename(self):
        """Equalizer Vocal Boost with date rename."""
        src = self._create_sample_file("audio.wav")
        dlg = FormDialog(tools.BY_ID["eq"], self.st, preview_paths=[str(src)])
        try:
            dlg.widgets["preset"].setCurrentText("Vocal Boost")
            dlg.rename_edit.setText("{name}_{date}")
            params = dlg.values()
            with self.mock_ffmpeg_and_probe() as captured:
                outs, errs = tools.run_tool("eq", [str(src)], params, self.st)
                self.assertEqual(len(outs), 1)
                self.assertEqual(errs, [])
                self.assertTrue(Path(outs[0]).exists())
                af = captured[0][captured[0].index("-filter:a") + 1]
                self.assertIn("equalizer=f=1000", af)
        finally:
            dlg.deleteLater()

    def test_tier3_batch_video_conversion_with_numbered_rename_and_options(self):
        """Batch video conversion with numbered rename and options."""
        v1 = self._create_sample_file("vid1.mp4")
        v2 = self._create_sample_file("vid2.mp4")
        with self.mock_ffmpeg_and_probe() as captured:
            outs, errs = engine.convert_batch(
                [str(v1), str(v2)], "mp3", self.st,
                custom_name="Track_{num}", params={"volume": 150, "bass_preset": "Bass Boost"}
            )
            self.assertEqual(len(outs), 2)
            self.assertEqual(errs, [])
            self.assertTrue(Path(outs[0]).name.startswith("Track_"))
            self.assertTrue(Path(outs[1]).name.startswith("Track_"))
            self.assertEqual(len(captured), 2)
            for args in captured:
                af = args[args.index("-filter:a") + 1]
                self.assertIn("volume=1.50", af)
                self.assertIn("bass=g=8:f=100", af)


# ============================================================================
# Tier 4: Real-World Scenarios (5 tests)
# ============================================================================
class TestTier4RealWorldScenarios(UserRequirementsTestBase):
    """End-to-end simulated user workflows representing real customer use-cases."""

    def test_tier4_scenario_video_podcast_to_mp3_with_bass_and_low_volume(self):
        """Scenario 1: Video podcast to MP3 with bass boost and low volume (75%)."""
        podcast_vid = self._create_sample_file("interview_raw.mp4")
        dlg = ActionConfirmDialog("MP4 → MP3", [str(podcast_vid)], "mp3", is_conv=True)
        try:
            if hasattr(dlg, "vol_slider"):
                dlg.vol_slider.setValue(75)
            if hasattr(dlg, "eq_combo"):
                dlg.eq_combo.setCurrentText("Bass Boost (+8dB)")
            dlg.name_edit.setText("Podcast_Episode_01")
            vals = dlg.values()

            with self.mock_ffmpeg_and_probe() as captured:
                outs, errs = engine.convert_batch(
                    [str(podcast_vid)], "mp3", self.st,
                    custom_name=vals["custom_name"], params=vals
                )
                self.assertEqual(len(outs), 1)
                self.assertEqual(errs, [])
                self.assertEqual(Path(outs[0]).name, "Podcast_Episode_01.mp3")
                af = captured[0][captured[0].index("-filter:a") + 1]
                self.assertIn("volume=0.75", af)
                self.assertIn("bass=g=8:f=100", af)
        finally:
            dlg.deleteLater()

    def test_tier4_scenario_user_drops_audio_on_volume_boost_tool(self):
        """Scenario 2: User drops voice recording on volume boost tool with 250% boost."""
        voice = self._create_sample_file("voice_note.wav")
        dlg = FormDialog(tools.BY_ID["volume"], self.st, preview_paths=[str(voice)])
        try:
            self.assertIsNotNone(dlg.rename_edit, "FormDialog should open cleanly on file drop without NameError")
            if "volume" in dlg.widgets:
                dlg.widgets["volume"].setValue(250)
            dlg.rename_edit.setText("VoiceBoosted")
            params = dlg.values()

            with self.mock_ffmpeg_and_probe() as captured:
                outs, errs = tools.run_tool("volume", [str(voice)], params, self.st)
                self.assertEqual(len(outs), 1)
                self.assertEqual(errs, [])
                self.assertTrue(Path(outs[0]).name.startswith("VoiceBoosted"))
                af = captured[0][captured[0].index("-filter:a") + 1]
                self.assertIn("volume=2.50", af)
        finally:
            dlg.deleteLater()

    def test_tier4_scenario_all_11_video_tools_selectable_on_wheel(self):
        """Scenario 3: All 11 video tools selectable on wheel (including 11th inspect tool)."""
        vid = self._create_sample_file("gameplay.mp4")
        w = Wheel(self.st)
        try:
            w.set_content("tools", [str(vid)])
            self.assertGreaterEqual(len(w.items), 11)
            item_11 = w.items[10]
            self.assertEqual(item_11[0], "inspect", "11th tool must be inspect")

            chosen_events = []
            w.chosen.connect(lambda k, i, p: chosen_events.append((k, i, p)))
            lx = w._layout_cache[10]["lx"]
            ly = w._layout_cache[10]["ly"]
            m_event = QMouseEvent(QEvent.MouseButtonPress, QPointF(lx, ly), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            qt_app.sendEvent(w, m_event)
            qt_app.processEvents()

            self.assertEqual(len(chosen_events), 1)
            self.assertEqual(chosen_events[0], ("tools", "inspect", [str(vid)]))
        finally:
            w.deleteLater()

    def test_tier4_scenario_wheel_resilient_to_background_activation_switches(self):
        """Scenario 4: Wheel resilient to background activation switches."""
        vid = self._create_sample_file("screencast.mp4")
        w = Wheel(self.st)
        try:
            w.present("tools", [str(vid)], 500, 500, interactive=True)
            self.assertTrue(w.isVisible())

            # Simulate Windows focus changes
            qt_app.sendEvent(w, QEvent(QEvent.ActivationChange))
            qt_app.sendEvent(w, QEvent(QEvent.WindowDeactivate))
            self.assertTrue(w.isVisible(), "Wheel should remain visible through external focus shifts")

            # User intentionally dismisses via Escape key
            k_esc = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
            qt_app.sendEvent(w, k_esc)
            self.assertFalse(w.isVisible(), "Escape dismisses wheel on demand")
        finally:
            w.deleteLater()

    def test_tier4_scenario_batch_media_conversion_with_complete_options_pipeline(self):
        """Scenario 5: Batch media conversion with complete options pipeline."""
        s1 = self._create_sample_file("scene1.mp4")
        s2 = self._create_sample_file("scene2.mp4")
        s3 = self._create_sample_file("scene3.mp4")
        params = {
            "volume": 120,
            "bass_preset": "Loudness & Clarity",
            "bitrate_k": 160,
            "custom_name": "Scene_{num}"
        }

        with self.mock_ffmpeg_and_probe() as captured:
            outs, errs = engine.convert_batch(
                [str(s1), str(s2), str(s3)], "m4a", self.st,
                custom_name=params["custom_name"], params=params
            )
            self.assertEqual(len(outs), 3)
            self.assertEqual(errs, [])
            self.assertEqual(len(captured), 3)
            for args in captured:
                af = args[args.index("-filter:a") + 1]
                self.assertIn("loudnorm", af)
                self.assertIn("volume=1.20", af)
                self.assertIn("-b:a", args)
                self.assertEqual(args[args.index("-b:a") + 1], "160k")


if __name__ == "__main__":
    unittest.main()
