# Connections

## Polling a host during a benchmark

An agent benchmarking two DGX Sparks wrote a sampler to record CPU clocks on both hosts every 2 seconds while each run was in progress.

**Wrong:** a fresh connection for every sample.

```sh
while :; do
  for n in 1 2; do
    ssh -n -o BatchMode=yes kelchm@10.32.21.3$n \
      'for p in 0 10 15; do cat /sys/devices/system/cpu/cpufreq/policy$p/scaling_cur_freq; done'
  done
  sleep 2
done
```

That came to about 1,600 SSH connections an hour from one workstation. Each one forked `sshd` and ran a key exchange on the Sparks, the very machines being measured.

**Right:** run the loop on each host, and stream the samples back over one connection.

```sh
for n in 1 2; do
  ssh -o BatchMode=yes kelchm@10.32.21.3$n '
    while :; do
      printf "%s" "$(date -u +%FT%TZ)"
      for p in 0 10 15; do printf ",%s" "$(cat /sys/devices/system/cpu/cpufreq/policy$p/scaling_cur_freq)"; done
      echo; sleep 2
    done' > "clocks-spark-$n.csv" &
done
```

That's two connections for the whole run, and the timestamps come from the host rather than the workstation.

## Steps that can't be combined

When you need to look at output before choosing the next command, hold one connection open for the job.

```sh
sock=/tmp/cm-$$                          # short: macOS caps socket paths at 104 bytes
ssh -fNM -S "$sock" kelchm@10.32.21.31
ssh -S "$sock" -O check kelchm@10.32.21.31  # -S falls back to a fresh connection if the master is gone
ssh -S "$sock" kelchm@10.32.21.31 'docker ps'
ssh -S "$sock" kelchm@10.32.21.31 'docker logs --tail 50 qwen'
ssh -S "$sock" -O exit kelchm@10.32.21.31
```

Close only a master you opened. Close it before you finish, too, or it outlives the job.
