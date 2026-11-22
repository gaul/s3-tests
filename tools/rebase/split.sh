#!/bin/bash
# Split the s3-tests directory of a ceph/ceph checkout into standalone
# history, the way this fork's upstream branch ceph/split was made, and
# fetch the result into this repository as refs/remotes/ceph/split.
#
# usage: tools/rebase/split.sh CEPH_DIR [UPSTREAM_REF]
#
# CEPH_DIR is a full clone of ceph/ceph; UPSTREAM_REF defaults to
# origin/main.  Each split commit records the ceph commit it came from in a
# "(split from ceph/ceph@SHA)" line, so a later run reuses the existing
# ceph/split and adds only the commits after it.  The ids of commits already
# split stay the same, which is what lets the fork's branches rebase onto
# the new tip.

set -o errexit
set -o nounset
set -o pipefail

PREFIX=src/test/rgw/s3-tests
ceph=$(cd "$1" && pwd)
upstream=${2:-origin/main}
here=$(git rev-parse --show-toplevel)

# Hand the existing split to the ceph checkout, whose objects the new
# commits are built from.
declare -A map
if git -C "$here" rev-parse --verify --quiet refs/remotes/ceph/split >/dev/null; then
    git -C "$ceph" fetch --quiet "$here" \
            "+refs/remotes/ceph/split:refs/s3tests/split"
    while read -r split source; do
        map[$source]=$split
    done < <(git -C "$ceph" log --format='%x01%H%n%B' refs/s3tests/split |
            awk '/^\001/ { split_sha = substr($0, 2); next }
                 /^\(split from ceph\/ceph@[0-9a-f]+\)$/ {
                     source = $0
                     sub(/^\(split from ceph\/ceph@/, "", source)
                     sub(/\)$/, "", source)
                     print split_sha, source
                 }')
    echo "existing split: ${#map[@]} commits" >&2
fi

last=""
count=0
while read -r sha parents; do
    if [ -n "${map[$sha]:-}" ]; then
        last=${map[$sha]}
        continue
    fi
    args=()
    for p in $parents; do
        if [ -z "${map[$p]:-}" ]; then
            echo "parent $p of $sha has not been split" >&2
            exit 1
        fi
        args+=(-p "${map[$p]}")
    done
    tree=$(git -C "$ceph" rev-parse "$sha:$PREFIX")
    new=$(
        cd "$ceph"
        format() { git log -1 --format="$1" "$sha"; }
        export GIT_AUTHOR_NAME="$(format %an)" GIT_AUTHOR_EMAIL="$(format %ae)"
        export GIT_AUTHOR_DATE="$(format %aD)"
        export GIT_COMMITTER_NAME="$(format %cn)" GIT_COMMITTER_EMAIL="$(format %ce)"
        export GIT_COMMITTER_DATE="$(format %cD)"
        { format %B; echo "(split from ceph/ceph@$sha)"; } |
                git commit-tree "$tree" ${args[@]+"${args[@]}"}
    )
    map[$sha]=$new
    last=$new
    count=$((count + 1))
done < <(git -C "$ceph" rev-list --topo-order --reverse --parents \
        "$upstream" -- "$PREFIX")

if [ -z "$last" ]; then
    echo "$upstream has no commits under $PREFIX" >&2
    exit 1
fi
git -C "$ceph" update-ref refs/s3tests/split-new "$last"
old=$(git -C "$here" rev-parse --verify --quiet refs/remotes/ceph/split || true)
# Count what the new tip gained rather than what was made: a clone with
# more history than the one the existing split came from can see a merge
# or two that history simplification dropped there, which get split but
# end up on no path to the tip.
if [ -n "$old" ]; then
    count=$(git -C "$ceph" rev-list --count "$last" --not refs/s3tests/split)
fi
git -C "$here" fetch --quiet "$ceph" "+refs/s3tests/split-new:refs/remotes/ceph/split"
echo "added $count commits" >&2
echo "old ceph/split: ${old:-none}"
echo "new ceph/split: $last"
