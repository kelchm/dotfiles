# Waits

## Waiting for a reboot

During an OS update on a DGX Spark, an agent rebooted the host and waited for it to come back.

**Wrong:**

```sh
ssh -o BatchMode=yes 10.32.21.32 'sudo -n systemctl reboot'
sleep 60
until timeout 8 ssh -o BatchMode=yes -o ConnectTimeout=5 10.32.21.32 true 2>/dev/null; do sleep 15; done
echo back
```

`timeout 8` limits each attempt, but nothing limits the loop. If the host never comes back, from a bad kernel or a firmware prompt, the loop spins forever and the agent never hears about it. A host that is still shutting down can also answer the first attempt, so "back" doesn't prove the reboot happened.

**Right:** put a deadline on the whole wait, and compare boot IDs.

```sh
before=$(ssh 10.32.21.32 cat /proc/sys/kernel/random/boot_id)
ssh -o BatchMode=yes 10.32.21.32 'sudo -n systemctl reboot'
timeout 900 sh -c 'until ssh -o BatchMode=yes -o ConnectTimeout=5 10.32.21.32 true 2>/dev/null; do sleep 15; done' \
  || { echo "not back after 15 minutes"; exit 1; }
[ "$(ssh 10.32.21.32 cat /proc/sys/kernel/random/boot_id)" != "$before" ] || echo "did not reboot"
```

## Waiting for a long job

The same agent waited for the upgrade log to say it had finished.

**Wrong:**

```sh
until timeout 20 ssh 10.32.21.32 'grep -q "== end" ~/os-update/upgrade.log'; do sleep 20; done
```

If the upgrade dies before it writes `== end`, the loop never ends. Every pass also opens a new connection.

**Right:** wait on the host, with a deadline that fails loudly.

```sh
ssh 10.32.21.32 'timeout 3600 sh -c "until grep -q \"== end\" ~/os-update/upgrade.log; do sleep 20; done" \
  || { echo "upgrade did not finish within an hour"; tail -20 ~/os-update/upgrade.log; exit 1; }'
```
