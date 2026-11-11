# Hidden failures

## A pipeline hides a failed login

An agent tried two hosts in turn and stopped at the first that answered.

**Wrong:** login to the first host failed, but `head` succeeded, so `&& break` stopped the loop. The second host was never tried.

```sh
for h in host-a host-b; do
  ssh $h 'ip route' | head -40 && break
done
```

**Right:** test the `ssh` result, not the pipeline's.

```sh
for h in host-a host-b; do
  out=$(ssh $h 'ip route') && { echo "$out" | head -40; break; }
done
```

## A nested ssh swallows the script

**Wrong:** the inner `ssh` reads the rest of the script as its own input, so the later steps never run.

```sh
ssh host-a bash -s <<'EOF'
ssh host-b 'docker pull "$IMAGE"'
./deploy.sh    # never runs
EOF
```

**Right:** give inner `ssh` calls `-n`.

```sh
ssh -n host-b 'docker pull "$IMAGE"'
```
