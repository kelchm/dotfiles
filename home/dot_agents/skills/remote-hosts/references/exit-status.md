# Exit status

## A pipeline hides a failed login

An agent checking BGP routes tried two routers in turn and stopped at the first one that answered.

**Wrong:**

```sh
for h in 10.32.30.1 10.32.10.1; do
  ssh -o BatchMode=yes root@$h "vtysh -c 'show ip route bgp'" 2>&1 | head -40 && break
done
```

```
root@10.32.30.1: Permission denied (publickey,keyboard-interactive).
```

`head` succeeded, so `&& break` fired after the failed login. The second router, the one that would have answered, was never tried.

**Right:** test the `ssh` status, not the pipeline's.

```sh
for h in 10.32.30.1 10.32.10.1; do
  if out=$(ssh -o BatchMode=yes root@$h "vtysh -c 'show ip route bgp'"); then
    printf '%s\n' "$out" | head -40; break
  fi
  echo "$h failed ($?)"
done
```

Or use `set -o pipefail`. An exit status of 255 means SSH itself failed, not the remote command.

## A nested ssh swallows the script

An agent streamed a deployment script to one host, and that script reached a second host partway through.

**Wrong:** the inner `ssh` read the rest of the script from stdin as its own input, and the remaining deployment steps silently never ran.

```sh
ssh kelchm@10.32.21.31 bash -s <<'SCRIPT'
ssh kelchm@10.32.21.32 'docker pull "$IMAGE"'
./deploy-head.sh          # never runs
SCRIPT
```

**Right:** give inner `ssh` calls `-n`, and end the script with a line you can check for.

```sh
ssh kelchm@10.32.21.31 bash -s <<'SCRIPT'
set -e
ssh -n kelchm@10.32.21.32 'docker pull "$IMAGE"'
./deploy-head.sh
echo DEPLOY_DONE
SCRIPT
```
