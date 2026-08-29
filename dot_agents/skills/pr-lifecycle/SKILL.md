---
name: pr-lifecycle
description: Coordinate pull-request review, optional branch preparation, feedback triage, merge authorization, and requested rollout verification. Use when the user asks to review, land, merge, deploy, babysit, or monitor a pull request. Do not use for ordinary local edits with no PR lifecycle.
---

# PR lifecycle

Own the requested portion of a pull request's lifecycle while keeping review, publication, merge, and deployment as distinct authorization boundaries.

## Resolve the target

Before changing anything, establish the repository and exact worktree, PR URL or number, head and base branches, head commit, local cleanliness, remote divergence, and the lifecycle stages the user actually requested.

Read repository instructions before deciding how to validate, publish, merge, or deploy. If the target or requested mutation is genuinely ambiguous, stop and ask instead of guessing.

## Review from evidence

Start with read-only inspection of:

- PR metadata, changed files, diff, and linked issue;
- CI and required checks on the current head commit;
- review comments, unresolved threads, and bot findings;
- mergeability, branch ancestry, dependencies, and ordering risks; and
- the repository's deployment or reconciliation mechanism when rollout is in scope.

Verify findings against the source. Separate blockers, important non-blocking concerns, stale or already-resolved comments, bot noise, and residual test gaps. A review-only request does not authorize edits, commits, pushes, PR updates, merges, or deployment changes.

## Prepare only when requested

When the user asks to address findings or prepare the PR:

1. Reconfirm the intended worktree and branch before editing.
2. Sync or rebase only when needed and safe for that repository.
3. Fix verified findings without expanding into unrelated work.
4. Run the smallest relevant checks required by repository instructions.
5. Re-review the resulting diff.
6. Commit, push, or open/update the PR only to the extent the request authorizes.

After publishing, verify the intended remote branch and the PR's current head and draft state. Report the PR URL, branch, exact commit, and whether it remains a draft.

Use an existing review or implementation delegation skill when the user asks for an independent review or bounded delegation. Do not duplicate its provider-specific mechanics here.

## Preserve authorization boundaries

Interpret the request narrowly:

- Review and monitoring are read-only.
- Editing or committing requires an implementation/fix request.
- Pushing or opening/updating a PR requires explicit publication scope or a clearly approved continuation that already included publication.
- Merging requires explicit merge approval after current blockers are known.
- Direct-to-main work requires explicit direct-main authorization.
- Deployment mutations require explicit deployment authorization.

"Merge and monitor" authorizes that merge and read-only verification, not unrelated remediation. Stop before mutation if CI is red, required review is missing, the branch or head commit changed unexpectedly, or the target became ambiguous.

Do not ask for the same approval twice. Once a stage is explicitly authorized, carry it through unless new evidence materially changes the risk or scope.

## Babysit feedback and checks

When asked to babysit or monitor a PR:

- Track the current head commit so stale results are not mistaken for current ones.
- Inspect only checks and comments newer than the last handled state.
- Deduplicate the same finding across reviewers, bots, and prior threads; when replies are authorized, continue the existing thread instead of posting a parallel one.
- Verify each automated finding against the code; fix real findings when authorized and explain false positives when replies are authorized.
- Stay quiet when nothing meaningful changed.
- Stop when the latest head is green and required feedback is resolved, the PR is merged or closed, a definitive blocker appears, or the agreed monitoring window ends.

Across a long or resumed lifecycle, preserve a compact checkpoint of the PR head, handled check runs and comment IDs, attempted fixes that were abandoned, and remaining blockers in conversation or task state. Do not create a repository artifact unless the user or repository workflow asks for one.

Do not monitor indefinitely. Establish a finite horizon appropriate to the repository and ask before extending it.

## Verify an authorized merge or rollout

Before merging, reconfirm the exact PR, head commit, approvals, checks, and unresolved blockers. After an authorized merge or deployment:

- report the exact merge commit or deployed revision;
- verify that the expected reconciler or deployment mechanism observed it;
- check only the relevant repository-defined health indicators; and
- distinguish transient warnings from persistent failures.

Do not invent generic rollout checks when the repository defines its own runbook or skill.

## Close out compactly

Report the target and exact commit, actions taken, actions deliberately not taken, findings and supporting evidence, checks or rollout result, and any remaining caveat or user decision. Do not paste large logs or expose credentials.
