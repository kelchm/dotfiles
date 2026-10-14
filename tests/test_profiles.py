"""Exercise real chezmoi renders/applies without touching the user's home."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHEZMOI = os.environ.get("CHEZMOI") or shutil.which("chezmoi")
MODULES = ("desktop", "git", "agents", "tools", "runtimes", "shell", "prompt", "terminal", "editor", "packages")


@unittest.skipUnless(CHEZMOI, "install chezmoi or set CHEZMOI to its executable")
class Profiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.config = self.base / "chezmoi.toml"
        self.platform = "linux"

    def configure(self, profile="omarchy", *, bootstrap=False, **overrides):
        standalone = profile == "standalone"
        data = dict(profile=profile, name="Test User", email="test@example.com",
                    signingMethod="none", signingKey="", sshAgent="system",
                    bootstrap=bootstrap)
        modules = {m: (standalone or m in {"git", "agents", "tools"}) and m != "desktop" for m in MODULES}
        modules.update(overrides.pop("modules", {}))
        data.update(overrides)
        text = "[data]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in data.items())
        text += "[data.modules]\n" + "".join(f"{k} = {str(v).lower()}\n" for k, v in modules.items())
        text += '[data.desktop]\nnaturalScroll = true\nkeyboardOptions = "ctrl:nocaps,shift:both_capslock_cancel,altwin:swap_lalt_lwin"\nborderSize = 1\n'
        self.config.write_text(text)

    def chezmoi(self, *args, check=True):
        override = json.dumps({"chezmoi": {"os": self.platform}})
        result = subprocess.run(
            [CHEZMOI, "-S", str(ROOT), "-D", str(self.home), "-c", str(self.config),
             "--persistent-state", str(self.base / "state.boltdb"),
             "--cache", str(self.base / "cache"), "--no-tty", "--override-data", override, *args],
            text=True, capture_output=True,
        )
        if check and result.returncode:
            self.fail(f"chezmoi {' '.join(args)} failed:\n{result.stderr}\n{result.stdout}")
        return result

    def seed(self, target, text):
        p = self.home / target
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def apply(self):
        self.chezmoi("apply", "--exclude", "scripts", "--force")

    def test_omarchy_preserves_system_owned_files_and_tools(self):
        self.configure()
        stock = [".bashrc", ".bash_profile", ".profile", ".config/starship.toml",
                 ".config/ghostty/config", ".config/hypr/hyprland.lua",
                 ".config/fish/config.fish", ".vscode/settings.json"]
        for target in stock:
            self.seed(target, "stock config\n")
        mise = self.seed(".config/mise/config.toml", '''# local tools
[tools]
node = "26.8.2"
ruby = "3.4"
"aqua:cli/cli" = "2.101.0"
"npm:@opencode/cli" = "latest"
[env]
LOCAL = "keep"
[settings]
minimum_release_age = "24h"
[settings.upgrade]
auto_prune = false
[tasks.local]
run = "echo keep"
''')
        for tool_dir in [".agents/skills", ".codex/skills", ".claude/skills", ".pi/agent/skills"]:
            p = self.home / tool_dir / "omarchy"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.symlink_to("/usr/share/omarchy/default/agents/skills/omarchy")
        self.apply()
        for target in stock:
            self.assertEqual((self.home / target).read_text(), "stock config\n")
        config = tomllib.loads(mise.read_text())
        self.assertEqual(config["tools"]["node"], "26.8.2")
        self.assertEqual(config["tools"]["ruby"], "3.4")
        self.assertEqual(config["tools"]["gh"], "latest")
        self.assertNotIn("aqua:cli/cli", config["tools"])
        self.assertNotIn("npm:@opencode/cli", config["tools"])
        self.assertEqual(config["env"]["LOCAL"], "keep")
        self.assertEqual(config["settings"]["minimum_release_age"], "24h")
        self.assertFalse(config["settings"]["upgrade"]["auto_prune"])
        self.assertEqual(config["tasks"]["local"]["run"], "echo keep")
        self.assertEqual(config["tasks"]["harness:update"]["env"]["MISE_MINIMUM_RELEASE_AGE"], "0")
        for harness in [".claude/skills", ".codex/skills", ".pi/agent/skills"]:
            self.assertTrue((self.home / harness / "omarchy").is_symlink())
            self.assertEqual((self.home / harness / "pr-monitor").resolve(),
                             self.home / ".agents/skills/pr-monitor")
        first = mise.read_bytes()
        self.apply()
        self.assertEqual(mise.read_bytes(), first)
        self.chezmoi("verify", "--exclude", "scripts")

    def test_mise_keeps_comments_when_already_compliant(self):
        self.configure()
        self.apply()
        p = self.home / ".config/mise/config.toml"
        p.write_text("# personal comment\n" + p.read_text())
        text = p.read_bytes()
        self.apply()
        self.assertEqual(p.read_bytes(), text)

    def test_standalone_platforms_and_bootstrap_render(self):
        for platform in ["linux", "darwin", "windows"]:
            with self.subTest(platform=platform):
                self.platform = platform
                self.configure("standalone", bootstrap=True)
                managed = self.chezmoi("managed").stdout.splitlines()
                self.assertIn(".config/starship.toml", managed)
                self.assertFalse(any("/tests/" in target for target in managed))
                self.assertFalse(any("build-onedark-theme" in target for target in managed))
                self.assertEqual(".bashrc" in managed, platform != "windows")
                self.assertEqual(".config/iterm2/com.googlecode.iterm2.plist" in managed, platform == "darwin")
                self.assertEqual("Documents/PowerShell/profile.ps1" in managed, platform == "windows")
                body = self.chezmoi("cat", str(self.home / ".config/mise/config.toml")).stdout
                config = tomllib.loads(body)
                self.assertEqual(config["tools"]["node"], "lts")
                self.assertEqual(config["tools"]["python"], "3.12")
                self.assertEqual(config["tools"]["aqua:cli/cli"], "2.101.0")
                self.assertNotIn("minimum_release_age", config.get("settings", {}))
                for script in sorted((ROOT / "home/.chezmoiscripts").glob("run*.sh.tmpl")):
                    result = self.chezmoi("execute-template", "-f", str(script)).stdout
                    syntax = subprocess.run(["bash", "-n"], input=result, text=True, capture_output=True)
                    self.assertEqual(syntax.returncode, 0, syntax.stderr)
                script = ROOT / "home/.chezmoiscripts/run_onchange_02-install-mise-tools.ps1.tmpl"
                ps1 = self.chezmoi("execute-template", "-f", str(script)).stdout
                self.assertEqual(bool(ps1.strip()), platform == "windows")

    def test_disabled_modules_and_bootstrap(self):
        self.configure(modules={m: False for m in MODULES})
        self.apply()
        for target in [".gitconfig", ".codex/AGENTS.md", ".config/mise/config.toml"]:
            self.assertFalse((self.home / target).exists())
        for script in sorted((ROOT / "home/.chezmoiscripts").glob("run*.tmpl")):
            self.assertFalse(self.chezmoi("execute-template", "-f", str(script)).stdout.strip())
        self.chezmoi("init")
        data = tomllib.loads(self.config.read_text())["data"]
        self.assertTrue(all(v is False for v in data["modules"].values()))
        self.assertFalse(data["bootstrap"])

    def test_invalid_module_combinations_fail_initialization(self):
        self.configure(modules={"runtimes": True, "tools": False})
        result = self.chezmoi("init", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtimes module requires", result.stderr)
        self.configure("standalone", modules={"desktop": True})
        result = self.chezmoi("init", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("desktop module requires", result.stderr)

    def test_profile_defaults_and_existing_identity_survive_init(self):
        for profile in ["omarchy", "standalone"]:
            with self.subTest(profile=profile):
                self.config.write_text(f'''[data]
profile = "{profile}"
email = "existing@example.com"
signingMethod = "none"
''')
                self.chezmoi("init")
                data = tomllib.loads(self.config.read_text())["data"]
                self.assertEqual(data["email"], "existing@example.com")
                self.assertEqual(data["modules"]["shell"], profile == "standalone")
                self.assertEqual(data["modules"]["runtimes"], profile == "standalone")
                self.assertTrue(data["modules"]["agents"])

    def test_ssh_agent_merge_idempotence_and_opt_out(self):
        self.configure(sshAgent="1password")
        original = "Host github.com\n    User git\n    IdentityFile ~/.ssh/custom\n"
        p = self.seed(".ssh/config", original)
        self.apply()
        text = p.read_text()
        self.assertTrue(text.endswith(original))
        self.assertIn('IdentityAgent "~/.1password/agent.sock"', text)
        parsed = subprocess.run(["ssh", "-G", "-F", str(p), "github.com"], text=True, capture_output=True)
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.assertIn("user git\n", parsed.stdout)
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.apply()
        self.assertEqual(p.read_text(), text)
        self.configure(sshAgent="system")
        self.apply()
        self.assertEqual(p.read_text(), original)

    def test_opencode_merge_keeps_local_providers_and_defaults(self):
        self.configure()
        p = self.seed(".config/opencode/opencode.jsonc", '''{
// local settings
"enabled_providers": ["custom"], "disabled_providers": ["opencode-go", "other"],
"provider": {"custom": {"name": "Private"}}, "model": "custom/mine"
}''')
        self.apply()
        data = json.loads(p.read_text())
        self.assertEqual(data["model"], "custom/mine")
        self.assertEqual(data["enabled_providers"], ["custom", "opencode-go"])
        self.assertEqual(data["disabled_providers"], ["other"])
        first = p.read_bytes()
        self.apply()
        self.assertEqual(p.read_bytes(), first)

    def test_desktop_is_opt_in_and_leaves_monitor_and_bootstrap_local(self):
        self.configure(modules={"desktop": True})
        main = self.seed(".config/hypr/hyprland.lua", "stock bootstrap\n")
        monitor = self.seed(".config/hypr/monitors.lua", "machine monitor\n")
        self.apply()
        self.assertEqual(main.read_text(), "stock bootstrap\n")
        self.assertEqual(monitor.read_text(), "machine monitor\n")
        self.assertIn("natural_scroll = true", (self.home / ".config/hypr/input.lua").read_text())
        self.assertIn("border_size = 1", (self.home / ".config/hypr/looknfeel.lua").read_text())
        self.configure(modules={"desktop": False})
        managed = self.chezmoi("managed").stdout
        self.assertNotIn(".config/hypr/input.lua", managed)

    def test_generated_python_caches_are_not_deployed(self):
        self.configure()
        managed = self.chezmoi("managed").stdout
        self.assertNotIn("__pycache__", managed)
        self.assertNotIn(".pyc", managed)

    def test_git_include_preserves_credentials_and_overrides_identity(self):
        self.configure()
        original = '[credential "https://github.com"]\n    helper = !gh auth git-credential\n[user]\n    email = old@example.com\n'
        p = self.seed(".gitconfig", original)
        self.apply()
        self.assertTrue(p.read_text().startswith(original))
        config = subprocess.run(["git", "config", "--includes", "--file", str(p), "--get", "user.email"], text=True, capture_output=True)
        self.assertEqual(config.stdout.strip(), "test@example.com")
        first = p.read_bytes()
        self.apply()
        self.assertEqual(p.read_bytes(), first)
        self.assertEqual(p.read_text().count("# BEGIN dotfiles: personal Git configuration"), 1)

    def test_linux_signing_and_disabled_signing(self):
        self.configure(signingMethod="ssh", signingKey="ssh-ed25519 AAAATEST example")
        self.apply()
        p = self.home / ".config/git/dotfiles.gitconfig"
        config = subprocess.run(["git", "config", "--includes", "--file", str(self.home / ".gitconfig"), "--get", "user.signingkey"], text=True, capture_output=True)
        self.assertEqual(config.stdout.strip(), "ssh-ed25519 AAAATEST example")
        if Path("/opt/1Password/op-ssh-sign").exists():
            self.assertIn("program = /opt/1Password/op-ssh-sign", p.read_text())
        self.configure()
        self.apply()
        self.assertIn("gpgsign = false", p.read_text())


if __name__ == "__main__":
    unittest.main()
