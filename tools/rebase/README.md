# Rebasing onto upstream

The s3-tests live in ceph/ceph under `src/test/rgw/s3-tests`; the old
ceph/s3-tests repository is frozen.  This fork's upstream branch,
`ceph/split`, is that directory's history split out into a repository of its
own, and `master` is S3Proxy's commits on top of it: markers saying which
tests fail on which backend, tags, and fixes to the harness.

Upstream keeps editing the lines next to the markers, so a plain
`git rebase` conflicts on almost every commit.  These tools rebuild the fork
on a new upstream tip instead, merging decorators test by test.

## Tools

| tool | does |
| --- | --- |
| `check-upstream.sh CEPH_DIR` | lists upstream commits newer than `ceph/split` |
| `split.sh CEPH_DIR` | splits new upstream commits onto `ceph/split`, reusing the existing ones |
| `replay.sh OLD_BASE..OLD_TIP` | replays the fork's commits onto the current branch |
| `markermerge.py` | the per-file merge `replay.sh` uses: decorators per test, the rest by `git merge-file` |
| `verify.py OLD_BASE OLD_TIP NEW_BASE NEW_TIP` | checks every marker carried over |
| `runlane.sh LANE` | runs one S3Proxy lane, emulator included, keeping its JUnit file |
| `triage.py RESULTS_DIR` | suggests the marker each failing test needs |
| `addmarks.py` | adds markers, from a list or from `triage.py --json` |

`CEPH_DIR` is a full clone of ceph/ceph.  The tools run from this checkout
while it is S3Proxy's `s3-tests` submodule.

## Recipe

1. Bring the ceph clone up to date and see what is new:

   ```
   git -C ~/work/ceph fetch origin
   tools/rebase/check-upstream.sh ~/work/ceph
   ```

2. Split the new commits onto `ceph/split`.  It prints the old and new tips;
   keep the old one, it is the base the fork sits on:

   ```
   tools/rebase/split.sh ~/work/ceph
   ```

   Commit ids already on `ceph/split` do not change: each split commit
   records the ceph commit it came from, and a later split starts from them.

3. Replay the fork onto the new tip, on a branch of its own:

   ```
   git switch -c rebase-ceph ceph/split
   tools/rebase/replay.sh OLD_SPLIT..master
   ```

   `NOTE` lines report a marker change that no longer applies, usually
   because upstream deleted or rewrote the test; check each one.  `EMPTY`
   reports a commit with nothing left, typically because upstream made the
   same change.  On `STOP`, resolve the files, `git commit -C` the commit
   it names, and run again from there as it says.

4. Check that the markers carried over:

   ```
   python3 tools/rebase/verify.py OLD_SPLIT master ceph/split rebase-ceph
   ```

   Every `LOST` is a marker on a test that upstream deleted; every `DIFF`
   needs a look.

5. Run every lane against the rebased tests, with `target/s3proxy` built in
   the S3Proxy checkout:

   ```
   for lane in transient filesystem azurite azurite-versioning \
           fake-gcs-server localstack ministack swift; do
       tools/rebase/runlane.sh $lane
   done
   python3 tools/rebase/triage.py lane-results --json plan.json
   ```

   New upstream tests that S3Proxy fails show up as failures, and stale
   markers as `XPASS`.  Add the markers, each with a comment saying why the
   test fails, with `addmarks.py --json plan.json` or by hand, and rerun the
   lanes that changed until all are green.

6. Make `rebase-ceph` the new `master`, push it, and bump the `s3-tests`
   pointer in S3Proxy with a commit of its own.  Push this repository first,
   so that the pointer never names a commit the remote does not have.
