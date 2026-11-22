"""Tests for the macOS hidden-display helper without creating a virtual display."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "home/dot_local/share/hidden-display/hidden-display.m"


class HiddenDisplaySource(unittest.TestCase):
    def test_source_is_generic(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("ritornel", text.lower())
        self.assertNotIn("offscreen", text.lower())
        self.assertIn('@"Hidden Display"', text)


@unittest.skipUnless(sys.platform == "darwin", "hidden-display builds and runs on macOS only")
class HiddenDisplayCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.build_dir.cleanup)
        cls.binary = Path(cls.build_dir.name) / "hidden-display"
        result = subprocess.run(
            [
                "clang",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fobjc-arc",
                "-framework",
                "Foundation",
                "-framework",
                "CoreGraphics",
                str(SOURCE),
                "-o",
                str(cls.binary),
            ],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"clang failed:\n{result.stderr}\n{result.stdout}")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state_dir = Path(self.temp.name)
        self.state_file = self.state_dir / "hidden-display"

    def run_cli(self, *args):
        env = dict(os.environ, HIDDEN_DISPLAY_STATE_DIR=str(self.state_dir))
        return subprocess.run(
            [str(self.binary), *args],
            env=env,
            text=True,
            capture_output=True,
        )

    def test_help_and_usage_errors(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                res = self.run_cli(flag)
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertIn("usage: hidden-display ensure | status | stop", res.stdout)

        for bad_args in ((), ("bogus",), ("status", "extra")):
            with self.subTest(args=bad_args):
                res = self.run_cli(*bad_args)
                self.assertEqual(res.returncode, 2)
                self.assertIn("usage: hidden-display ensure | status | stop", res.stderr)

    def test_empty_state(self):
        status = self.run_cli("status")
        self.assertEqual(status.returncode, 1)
        self.assertIn("not running", status.stdout)

        stop = self.run_cli("stop")
        self.assertEqual(stop.returncode, 0, stop.stderr)
        self.assertIn("not running", stop.stdout)

    def test_stale_dead_pid(self):
        self.state_file.write_text("pid=999999\ndisplay=42\norigin=100,200\n", encoding="utf-8")
        status = self.run_cli("status")
        self.assertEqual(status.returncode, 1)
        self.assertIn("not running", status.stdout)

        stop = self.run_cli("stop")
        self.assertEqual(stop.returncode, 0, stop.stderr)
        self.assertIn("not running", stop.stdout)
        self.assertFalse(self.state_file.exists())

    def test_recycled_live_non_daemon_pid_is_not_killed(self):
        sleeper = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
        for pid in (os.getpid(), sleeper.pid):
            with self.subTest(pid=pid):
                self.state_file.write_text(
                    f"pid={pid}\ndisplay=42\norigin=100,200\n", encoding="utf-8"
                )
                status = self.run_cli("status")
                self.assertEqual(status.returncode, 1)
                self.assertIn("not running", status.stdout)

                stop = self.run_cli("stop")
                self.assertEqual(stop.returncode, 0, stop.stderr)
                self.assertIn("not running", stop.stdout)
                self.assertFalse(self.state_file.exists())
                self.assertIsNone(sleeper.poll(), "stop must not kill a non-daemon process")

    def test_corrupt_state_files(self):
        cases = [
            "garbage\n",
            "pid=1\ndisplay=42\norigin=0,0\n",
            "pid=12345\ndisplay=0\norigin=0,0\n",
            "pid=12345\ndisplay=42\norigin=0,0\nextra=1\n",
            "",
        ]
        for body in cases:
            with self.subTest(body=body):
                self.state_file.write_text(body, encoding="utf-8")
                status = self.run_cli("status")
                self.assertEqual(status.returncode, 1)
                self.assertIn("not running", status.stdout)

                stop = self.run_cli("stop")
                self.assertEqual(stop.returncode, 0, stop.stderr)
                self.assertFalse(self.state_file.exists())


if __name__ == "__main__":
    unittest.main()
