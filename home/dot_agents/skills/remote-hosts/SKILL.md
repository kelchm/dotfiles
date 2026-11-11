---
name: remote-hosts
description: Work on hosts you reach over SSH. Use before scripting or polling a host, rebooting it, or changing its networking or SSH.
---

# Remote hosts

## Connections

Every `ssh` repeats the handshake and login: roughly 0.4s against 0.01s for a reused connection, plus a process on the host. That adds up fast in loops and scripts, including `ssh` nested inside them. Run repeated work on the host inside one connection, or hold one open for the job. Examples: [polling a host, and steps that can't be combined](references/connections.md).

## The host's environment

A remote host is not your workstation. Tools you expect may be missing or off `PATH`, versions differ, and services run with a minimal environment. Check what you need once before building on it, rather than discovering it one failed command at a time. Examples: [a missing tool, and a service manager's PATH](references/environment.md).

## Waits

`BatchMode` and `ConnectTimeout` only cover getting connected; a command that hangs after login, or a loop waiting for a host to return, runs until something stops it. Give both a deadline, and after a reboot confirm the host actually restarted. Examples: [waiting for a reboot or a long job](references/waits.md).

## Login failures

A failed login usually has one cause: a locked SSH agent, an approval that timed out, the wrong user, or a host key pinned under another name. Retrying unchanged doesn't help. Find the cause, wait for the user when it needs them, and never turn off host-key checking to get through. Examples: [a locked SSH agent, a guessed user, and a host-key mismatch](references/login-failures.md).

## Exit status

A pipeline reports its last command's status, and a script that carries on after an error ends with whatever ran last. Either can make a failed remote step look successful. Examples: [a pipeline hiding a failed login, and a nested ssh swallowing a script](references/exit-status.md).

## Changing what your access depends on

When a change can break networking, SSH, or a service you reach the host through, a rollback that needs you to log in again may never run. Arm the rollback on the host before the change, and cancel it only once a fresh connection works. If a connection drops mid-change, check what the host did before rerunning. Examples: [a static IP with an automatic revert, and a rollback that needed a fresh login](references/access-changes.md).
