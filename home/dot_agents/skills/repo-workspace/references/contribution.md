# Contribution checkouts

Read this when setting up or normalizing a Contribute checkout, starting a contribution worktree, or publishing a contribution.

## Git settings

Check existing settings before changing anything. Existing feature-branch tracking, stack metadata, local commits, remote refs, and user protections must be kept. Changing baseline settings must not reset or advance any branch.

| Setting | Value |
|---|---|
| `remote.origin.url` | the user's publishing fork, once forking is authorized |
| `remote.upstream.url` | the verified contribution target |
| upstream push URL | disabled, for example `git remote set-url --push upstream no_push` |
| `remote.pushDefault` | `origin` |
| `push.default` | `simple` |
| `pull.ff` | `only` |
| `branch.<baseline>.remote` | `upstream` |
| `branch.<baseline>.merge` | `refs/heads/<actual target branch>` |
| `gh repo set-default` | the upstream `owner/repo` |

Find the target's actual default or release branch rather than assuming `main`, and keep the existing local branch names. Without an authorized fork, clone with `--origin upstream` and leave `origin` absent until forking is authorized.

These settings do not guarantee everything. `remote.pushDefault` does not stop a push of the baseline branch to `origin`, and `pull.ff=only` does not keep the baseline pristine. Make ordinary contribution edits in topic worktrees. Do not add a general push-hook framework. Leave an effective `push.autoSetupRemote` as it is: the first publication is explicit either way.

Do not change project or environment preferences, such as a project's `autoPull`, while normalizing a checkout.

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

T3's fresh-base and native PR behavior above is derived from reading T3 source. It has not been reproduced on the deployed build. A focused local source test could not initialize because of a dependency mismatch in the local T3 checkout. Until it is reproduced, the HEAD check before the first edit and the explicit `--repo`/`--base`/`--head` arguments are the safeguards.
