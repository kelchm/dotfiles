# Changing what your access depends on

## Right: a static IP with an automatic revert

An agent moved a GL.iNet KVM from DHCP to a static address. If the new address had been wrong, the agent would have lost the host.

```sh
timeout 30 ssh -o BatchMode=yes -o ServerAliveInterval=5 -o ServerAliveCountMax=2 root@10.32.20.10 '
  set -e
  cp -a /etc/kvmd/user/connman/ethernet_9483c4c499d7_cable/settings \
        /etc/kvmd/user/backups/connman-settings.before-static
  touch /tmp/static-ip-pending
  nohup sh -c "sleep 90; if [ -e /tmp/static-ip-pending ]; then
      connmanctl config ethernet_9483c4c499d7_cable --ipv4 dhcp
    fi" >/dev/null 2>&1 &
  connmanctl config ethernet_9483c4c499d7_cable --ipv4 manual 10.32.20.10 255.255.255.0 10.32.20.1 --nameservers 10.32.20.1'

# A new, unshared connection proves the new address works; only then cancel the revert.
ssh -o BatchMode=yes -o ConnectTimeout=5 -o ControlPath=none root@10.32.20.10 'rm -f /tmp/static-ip-pending && echo "fallback cancelled"'
```

The revert lived on the host and didn't need the agent. If the second `ssh` had failed, the KVM would have gone back to DHCP after 90 seconds.

## Wrong: a rollback that needs a fresh login

During the overnight trial in [login failures](login-failures.md), the agent stopped DeepSeek to free the Sparks and planned to relaunch it over SSH when the trial ended. The trial failed, but by then 1Password had locked, and the relaunch couldn't log in. DeepSeek stayed down for 5½ hours.

**Right:** arm the restore on the host before taking the service down, as a system timer so it survives logout, and cancel it only once the restore isn't needed.

```sh
# restore-deepseek.sh: the same relaunch you would otherwise run by hand at the end
ssh kelchm@10.32.21.31 'sudo -n systemd-run --uid=kelchm --on-active=4h --unit=restore-deepseek /home/kelchm/restore-deepseek.sh'
# … run the trial …
ssh kelchm@10.32.21.31 'sudo -n systemctl stop restore-deepseek.timer && ~/restore-deepseek.sh'
```

## A dropped connection mid-change

If a connection drops during a change, don't rerun it straight away. Check what the host actually did first, since the change may already have finished or be halfway through.
