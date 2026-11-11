---
name: remote-hosts
description: Work on hosts you reach over SSH. Use before scripting or polling a host, rebooting it, or changing its networking or SSH.
---

# Remote hosts

Commands you run over SSH have no terminal, and a command that doesn't return blocks you until your tool times out. Keep remote work short, bounded, and honest about failures.

- **Never wait on a prompt.** Use `-o BatchMode=yes -o ConnectTimeout=10`. If a login fails, find out why and tell the user. Don't retry unchanged, and never turn off host-key checking. The examples leave these options out to stay short.
- **Use one connection for a batch of work.** Send several steps in one `ssh`. When sampling a host, run a short, bounded loop on the host rather than calling `ssh` in a loop. When you need many separate calls to the host you're working on, share one connection between them. Each call still starts fresh on the host, so set the directory and environment you need in every call. Examples: [polling, batching, and sharing a connection](references/connections.md).
- **Keep every call short.** Each `ssh` call should finish well inside your tool's time limit. Where `timeout` is available, wrap anything that could hang in it: on the host for the command, and locally for the `ssh` call itself, since a stalled connection ignores the remote one.
- **Run long jobs detached, then check back.** Start them on the host with their output going to a log, note the PID, confirm from the log that the job started, and check back with short calls. Don't block on a job, and don't write a wait that only ends when the job finishes. Tell the user what is still running and how to stop it. Examples: [a long upgrade](references/long-jobs.md).
- **Quote for the right shell.** Your local shell expands the command before `ssh` sends it. Keep anything meant for the host in single quotes, and send longer logic as a script with a quoted heredoc (`ssh host bash -s <<'EOF'`).
- **Check the host's tools first.** Tools you expect may be missing or off `PATH`. Check once with `command -v`, and parse output locally when the tool only exists on your side.
- **Keep failures visible.** A pipeline reports its last command's status, so check the `ssh` result itself rather than `ssh … | head`. `a; b` reports only `b`'s status, so chain dependent steps with `&&` or `set -e`. Give `ssh` the `-n` flag inside `while read` loops and inside scripts sent over `ssh`, so it doesn't swallow their input. Examples: [hidden failures](references/exit-status.md).
- **Exit 0 isn't proof.** Check the result itself: the service's state, the file's contents, or, after a reboot on Linux, a changed `/proc/sys/kernel/random/boot_id`.
- **Ask before changing what your access depends on.** Before changing networking, SSH, or firewall settings on a host you only reach over SSH, agree with the user how they would recover. If a connection drops partway through a change, check what the host did before running anything again.
