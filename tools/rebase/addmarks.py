"""Add markers above test functions.

usage: addmarks.py FILE < lines of "TEST MARKER [MARKER...]"
       addmarks.py --json PLAN.json

The first form adds each MARKER as @pytest.mark.MARKER above def TEST in
FILE.  The second takes the suggestions triage.py --json wrote, keyed
"module::test", for the files under s3tests/functional.  A marker already
on the test is left alone; a test that is not found is an error.
Suggestions starting with ?? are skipped and reported, as they need a
decision by hand.  Review the result: a marker needs a comment saying why.
"""

import json
import sys


def add(path, want):
    with open(path) as f:
        lines = f.read().split('\n')
    out = []
    done = set()
    for line in lines:
        if line.startswith('def '):
            name = line[4:].split('(')[0]
            if name in want:
                j = len(out)
                have = set()
                while j > 0 and out[j - 1].startswith(('@', '#')):
                    j -= 1
                    have.add(out[j].strip())
                for marker in want[name]:
                    decorator = '@pytest.mark.' + marker
                    if decorator not in have:
                        out.append(decorator)
                done.add(name)
        out.append(line)
    with open(path, 'w') as f:
        f.write('\n'.join(out))
    return set(want) - done


def main():
    if sys.argv[1] == '--json':
        with open(sys.argv[2]) as f:
            plan = json.load(f)
        by_file = {}
        for name, markers in plan.items():
            module, test = name.split('::')
            keep = [m for m in markers if not m.startswith('??')]
            for m in markers:
                if m.startswith('??'):
                    print('decide by hand:', name, m)
            if keep:
                path = 's3tests/functional/%s.py' % module
                by_file.setdefault(path, {})[test] = keep
    else:
        want = {}
        for line in sys.stdin:
            parts = line.split()
            if parts:
                want[parts[0]] = parts[1:]
        by_file = {sys.argv[1]: want}
    missing = set()
    for path, want in by_file.items():
        missing |= add(path, want)
    if missing:
        sys.exit('not found: %s' % ', '.join(sorted(missing)))


if __name__ == '__main__':
    main()
