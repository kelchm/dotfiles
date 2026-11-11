# A long upgrade

An agent upgraded a host's packages, which takes several minutes.

**Wrong:** the upgrade runs in the foreground. You're blocked until your tool times out, and if the connection drops, the upgrade can die with it.

```sh
ssh host 'sudo apt-get -y full-upgrade'
```

**Right:** start it detached with its output in a log, which ends with its exit status, and note the PID.

```sh
ssh host 'setsid nohup sh -c "sudo -n apt-get -y full-upgrade; echo exit=\$?" </dev/null >upgrade.log 2>&1 & echo pid=$!'
```

Check the log once right away to confirm it started, then check back with short calls until it ends with `exit=`. If you stop working before then, tell the user the job is still running and its PID.

```sh
ssh host 'tail -3 upgrade.log'
```
