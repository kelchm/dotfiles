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
DEFAULTS = tomllib.loads((ROOT / "home/.chezmoidata.toml").read_text())["dotfiles"]["profiles"]
MODULES = tuple(DEFAULTS["standalone"])


class Profiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CHEZMOI:
            raise RuntimeError("chezmoi is required; install it or set CHEZMOI to its executable")
        # Share downloaded externals across tests.
        cls.cache = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.cache.cleanup)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.config = self.base / "chezmoi.toml"
        self.platform = "linux"

    def configure(self, profile="omarchy", *, bootstrap=False, **overrides):
        data = dict(profile=profile, name="Test User", email="test@example.com",
                    signingMethod="none", signingKey="", sshAgent="system",
                    bootstrap=bootstrap)
        modules = dict(DEFAULTS[profile])
        modules.update(overrides.pop("modules", {}))
        data.update(overrides)
        text = "[data]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in data.items())
        text += "[data.modules]\n" + "".join(f"{k} = {str(v).lower()}\n" for k, v in modules.items())
        self.config.write_text(text)

    def chezmoi(self, *args, check=True, env=None):
        override = json.dumps({"chezmoi": {"os": self.platform}})
        result = subprocess.run(
            [CHEZMOI, "-S", str(ROOT), "-D", str(self.home), "-c", str(self.config),
             "--persistent-state", str(self.base / "state.boltdb"),
             "--cache", self.cache.name, "--no-tty", "--override-data", override, *args],
            text=True, capture_output=True, env=env,
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

    def test_retired_t3_status_cleanup_is_scoped_to_agents(self):
        template = (ROOT / "home/.chezmoiremove").read_text()
        target = ".agents/skills/t3-thread-search/scripts/t3-thread-status"
        for enabled in (False, True):
            with self.subTest(agents=enabled):
                self.configure(modules={"agents": enabled})
                rendered = self.chezmoi("execute-template", template).stdout.splitlines()
                self.assertEqual(target in rendered, enabled)

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
            for skill in ["pr-monitor", "gh-stack"]:
                self.assertEqual((self.home / harness / skill).resolve(),
                                 self.home / ".agents/skills" / skill)
        self.assertTrue((self.home / ".agents/skills/gh-stack/SKILL.md").is_file())
        first = mise.read_bytes()
        self.apply()
        self.assertEqual(mise.read_bytes(), first)
        self.chezmoi("verify", "--exclude", "scripts")

    def test_mise_retains_tool_options_when_updating_versions_and_aliases(self):
        self.configure(modules={"runtimes": True})
        p = self.seed(".config/mise/config.toml", '''
[tools.gh]
version = "2.80.0"
os = ["linux"]
[tools."aqua:cli/cli"]
version = "2.101.0"
install_env = { CUSTOM = "keep" }
[tools.python]
version = "3.11.9"
virtualenv = "/custom/venv"
[tools."npm:@opencode/cli"]
version = "latest"
extra_bins = ["opencode2"]
''')
        self.apply()
        tools = tomllib.loads(p.read_text())["tools"]
        self.assertEqual(tools["gh"]["version"], "latest")
        self.assertEqual(tools["gh"]["os"], ["linux"])
        self.assertEqual(tools["gh"]["install_env"], {"CUSTOM": "keep"})
        self.assertEqual(tools["python"], {"version": "3.12", "virtualenv": "/custom/venv"})
        self.assertEqual(tools["opencode"]["extra_bins"], ["opencode2"])
        first = p.read_bytes()
        self.apply()
        self.assertEqual(p.read_bytes(), first)

    def test_mise_keeps_comments_when_already_compliant(self):
        self.configure()
        self.apply()
        p = self.home / ".config/mise/config.toml"
        p.write_text("# personal comment\n" + p.read_text())
        text = p.read_bytes()
        self.apply()
        self.assertEqual(p.read_bytes(), text)

    def test_tools_re_is_off_by_default(self):
        for profile in DEFAULTS:
            with self.subTest(profile=profile):
                self.assertFalse(DEFAULTS[profile]["tools-re"])
                self.configure(profile)
                managed = self.chezmoi("managed").stdout
                self.assertNotIn("reverse-engineer-anything", managed)
                body = self.chezmoi("cat", str(self.home / ".config/mise/config.toml")).stdout
                config = tomllib.loads(body)
                self.assertNotIn("npm:rea-agents", config["tools"])
                external = self.chezmoi("execute-template", "-f", str(ROOT / "home/.chezmoiexternal.toml")).stdout
                self.assertNotIn("rea-agents", external)

    def test_tools_re_opt_in_and_opt_out_preserve_local_state(self):
        self.configure(modules={"tools-re": True})
        mise = self.seed(".config/mise/config.toml", '[tools]\nnode = "24.22.1"\nruby = "3.4"\n')
        local = self.seed(".codex/config.toml", '[mcp_servers.local]\ncommand = "local-server"\n')
        original = local.read_bytes()
        self.apply()
        config = tomllib.loads(mise.read_text())
        pin = tomllib.loads((ROOT / "home/.chezmoidata.toml").read_text())["dotfiles"]["pins"]["rea"]
        self.assertEqual(config["tools"]["npm:rea-agents"]["version"], pin)
        self.assertEqual(config["tools"]["node"], "24.22.1")
        self.assertEqual(config["tools"]["ruby"], "3.4")
        skill = self.home / ".agents/skills/reverse-engineer-anything"
        self.assertIn("name: reverse-engineer-anything", (skill / "SKILL.md").read_text())
        self.assertTrue((skill / "references/connection-and-recovery.md").is_file())
        for harness in [".claude/skills", ".codex/skills", ".pi/agent/skills"]:
            self.assertEqual((self.home / harness / skill.name).resolve(), skill.resolve())
        self.assertEqual(local.read_bytes(), original)
        first = mise.read_bytes()
        self.apply()
        self.assertEqual(mise.read_bytes(), first)
        self.chezmoi("verify", "--exclude", "scripts")
        self.configure()
        self.apply()
        self.assertNotIn("reverse-engineer-anything", self.chezmoi("managed").stdout)
        self.assertEqual(mise.read_bytes(), first)
        self.assertTrue((skill / "SKILL.md").is_file())
        self.assertEqual(local.read_bytes(), original)

    def test_tools_re_cli_can_be_used_without_agent_configuration(self):
        self.configure(modules={"tools-re": True, "agents": False})
        self.apply()
        config = tomllib.loads((self.home / ".config/mise/config.toml").read_text())
        self.assertIn("npm:rea-agents", config["tools"])
        self.assertFalse((self.home / ".agents").exists())
        self.assertFalse((self.home / ".codex").exists())
        external = self.chezmoi("execute-template", "-f", str(ROOT / "home/.chezmoiexternal.toml")).stdout
        self.assertNotIn("rea-agents", external)

    def test_tools_re_requires_tools(self):
        self.configure("standalone", modules={"tools-re": True, "tools": False, "runtimes": False})
        for args in [("init",), ("managed",)]:
            result = self.chezmoi(*args, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("tools-re module requires the tools module", result.stderr)

    def test_tools_re_choice_survives_init(self):
        self.configure("standalone", modules={"tools-re": True})
        self.chezmoi("init")
        data = tomllib.loads(self.config.read_text())["data"]
        self.assertTrue(data["modules"]["tools-re"])

    def test_standalone_platforms_and_bootstrap_render(self):
        for platform in ["linux", "darwin", "windows"]:
            with self.subTest(platform=platform):
                self.platform = platform
                self.configure("standalone", bootstrap=True, modules={"tools-re": True})
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
                self.assertIn("npm:rea-agents", config["tools"])
                self.assertNotIn("minimum_release_age", config.get("settings", {}))
                for script in sorted((ROOT / "home/.chezmoiscripts").glob("run*.sh.tmpl")):
                    result = self.chezmoi("execute-template", "-f", str(script)).stdout
                    syntax = subprocess.run(["bash", "-n"], input=result, text=True, capture_output=True)
                    self.assertEqual(syntax.returncode, 0, syntax.stderr)
                script = ROOT / "home/.chezmoiscripts/run_onchange_after_02-install-mise-tools.ps1.tmpl"
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
        managed = self.chezmoi("managed", "--exclude", "scripts").stdout.splitlines()
        self.assertEqual(managed, [])

    def test_invalid_module_combinations_fail_initialization(self):
        self.configure(modules={"runtimes": True, "tools": False})
        result = self.chezmoi("init", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtimes module requires", result.stderr)
        result = self.chezmoi("managed", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtimes module requires", result.stderr)
        self.configure("standalone", modules={"desktop": True})
        result = self.chezmoi("init", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("desktop module requires", result.stderr)
        result = self.chezmoi("managed", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("desktop module requires", result.stderr)

    def test_unknown_module_names_fail_instead_of_silently_ignoring_opt_outs(self):
        self.configure(modules={"terminals": False})
        for args in [("init",), ("managed",)]:
            result = self.chezmoi(*args, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unknown module "terminals"', result.stderr)

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
                self.assertFalse(data["modules"]["tools-re"])

    def test_owned_blocks_survive_external_crlf_rewrites(self):
        self.configure(sshAgent="1password")
        self.apply()
        for target in [".gitconfig", ".ssh/config"]:
            p = self.home / target
            p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        self.apply()
        self.assertEqual((self.home / ".gitconfig").read_text().count("# BEGIN dotfiles:"), 1)
        self.assertEqual((self.home / ".ssh/config").read_text().count("# BEGIN dotfiles:"), 1)
        self.configure(sshAgent="system")
        self.apply()
        ssh_config = self.home / ".ssh/config"
        self.assertFalse(ssh_config.exists())

    def test_init_does_not_pin_an_editor(self):
        self.configure()
        self.chezmoi("init")
        self.assertNotIn("edit", tomllib.loads(self.config.read_text()))

    def test_preinit_config_has_an_actionable_error(self):
        self.config.write_text('[data]\nprofile = "omarchy"\n')
        result = self.chezmoi("managed", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Run chezmoi init", result.stderr)

    def test_ssh_agent_merge_idempotence_and_opt_out(self):
        self.configure(sshAgent="1password")
        original = "Host github.com\n    User git\n    IdentityFile ~/.ssh/custom\n"
        p = self.seed(".ssh/config", original)
        self.apply()
        text = p.read_text()
        self.assertTrue(text.startswith(original))
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

    def test_opencode_uses_existing_json_without_creating_jsonc(self):
        self.configure()
        original = '{"theme":"omarchy","autoupdate":false}\n'
        p = self.seed(".config/opencode/opencode.json", original)
        self.apply()
        self.assertEqual(p.read_text(), original)
        self.assertFalse((self.home / ".config/opencode/opencode.jsonc").exists())
        p.write_text('{"enabled_providers":["custom"],"theme":"omarchy"}')
        self.apply()
        data = json.loads(p.read_text())
        self.assertEqual(data["enabled_providers"], ["custom", "opencode-go"])
        self.assertEqual(data["theme"], "omarchy")
        self.assertFalse((self.home / ".config/opencode/opencode.jsonc").exists())

    def test_opencode_non_array_provider_fields_do_not_abort_apply(self):
        self.configure()
        for value in [None, "custom"]:
            original = json.dumps({"enabled_providers": value, "disabled_providers": value, "model": "custom/mine"})
            p = self.seed(".config/opencode/opencode.jsonc", original)
            self.apply()
            self.assertEqual(p.read_text(), original)
            self.assertTrue((self.home / ".gitconfig").exists())

    def test_agent_only_rtk_cleanup_skips_a_missing_mise(self):
        self.platform = "darwin"
        self.configure("standalone", bootstrap=True, modules={"tools": False, "runtimes": False})
        script = ROOT / "home/.chezmoiscripts/run_onchange_after_05-remove-rtk.sh.tmpl"
        rendered = self.chezmoi("execute-template", "-f", str(script)).stdout
        empty_path = self.base / "empty-bin"
        empty_path.mkdir()
        env = dict(os.environ, HOME=str(self.home), PATH=str(empty_path))
        result = subprocess.run([shutil.which("bash")], input=rendered, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_bootstrap_scripts_run_after_their_configuration_is_written(self):
        self.configure("standalone", bootstrap=True)
        bins = self.base / "bin"
        bins.mkdir()
        trace = self.base / "trace"
        (bins / "mise").write_text('#!/bin/sh\n[ "$1" = install ] && test -f "$HOME/.config/mise/config.toml" && echo configured >> "$TRACE"\nexit 0\n')
        (bins / "gh").write_text("#!/bin/sh\nexit 1\n")
        for stub in bins.iterdir():
            stub.chmod(0o755)
        env = dict(os.environ, HOME=str(self.home), PATH=f"{bins}:/usr/bin:/bin", TRACE=str(trace))
        self.chezmoi("apply", "--force", env=env)
        self.assertEqual(trace.read_text(), "configured\n")

    def test_missing_module_choice_requests_reinitialization(self):
        self.configure()
        self.config.write_text(self.config.read_text().replace("runtimes = false\n", ""))
        result = self.chezmoi("managed", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run chezmoi init", result.stderr)
        self.chezmoi("init")
        self.assertFalse(tomllib.loads(self.config.read_text())["data"]["modules"]["runtimes"])

    def test_rtk_cleanup_removes_global_request_before_uninstall(self):
        self.platform = "darwin"
        self.configure("standalone", bootstrap=True)
        script = ROOT / "home/.chezmoiscripts/run_onchange_after_05-remove-rtk.sh.tmpl"
        rendered = self.chezmoi("execute-template", "-f", str(script)).stdout
        bins = self.base / "bin"
        bins.mkdir()
        trace = self.base / "trace"
        rtk = bins / "rtk"
        rtk.write_text('#!/bin/sh\nprintf "rtk %s\\n" "$*" >> "$RTK_TRACE"\n')
        rtk.chmod(0o755)
        mise = bins / "mise"
        mise.write_text('#!/bin/sh\nprintf "mise %s\\n" "$*" >> "$RTK_TRACE"\nif [ "$1" = "where" ]; then\n [ "$RTK_PRESENT" = "yes" ] || exit 1\n printf "%s\\n" "$RTK_DIRECTORY"\nfi\n')
        mise.chmod(0o755)
        for present in ["yes", "no"]:
            with self.subTest(installed=present):
                trace.write_text("")
                env = dict(os.environ, HOME=str(self.home), PATH=f"{bins}:{os.environ['PATH']}", RTK_TRACE=str(trace), RTK_PRESENT=present, RTK_DIRECTORY=str(bins))
                subprocess.run(["bash"], input=rendered, env=env, text=True, capture_output=True, check=True)
                calls = trace.read_text().splitlines()
                self.assertIn("mise unuse --global --no-prune rtk", calls)
                if present == "yes":
                    self.assertLess(calls.index("mise unuse --global --no-prune rtk"), calls.index("mise uninstall --all rtk"))
                else:
                    self.assertNotIn("mise uninstall --all rtk", calls)

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
        input_lua = (self.home / ".config/hypr/input.lua").read_text()
        self.assertIn("natural_scroll = true", input_lua)
        self.assertIn('action = "workspace"', input_lua)
        self.assertIn("border_size = 1", (self.home / ".config/hypr/looknfeel.lua").read_text())
        self.configure(modules={"desktop": False})
        managed = self.chezmoi("managed").stdout
        self.assertNotIn(".config/hypr/input.lua", managed)

    def test_generated_python_caches_are_not_deployed(self):
        self.configure()
        managed = self.chezmoi("managed").stdout
        self.assertNotIn("__pycache__", managed)
        self.assertNotIn(".pyc", managed)

    def test_git_include_preserves_credentials(self):
        self.configure()
        original = '[credential "https://github.com"]\n    helper = !gh auth git-credential\n'
        p = self.seed(".gitconfig", original)
        self.apply()
        self.assertTrue(p.read_text().endswith(original))
        config = subprocess.run(["git", "config", "--includes", "--file", str(p), "--get", "user.email"], text=True, capture_output=True)
        self.assertEqual(config.stdout.strip(), "test@example.com")
        first = p.read_bytes()
        self.apply()
        self.assertEqual(p.read_bytes(), first)
        self.assertEqual(p.read_text().count("# BEGIN dotfiles: personal Git configuration"), 1)

    def test_windows_does_not_append_a_duplicate_credential_helper(self):
        self.platform = "windows"
        self.configure("standalone")
        p = self.seed(".gitconfig", '[credential]\n helper = manager\n')
        self.apply()
        helpers = subprocess.check_output(["git", "config", "--includes", "--file", str(p), "--get-all", "credential.helper"], text=True)
        self.assertEqual(helpers.splitlines(), ["manager"])

    def test_machine_git_identity_and_conditional_include_take_precedence(self):
        self.configure()
        corporate = self.base / "corporate.gitconfig"
        corporate.write_text('[user]\n email = work@example.com\n')
        work = self.base / "work"
        subprocess.run(["git", "init", str(work)], check=True, capture_output=True)
        self.seed(".gitconfig", f'[user]\n email = local@example.com\n[includeIf "gitdir:{work}/"]\n path = {corporate}\n')
        self.apply()
        env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"))
        identity = subprocess.check_output(["git", "-C", str(work), "config", "user.email"], env=env, text=True)
        self.assertEqual(identity.strip(), "work@example.com")
        identity = subprocess.check_output(["git", "config", "--global", "user.email"], env=env, text=True)
        self.assertEqual(identity.strip(), "local@example.com")

    def test_per_host_ssh_agent_takes_precedence_over_personal_default(self):
        self.configure(sshAgent="1password")
        p = self.seed(".ssh/config", 'Host isolated.example\n IdentityAgent none\n')
        self.apply()
        parsed = subprocess.check_output(["ssh", "-G", "-F", str(p), "isolated.example"], text=True, stderr=subprocess.DEVNULL)
        self.assertIn("identityagent none\n", parsed)
        parsed = subprocess.check_output(["ssh", "-G", "-F", str(p), "other.example"], text=True, stderr=subprocess.DEVNULL)
        self.assertIn("/.1password/agent.sock\n", parsed)

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
