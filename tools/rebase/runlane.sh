#!/bin/bash
# Run one s3-tests lane the way S3Proxy's CI does, emulator included, and
# keep its JUnit file for triage.py.
#
# usage: tools/rebase/runlane.sh LANE [PYTEST ARGS...]
#
# LANE is one of transient, filesystem, azurite, azurite-versioning,
# fake-gcs-server, localstack, ministack, swift.  Run it from this checkout
# while it is S3Proxy's s3-tests submodule, after "mvn package" has built
# target/s3proxy.  The emulator versions are read from S3Proxy's CI
# workflow so that a local run tests what CI tests.  Containers run under
# podman, or docker if CONTAINER=docker.
#
# Environment:
#   S3PROXY_DIR  the S3Proxy checkout (default: the superproject)
#   RESULTS      where LANE.xml and LANE.log go (default: ./lane-results)
#   CONTAINER    podman or docker (default: podman)

set -o nounset

lane=${1:?usage: $0 LANE [PYTEST ARGS...]}
shift
s3proxy=${S3PROXY_DIR:-$(git rev-parse --show-superproject-working-tree)}
results=$(mkdir -p "${RESULTS:-lane-results}" && cd "${RESULTS:-lane-results}" && pwd)
container=${CONTAINER:-podman}
workflow=$s3proxy/.github/workflows/ci-main.yml

# The first image or package reference in the workflow that starts with $1.
pinned() {
    grep -o -m 1 "$1[^ \"'\\\\]*" "$workflow" || {
        echo "no $1 in $workflow" >&2
        exit 1
    }
}

wait_url() {
    for _ in $(seq 120); do
        curl -s -o /dev/null "$@" && return 0
        sleep 1
    done
    echo "timed out waiting for $*" >&2
    return 1
}

emulator_pid=""
container_name=""
cleanup() {
    if [ -n "$emulator_pid" ]; then
        pkill -P "$emulator_pid" 2>/dev/null
        kill "$emulator_pid" 2>/dev/null
    fi
    if [ -n "$container_name" ]; then
        "$container" stop -t 2 "$container_name" >/dev/null 2>&1
    fi
}
trap cleanup EXIT

conf=s3proxy-$lane.conf
env_vars=()
case $lane in
transient)
    conf=s3proxy.conf
    ;;
filesystem)
    # s3proxy-filesystem.conf stores under /tmp/blobstore, as in CI.
    rm -rf /tmp/blobstore
    mkdir -p /tmp/blobstore
    ;;
azurite|azurite-versioning)
    account='{}'
    if [ "$lane" = azurite-versioning ]; then
        account='{"isBlobVersioningEnabled":true}'
    fi
    data=$(mktemp -d)
    (cd "$data" && exec npx --yes --package "$(pinned azurite@)" azurite-blob \
            --accountConfigAsJson "$account" > "$results/$lane.emulator.log" 2>&1) &
    emulator_pid=$!
    wait_url 'http://127.0.0.1:10000/devstoreaccount1?comp=list' || exit 1
    ;;
localstack)
    container_name=s3tests-localstack
    "$container" run -d --rm --name "$container_name" -p 4566:4566 \
            "$(pinned localstack/localstack:)" >/dev/null || exit 1
    for _ in $(seq 90); do
        curl -s http://127.0.0.1:4566/_localstack/health | grep -q '"s3"' && break
        sleep 1
    done
    ;;
ministack)
    container_name=s3tests-ministack
    "$container" run -d --rm --name "$container_name" -p 4567:4566 \
            "$(pinned ministackorg/ministack:)" >/dev/null || exit 1
    wait_url http://127.0.0.1:4567/ || exit 1
    ;;
fake-gcs-server)
    # go install puts it in $(go env GOPATH)/bin, as CI's own step does.
    GOBIN=$results/bin go install "$(pinned github.com/fsouza/fake-gcs-server@)" || exit 1
    "$results/bin/fake-gcs-server" -backend memory -scheme http -host 127.0.0.1 \
            > "$results/$lane.emulator.log" 2>&1 &
    emulator_pid=$!
    wait_url http://127.0.0.1:4443/storage/v1/b || exit 1
    env_vars=(STORAGE_EMULATOR_HOST=http://localhost:4443)
    ;;
swift)
    container_name=s3tests-swift
    "$container" run -d --rm --name "$container_name" -p 8080:8080 \
            --security-opt seccomp=unconfined \
            "$(pinned openstackswift/saio@)" >/dev/null || exit 1
    auth=(-H 'X-Auth-User: test:tester' -H 'X-Auth-Key: testing')
    for _ in $(seq 300); do
        curl -sf -o /dev/null "${auth[@]}" http://127.0.0.1:8080/auth/v1.0 && break
        sleep 1
    done
    ;;
*)
    echo "unknown lane: $lane" >&2
    exit 1
    ;;
esac

cd "$s3proxy" || exit 1
env ${env_vars[@]+"${env_vars[@]}"} ./src/test/resources/run-s3-tests.sh \
        "$conf" "$@" > "$results/$lane.log" 2>&1
rc=$?
cp "target/s3-tests-${conf%.conf}.xml" "$results/$lane.xml" 2>/dev/null
echo "$lane: exit $rc, $(grep -E '^=+ .*(passed|failed|error).* =+$' "$results/$lane.log" | tail -1)"
exit $rc
