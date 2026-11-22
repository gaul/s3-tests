#!/bin/bash
# Replay the fork's commits onto the current branch, merging each test file
# through markermerge.py instead of git's line merge.
#
# usage: tools/rebase/replay.sh OLD_BASE..OLD_TIP
#
# Check out a branch at the new upstream tip first, for example
#     git switch -c rebase-ceph ceph/split
# then pass the range of fork commits on the old base.  Each commit keeps
# its author and message.  A commit with nothing left to apply is skipped
# and reported.  On a conflict the replay stops with the files in the
# working tree: resolve them, commit with "git commit -C <commit>", and run
# again with the range starting at that commit.

set -o errexit
set -o nounset
set -o pipefail

if [ $# -ne 1 ] || [[ "$1" != *..* ]]; then
    echo "usage: $0 OLD_BASE..OLD_TIP" >&2
    exit 1
fi
range=$1
tools=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "the working tree has changes; commit or stash them first" >&2
    exit 1
fi

for c in $(git rev-list --reverse --no-merges "$range"); do
    subject="$(git log -1 --format='%h %s' "$c")"
    git cherry-pick --no-commit "$c" >/dev/null 2>&1 || true
    for f in $(git diff --name-only "$c^" "$c" -- 's3tests/functional/*.py'); do
        if ! git cat-file -e "$c:$f" 2>/dev/null ||
                ! git cat-file -e "HEAD:$f" 2>/dev/null; then
            continue  # added or deleted: the cherry-pick's answer stands
        fi
        git show "$c^:$f" > "$work/parent"
        git show "$c:$f" > "$work/commit"
        git show "HEAD:$f" > "$work/head"
        if python3 -I "$tools/markermerge.py" "$work/parent" "$work/commit" \
                "$work/head" "$f" 2> "$work/notes"; then
            git add "$f"
            if [ -s "$work/notes" ]; then
                echo "NOTE $subject [$f]"
                sed 's/^/    /' "$work/notes"
            fi
        else
            echo "STOP $subject [$f]: the test bodies conflict"
            sed 's/^/    /' "$work/notes"
            echo "resolve, commit with: git commit -C $c"
            echo "then continue with: $0 $c..${range#*..}"
            exit 1
        fi
    done
    unmerged=$(git diff --name-only --diff-filter=U)
    if [ -n "$unmerged" ]; then
        echo "STOP $subject: conflicts in" $unmerged
        echo "resolve, commit with: git commit -C $c"
        echo "then continue with: $0 $c..${range#*..}"
        exit 1
    fi
    if git diff --cached --quiet; then
        echo "EMPTY $subject"
        git reset --quiet --hard
        continue
    fi
    git commit --quiet -C "$c"
done
echo "replayed $range"
