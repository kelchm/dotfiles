# Login failures

## The SSH agent stops signing

An agent ran an overnight model trial on the Sparks, then took DeepSeek down to make room. At 03:25, 1Password locked and its SSH agent stopped signing:

```
sign_and_send_pubkey: signing failed for ED25519 "personal:home-lab" from agent: communication with agent failed
kelchm@10.32.21.31: Permission denied (publickey,password).
```

**Wrong:** the agent's polling loop kept trying and piled up failures. It then retried without `BatchMode` and got `Received disconnect … Too many authentication failures`. It only told the user at 07:35, four hours later. DeepSeek stayed down from 03:03 until 08:41, because the rollback needed the same login.

**Right:** treat the first "communication with agent failed" or "agent refused operation" as a blocker, not a flaky network. Stop the loop, and tell the user right away what is blocked and what is down, for example: "1Password's SSH agent won't sign, so I can't reach the Sparks to roll back. DeepSeek is down until it can." Retry only after something has changed.

## Guessing the user

**Wrong:** checking Tailscale on three Proxmox nodes as `root`:

```
root@10.32.20.21: Permission denied (publickey,password).
root@10.32.20.22: Permission denied (publickey,password).
root@10.32.20.23: Permission denied (publickey,password).
```

**Right:** look up how the project reaches the host first. Here the runbooks all use `kelchm@` with `sudo -n`. `ssh -G host | grep -E '^(user|hostname) '` shows what your own config will do.

## A host-key mismatch

**Wrong:** connecting by IP after the key was recorded under the host's name, then passing `-o StrictHostKeyChecking=no` to get past the warning.

**Right:** connect by the name the key is pinned under, or compare the fingerprint against one you already trust (`ssh-keygen -F name`). Never turn verification off to make an error go away.
