"""Treat the s3proxy backend markers as strict expected failures.

run-s3-tests.sh used to deselect these tests, which hid a marker that had
gone stale: one whose test had started passing was simply skipped forever,
and nothing said so.  Running them as strict xfail keeps the suite green
while a test still fails, and fails the suite as soon as one passes, so a
marker cannot outlive the limitation it records.

Only the fails_on_s3proxy markers are handled here.  The whole-feature tags
-- bucket_logging, lifecycle, versioning and the rest -- stay deselected in
run-s3-tests.sh, since running hundreds of tests for an unimplemented API to
watch them fail costs time and tells us nothing new.

Pass --runxfail to see what these tests really do, which is what you want
while fixing one.
"""

import pytest

BACKEND_MARKER_PREFIX = "fails_on_s3proxy_"
COMMON_MARKER = "fails_on_s3proxy"

# These ask for a bucket whose name S3 rejects and s3proxy accepts, using a
# literal name rather than one built from the configured prefix.  Failing
# means the bucket is created, and nuke_buckets only sees prefixed names, so
# each leaks a bucket for the rest of the session -- enough to break
# test_list_buckets_paginated, which requires an account with no buckets.
# Keep deselecting them; running them as xfail would be a green test that
# reds out an unrelated one later.  Tightening s3proxy's bucket name
# validation would let them pass outright, but it would also reject names
# that S3's legacy us-east-1 rules and some backends still allow, so that is
# a deliberate behaviour change rather than a fix to make here.
LEAK_UNPREFIXED_BUCKET = frozenset({
    "test_bucket_create_naming_dns_dash_at_end",
    "test_bucket_create_naming_dns_dash_dot",
    "test_bucket_create_naming_dns_dot_dash",
    "test_bucket_create_naming_dns_dot_dot",
    "test_bucket_create_naming_dns_underscore",
})


def pytest_addoption(parser):
    parser.addoption(
        "--s3proxy-backend", action="store", default="", metavar="NAMES",
        help="backend under test: azureblob, gcs, localstack, nio2 or swift."
             " Its " + BACKEND_MARKER_PREFIX + "NAME marker becomes a strict"
             " expected failure, as " + COMMON_MARKER + " always does."
             " Accepts a comma-separated list, for a lane that is one"
             " backend in general and a narrower one where they differ:"
             " the transient and filesystem stores share nio2 and part"
             " company over versioning."
             " Omit to expect only the backend-independent failures.")


def pytest_collection_modifyitems(config, items):
    expected = {COMMON_MARKER}
    for backend in config.getoption("--s3proxy-backend").split(","):
        backend = backend.strip()
        if backend:
            expected.add(BACKEND_MARKER_PREFIX + backend)

    kept = []
    deselected = []
    for item in items:
        matched = sorted(expected.intersection(
                mark.name for mark in item.iter_markers()))
        if matched and item.name in LEAK_UNPREFIXED_BUCKET:
            deselected.append(item)
            continue
        if matched:
            item.add_marker(pytest.mark.xfail(
                    strict=True, reason="marked " + ", ".join(matched)))
        kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
