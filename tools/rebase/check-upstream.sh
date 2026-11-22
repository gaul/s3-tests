#!/bin/bash
# List the upstream s3-tests commits this fork has not been rebased onto.
#
# usage: tools/rebase/check-upstream.sh CEPH_DIR [UPSTREAM_REF]
#
# Reads the ceph/ceph commit that ceph/split was last split from and lists
# the commits since then in CEPH_DIR (default ref origin/main, so fetch
# there first) that touch src/test/rgw/s3-tests.  Exits 0 with no output
# when there is nothing new, and 1 when there is.

set -o errexit
set -o nounset
set -o pipefail

PREFIX=src/test/rgw/s3-tests
ceph=$1
upstream=${2:-origin/main}

source=$(git log -1 --format=%B refs/remotes/ceph/split |
        sed -n 's/^(split from ceph\/ceph@\([0-9a-f]*\))$/\1/p')
if [ -z "$source" ]; then
    echo "ceph/split names no ceph/ceph commit" >&2
    exit 2
fi
new=$(git -C "$ceph" log --oneline "$source..$upstream" -- "$PREFIX")
if [ -n "$new" ]; then
    echo "$(echo "$new" | wc -l) upstream commits since ceph/ceph@${source:0:12}:"
    echo "$new"
    exit 1
fi
