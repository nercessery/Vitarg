"""Tests for Milestone 2: Options Dialogs & Engine Parameterization."""
import gc
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication

def get_app():
    return QApplication.instance() or QApplication([])

from vitarg import engine, tools
from vitarg.dialogs import ActionConfirmDialog, FormDialog
from vitarg.engine import _audio_filters
from vitarg.settings import Settings


class TestMilestone2Options(unittest.TestCase):
    def setUp(self):
        self.app = get_app()
        self.td = tempfile.mkdtemp(prefix="vitarg_m2_test_")
        self.settings = Settings()

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)
        gc.collect()
        self.app.processEvents()

    def _create_sine_wav(self, name="tone.wav", duration=1.0) -> Path:
        p = Path(self.td) / name
        ff = engine.need_tool("ffmpeg")
        cmd = [
            ff, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:a", "pcm_s16le", str(p)
        ]
        subprocess.run(cmd, check=True, capture_output=True, creationflags=engine.NOWIN)
        return p

    def test_01_form_dialog_path_import_and_preset_isolation(self):
        """FormDialog imports Path properly and does not collide settings.compress_preset with target_compress/eq."""
        # 1. Path import test: instantiating FormDialog with preview_paths does not raise NameError
        p = self.td + "\\dummy.png"
        Path(p).write_bytes(b"")
        dlg_vol = FormDialog(tools.BY_ID["volume"], self.settings, preview_paths=[p])
        self.assertIsNotNone(dlg_vol.rename_edit)

        # 2. Preset collision test:
        st = Settings()
        st.compress_preset = "Strong"

        dlg_tc = FormDialog(tools.BY_ID["target_compress"], st)
        self.assertEqual(dlg_tc.widgets["preset"].currentText(), "25 MB")

        dlg_eq = FormDialog(tools.BY_ID["eq"], st)
        self.assertEqual(dlg_eq.widgets["preset"].currentText(), "Bass Boost (+8dB)")

        dlg_cp = FormDialog(tools.BY_ID["compress"], st)
        self.assertEqual(dlg_cp.widgets["preset"].currentText(), "Strong")

        for d in (dlg_vol, dlg_tc, dlg_eq, dlg_cp):
            d.deleteLater()

    def test_02_action_confirm_dialog_options_and_values_contract(self):
        """ActionConfirmDialog presents volume/eq/bitrate options for audio/video targets and exposes values()."""
        # Audio target: mp3
        dlg = ActionConfirmDialog("MP4 → MP3", ["test_media.mp4"], "mp3", is_conv=True, settings=self.settings)
        self.assertTrue(dlg.has_audio_options)
        self.assertTrue(dlg.is_audio_target)
        self.assertEqual(dlg.vol_slider.value(), 100)
        self.assertEqual(dlg.vol_spin.value(), 100)
        self.assertIn("Normal", dlg.vol_status.text())
        self.assertEqual(dlg.eq_combo.currentText(), "Flat (Original)")
        self.assertEqual(dlg.bitrate_combo.currentText(), "192 kbps (Standard)")

        # Test dynamic volume label and synchronization
        dlg.vol_slider.setValue(200)
        self.assertEqual(dlg.vol_spin.value(), 200)
        self.assertIn("+100% Boost", dlg.vol_status.text())

        dlg.vol_slider.setValue(60)
        self.assertEqual(dlg.vol_spin.value(), 60)
        self.assertIn("-40% Lower", dlg.vol_status.text())

        dlg.vol_slider.setValue(100)
        self.assertEqual(dlg.vol_spin.value(), 100)
        self.assertIn("Normal", dlg.vol_status.text())

        # Test values() contract
        vals = dlg.values()
        self.assertEqual(vals["custom_name"], "test_media")
        self.assertEqual(vals["volume"], 100)
        self.assertEqual(vals["bass_preset"], "Flat (Original)")
        self.assertEqual(vals["bitrate_k"], 192)

        # Mutate options
        dlg.vol_spin.setValue(150)
        dlg.eq_combo.setCurrentText("Bass Boost (+8dB)")
        dlg.bitrate_combo.setCurrentText("320 kbps (High Quality)")
        dlg.name_edit.setText("my_custom_song")

        vals2 = dlg.values()
        self.assertEqual(vals2["custom_name"], "my_custom_song")
        self.assertEqual(vals2["volume"], 150)
        self.assertEqual(vals2["bass_preset"], "Bass Boost (+8dB)")
        self.assertEqual(vals2["bitrate_k"], 320)
        self.assertEqual(dlg.output_name(), "my_custom_song")

        # Non-audio target (e.g. PNG to JPG)
        dlg_img = ActionConfirmDialog("PNG → JPG", ["photo.png"], "jpg", is_conv=True)
        self.assertFalse(dlg_img.has_audio_options)
        vals_img = dlg_img.values()
        self.assertEqual(vals_img, {"custom_name": "photo"})
        dlg.deleteLater()
        dlg_img.deleteLater()

    def test_03_engine_audio_filters_helper(self):
        """_audio_filters constructs valid FFmpeg filter strings across volume, presets, and combinations."""
        # Defaults / empty
        self.assertEqual(_audio_filters(None), [])
        self.assertEqual(_audio_filters({}), [])
        self.assertEqual(_audio_filters({"volume": 100, "bass_preset": "Flat (Original)"}), [])

        # Volume only
        self.assertEqual(_audio_filters({"volume": 150}), ["-filter:a", "volume=1.50"])
        self.assertEqual(_audio_filters({"volume": 80}), ["-filter:a", "volume=0.80"])

        # Preset only
        self.assertEqual(_audio_filters({"bass_preset": "Bass Boost (+8dB)"}), ["-filter:a", "bass=g=8:f=100"])
        self.assertEqual(_audio_filters({"bass_preset": "Ultra Bass (+14dB)"}), ["-filter:a", "bass=g=14:f=80,volume=1.2"])
        vocal_af = _audio_filters({"bass_preset": "Vocal Boost"})
        self.assertIn("equalizer=f=1000", vocal_af[1])
        treble_af = _audio_filters({"bass_preset": "Treble Boost"})
        self.assertIn("treble=g=8:f=4000", treble_af[1])
        loudness_af = _audio_filters({"bass_preset": "Loudness & Clarity"})
        self.assertIn("loudnorm=", loudness_af[1])

        # Combined Volume + Preset
        comb = _audio_filters({"volume": 200, "bass_preset": "Bass Boost (+8dB)"})
        self.assertEqual(comb, ["-filter:a", "volume=2.00,bass=g=8:f=100"])

        # Direct bass_gain fallback
        bg = _audio_filters({"bass_gain": 6.5})
        self.assertEqual(bg, ["-filter:a", "bass=g=6.5:f=100"])

    def test_04_engine_convert_with_params(self):
        """engine.convert and convert_batch honor volume, bass, and bitrate params during audio conversion."""
        wav = self._create_sine_wav("test_sine.wav", 1.0)

        # 1. Parameterized conversion (Volume 150%, Bass Boost, 320 kbps)
        outs = engine.convert(
            wav, "mp3", self.settings,
            params={"volume": 150, "bass_preset": "Bass Boost (+8dB)", "bitrate_k": 320}
        )
        self.assertEqual(len(outs), 1)
        self.assertTrue(outs[0].exists())
        probe_res = engine.probe(outs[0])
        self.assertTrue(probe_res["audio"])

        # 2. Batch parameterized conversion
        outs_b, errs_b = engine.convert_batch(
            [str(wav)], "mp3", self.settings,
            params={"volume": 120, "bass_preset": "Flat (Original)"}
        )
        self.assertEqual(len(errs_b), 0)
        self.assertEqual(len(outs_b), 1)

    def test_05_tools_multi_parameter_volume_and_eq(self):
        """volume and eq tools in vitarg/tools.py accept both volume and preset simultaneously."""
        # 1. Schema check
        vol_tool = tools.BY_ID["volume"]
        self.assertTrue(any(f["key"] == "volume" for f in vol_tool.form))
        self.assertTrue(any(f["key"] == "preset" for f in vol_tool.form))

        eq_tool = tools.BY_ID["eq"]
        self.assertTrue(any(f["key"] == "preset" for f in eq_tool.form))
        self.assertTrue(any(f["key"] == "volume" for f in eq_tool.form))

        # 2. Execution check
        wav = self._create_sine_wav("tool_test.wav", 1.0)

        # Volume tool with EQ preset
        outs_v, errs_v = tools.run_tool("volume", [wav], {"volume": 180, "preset": "Bass Boost (+8dB)"}, self.settings)
        self.assertEqual(errs_v, [])
        self.assertEqual(len(outs_v), 1)
        self.assertTrue(outs_v[0].exists())

        # EQ tool with volume boost
        outs_eq, errs_eq = tools.run_tool("eq", [wav], {"preset": "Ultra Bass (+14dB)", "volume": 140}, self.settings)
        self.assertEqual(errs_eq, [])
        self.assertEqual(len(outs_eq), 1)
        self.assertTrue(outs_eq[0].exists())

        # 3. Preview text check
        _, txt1 = tools.make_preview("volume", [wav], {"volume": 200, "preset": "Bass Boost (+8dB)"})
        self.assertIn("200%", txt1)
        self.assertIn("Bass Boost", txt1)

        _, txt2 = tools.make_preview("eq", [wav], {"preset": "Treble Boost", "volume": 150})
        self.assertIn("Treble Boost", txt2)
        self.assertIn("150%", txt2)

    def test_06_controller_parameter_routing(self):
        """Controller.on_choice routes dialog parameters to engine.convert_batch."""
        from vitarg.app import Controller

        st = Settings()
        st.prompt_rename = True
        st.auto_update = False

        with patch("vitarg.app.DragMonitor"), \
             patch("vitarg.app.Wheel"), \
             patch("vitarg.app.QLocalServer"), \
             patch("vitarg.app.QSystemTrayIcon"):

            ctl = Controller(self.app, st)

            with patch("vitarg.app.ActionConfirmDialog") as MockDialog, \
                 patch("vitarg.engine.convert_batch") as mock_batch, \
                 patch("vitarg.app.JobWindow") as MockJob:

                dlg_inst = MagicMock()
                dlg_inst.exec.return_value = True
                dlg_inst.values.return_value = {
                    "custom_name": "custom_song",
                    "volume": 250,
                    "bass_preset": "Ultra Bass (+14dB)",
                    "bitrate_k": 320
                }
                dlg_inst.output_name.return_value = "custom_song"
                MockDialog.return_value = dlg_inst

                ctl.on_choice("conv", "mp3", ["input.mp4"])

                # Verify JobWindow was instantiated with custom_name
                MockJob.assert_called_once()
                call_kwargs = MockJob.call_args[1]
                self.assertEqual(call_kwargs["custom_name"], "custom_song")

                # Execute the background worker function passed to JobWindow
                worker_fn = MockJob.call_args[0][2]
                worker_fn(lambda f: None, None)

                # Verify convert_batch was called with the collected params
                mock_batch.assert_called_once()
                batch_kwargs = mock_batch.call_args[1]
                self.assertEqual(batch_kwargs["custom_name"], "custom_song")
                self.assertIsNotNone(batch_kwargs["params"])
                self.assertEqual(batch_kwargs["params"]["volume"], 250)
                self.assertEqual(batch_kwargs["params"]["bass_preset"], "Ultra Bass (+14dB)")
                self.assertEqual(batch_kwargs["params"]["bitrate_k"], 320)


if __name__ == "__main__":
    unittest.main()
