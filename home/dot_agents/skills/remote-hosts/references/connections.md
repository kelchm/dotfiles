# Polling and batching

## Polling a host

An agent sampled a host's CPU clock every 2 seconds during a benchmark.

**Wrong:** a new connection for every sample. That's about 1,800 connections an hour, each one adding load to the machine being measured.

```sh
while :; do
  ssh host 'cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq'
  sleep 2
done
```

**Right:** one connection, with a bounded loop on the host: 30 samples, then it returns.

```sh
ssh host 'for i in $(seq 30); do cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq; sleep 2; done'
```

## Several steps

**Wrong:** one connection per step.

```sh
ssh host 'docker ps'
ssh host 'docker logs --tail 50 app'
ssh host 'df -h /var/lib/docker'
```

**Right:** the same steps in one connection.

```sh
ssh host 'docker ps && docker logs --tail 50 app && df -h /var/lib/docker'
```

## Many separate calls

When each step depends on the last one's output, the steps can't go in one `ssh`.

**Wrong:** a fresh connection and login for each of the many calls in an investigation.

**Right:** give each call to that host the same connection-sharing options. The first call opens a shared connection, later calls reuse it, and it closes itself 5 minutes after the last one. Use this for the host you're working on, not as a default for every host.

```sh
ssh -o ControlMaster=auto -o ControlPath=~/.ssh/cm-%C -o ControlPersist=5m host 'docker ps'
ssh -o ControlMaster=auto -o ControlPath=~/.ssh/cm-%C -o ControlPersist=5m host 'docker logs --tail 50 app'
```
