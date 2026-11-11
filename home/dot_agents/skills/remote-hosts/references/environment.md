# The host's environment

## A tool that isn't there

An agent was auditing backups on a Proxmox node and parsed the API output with `jq` on the host.

**Wrong:**

```sh
ssh kelchm@10.32.20.21 'for v in 101 102; do
  sudo pvesh get /nodes/pve-sbx-1/storage/backups-pve-sbx/content --vmid $v --output-format json | jq -r ".[] | .volid"
done'
```

```
bash: line 1: jq: command not found
```

Proxmox doesn't ship `jq`, so every iteration failed the same way.

**Right:** fetch the raw output, check that the fetch worked, and parse it where the tool exists.

```sh
json=$(ssh kelchm@10.32.20.21 'sudo pvesh get /nodes/pve-sbx-1/storage/backups-pve-sbx/content --output-format json') || exit 1
printf '%s\n' "$json" | jq -r '.[] | select(.vmid == 101 or .vmid == 102) | .volid'
```

When a check needs several tools, ask once up front: `ssh host 'command -v jq rg iw docker'`.

## A service manager's PATH

On a NixOS Raspberry Pi with a crashed Wi-Fi driver, an agent scheduled a driver reload as a transient unit, so the reload would survive dropping the connection.

**Wrong:**

```sh
ssh kelchm@streamer-basement-workbench.local \
  'sudo -n systemd-run --unit=wifi-reload-manual sh -c "modprobe -r brcmfmac_wcc brcmfmac; sleep 2; modprobe brcmfmac"'
```

`systemd-run` replied "scheduled", but the unit failed straight away:

```
sh: line 1: modprobe: command not found
sh: line 1: sleep: command not found
```

Transient units on NixOS get almost no `PATH`, so the reload never ran, and the driver stayed down.

**Right:** give the unit an explicit `PATH`, stop if a step fails, then check what the unit actually did.

```sh
ssh kelchm@streamer-basement-workbench.local '
  sudo -n systemd-run --unit=wifi-reload-manual --setenv=PATH=/run/current-system/sw/bin \
    sh -c "modprobe -r brcmfmac_wcc brcmfmac && sleep 2 && modprobe brcmfmac"
  sleep 5; systemctl status --no-pager --lines=10 wifi-reload-manual'
```
