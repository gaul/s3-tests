"""Check that a rebased fork carries the same decorators as the old one.

usage: verify.py OLD_BASE OLD_TIP NEW_BASE NEW_TIP

For every test, the decorators the fork added to or removed from upstream
on the old base should be added or removed the same way on the new one.
Prints, per file, what differs:

  DUP      a decorator that appears twice on one test
  LOST     the fork changed a test that upstream has since deleted
  DIFF     a change that did not carry over, came back, or crept in
  ADDED    a test the fork itself added, and whether it survived

Nothing printed under a file means its markers carried over intact.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from markermerge import key, parse  # noqa: E402

FILES = ['s3tests/functional/test_s3.py', 's3tests/functional/test_headers.py',
         's3tests/functional/__init__.py']


def decorator(item):
    """The decorator line of an item, without the comments above it or
    one trailing it."""
    line = next((x for x in item.split('\n') if x.startswith('@')), item)
    return line.split('#')[0].strip()


def decorators(rev, path):
    text = subprocess.run(['git', 'show', rev + ':' + path],
                          capture_output=True, text=True).stdout
    return {s[1]: [key(x) for x in s[2]] for s in parse(text) if s[0] == 'test'}


def main():
    old_base, old_tip, new_base, new_tip = sys.argv[1:5]
    for path in FILES:
        ob, ot, nb, nt = (decorators(r, path)
                          for r in (old_base, old_tip, new_base, new_tip))
        print('== %s: tests old-base %d, old-fork %d, new-base %d, new-fork %d'
              % (path, len(ob), len(ot), len(nb), len(nt)))
        for k, items in nt.items():
            # By the decorator alone: the same marker under two different
            # comments is still a duplicate.
            names = [decorator(x) for x in items]
            dup = sorted({n for n in names if names.count(n) > 1})
            if dup:
                print('  DUP', k[0], dup)
        for k in ot:
            if k not in ob:
                print('  ADDED', k[0], 'present' if k in nt else 'gone')
                continue
            added = [x for x in ot[k] if x not in ob[k]]
            removed = [x for x in ob[k] if x not in ot[k]]
            if k not in nt:
                if added or removed:
                    print('  LOST', k[0], '+', added, '-', removed)
                continue
            missing = [x for x in added if x not in nt[k]]
            back = [x for x in removed if x in nt[k]]
            extra = [x for x in nt[k] if x not in nb.get(k, []) and x not in added]
            if missing or back or extra:
                print('  DIFF', k[0], 'missing', missing,
                      'removed-but-present', back, 'extra', extra)


if __name__ == '__main__':
    main()
