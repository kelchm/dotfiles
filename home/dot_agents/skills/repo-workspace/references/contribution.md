# Contribution checkouts

Read this when setting up or normalizing a Contribute checkout, starting a contribution worktree, publishing a contribution, or choosing Actions settings for a fork.

## Git settings

Check existing settings before changing anything. Existing feature-branch tracking, stack metadata, local commits, remote refs, and user protections must be kept. Changing baseline settings must not reset or advance any branch.

With `origin` set to the user's publishing fork (once forking is authorized) and `upstream` set to the verified contribution target, apply these settings:

```sh
git remote set-url --push upstream no_push
git config remote.pushDefault origin
git config push.default simple
git config pull.ff only
git fetch upstream   # not --prune: it deletes hand-fetched refs like upstream/pr-123
git branch --set-upstream-to=upstream/<target> <baseline>
gh repo set-default <upstream owner/repo>   # pins what gh already picks for a remote named upstream
```

Find the target's actual default or release branch rather than assuming `main`, and keep the existing local branch names. Without an authorized fork, clone with `--origin upstream` and leave `origin` absent until forking is authorized.

These settings do not guarantee everything. `remote.pushDefault` does not stop a push of the baseline branch to `origin`, and `pull.ff=only` does not keep the baseline pristine. Make ordinary contribution edits in topic worktrees. Do not add a general push-hook framework. Leave an effective `push.autoSetupRemote` as it is: the first publication is explicit either way.

Do not change project or environment preferences, such as a project's `autoPull`, while normalizing a checkout.

## GitHub Actions on forks

Disable scheduled workflows on the user's forks by default. Keep a schedule when the user wants it, and decide anything else case by case, when it causes noise or the user asks.

- Turn off each scheduled workflow (`gh workflow disable <workflow> --repo <fork owner/repo>`) unless it also runs on pushes to branches the user works on. Name the fork explicitly, since `gh` defaults to upstream in a Contribute checkout. A disabled workflow creates no runs, and the user can turn it back on later. A fork's `pull_request` triggers fire only for pull requests opened against the fork, not for the user's upstream contributions.
- Don't exclude `schedule` with an Actions policy. Each blocked run is recorded as a startup failure and emails the user.

An audit of a fork's Actions is read-only. Changing its settings is a separate step the user approves.

## Starting work

- An independent contribution starts from freshly fetched `upstream/<target>` and does not inherit the baseline's pull tracking: `git fetch upstream && git switch -c <topic> --no-track upstream/<target>`. Release work starts from its explicit release target.
- A dependent stack layer starts from its actual parent branch. Use the `gh-stack` skill.
- T3's `startFromOrigin=true` does not always mean `origin`. According to T3 source, it follows the selected local branch's configured tracking remote, or an explicitly remote-qualified ref, and falls back to `origin` only when neither applies. For an independent contribution, request `upstream/<target>` explicitly with `startFromOrigin=true` where the native surface allows it. Don't rely on the environment's `newWorktreesStartFromOrigin` default being applied to a native request. A local branch literally named `upstream/<target>` would shadow the remote ref. For a stack layer, use the parent branch with `startFromOrigin=false` so its local commits are kept.
- Before the first edit in a new worktree, confirm its base. For an independent contribution, `git rev-parse HEAD` must equal `git rev-parse upstream/<target>` right after a fresh `git fetch upstream`. For a stack layer, HEAD must equal the parent branch's SHA, captured when you chose it. If the base is wrong, stop and fix it. Don't build on it.

## Publishing

Publish only when it is authorized, and only within the task's restrictions.

- First publication: `git push -u origin HEAD`. After that the topic tracks `origin/<topic>`. Updating a topic from upstream is a separate operation.
- Create the PR with the target named explicitly: `gh pr create --repo <upstream owner/repo> --base <target> --head <fork owner>:<topic>`.
- If you use T3's native PR creation instead, check the exact request it will send before sending it. T3 picks the target repository from `GH_REPO`, then `gh`'s default, then the `upstream`, `github`, and `origin` remotes, and the source suggests the head may lose its fork qualification when the topic tracks `origin`.
- Never run `gh pr create --dry-run` blindly, since it may push. Never open a test PR.

## Runtime limits

On the deployed build, worktrees started from `origin/<baseline>` while the baseline tracked `origin` (t3code, November 2026). Starting from upstream once the baseline tracks it is not yet observed, so the HEAD check before the first edit and explicit `--repo`/`--base`/`--head` stay the safeguards.
