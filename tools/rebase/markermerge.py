"""Merge one test file of a fork commit onto a new upstream base.

usage: markermerge.py PARENT COMMIT HEAD OUT

PARENT and COMMIT are the file before and after the fork commit, HEAD the
file on the branch being rebuilt; the result goes to OUT.  A plain three-way
merge conflicts on nearly every marker commit, because a marker sits on the
line above a def that upstream keeps editing nearby.  So the decorators
above each test are taken apart from the rest: the commit's per-test
decorator changes (markers added, removed, or with their comments) are
applied to HEAD's decorators for the same test, and everything else goes
through git merge-file.

Exits 0 when merged, with notes on stderr about decorator changes that no
longer apply (the test is gone, or HEAD already has the change); exits 2
when the bodies conflict, leaving conflict markers in OUT.
"""

import os
import re
import subprocess
import sys
import tempfile

DEF = re.compile(r'^(?:async\s+)?def\s+(\w+)\s*\(')
PLACEHOLDER = re.compile(r'^<<(\w+)#(\d+)>>$')


def parse(text):
    """Split a test file into ('text', lines) and ('test', key, items)
    segments.  items are the decorators above a def, each a list of lines
    with the comments that precede it; key is (name, occurrence)."""
    lines = text.split('\n')
    segs = []
    cur = []
    seen = {}
    for line in lines:
        m = DEF.match(line)
        if m:
            # The contiguous block above the def that holds a decorator.
            j = len(cur)
            while (j > 0 and cur[j - 1].strip() != '' and
                   not DEF.match(cur[j - 1]) and
                   cur[j - 1].startswith(('@', '#', ' ', '\t', ')'))):
                j -= 1
            deco = cur[j:]
            if not any(d.startswith('@') for d in deco):
                deco = []
                j = len(cur)
            else:
                while deco and not deco[0].startswith(('@', '#')):
                    j += 1
                    deco = deco[1:]
            cur = cur[:j]
            items = []
            pending = []
            for d in deco:
                if d.startswith('@'):
                    items.append(pending + [d])
                    pending = []
                elif d.startswith('#'):
                    pending.append(d)
                elif items:
                    items[-1].append(d)
                else:
                    pending.append(d)
            if pending:
                if items:
                    items[-1].extend(pending)
                else:
                    items.append(pending)
            name = m.group(1)
            k = seen.get(name, 0)
            seen[name] = k + 1
            segs.append(('text', cur))
            cur = []
            segs.append(('test', (name, k), items))
        cur.append(line)
    segs.append(('text', cur))
    return segs


def key(item):
    return '\n'.join(line.rstrip() for line in item)


def tests(segs):
    return {s[1]: s[2] for s in segs if s[0] == 'test'}


def skeleton(segs):
    return '\n'.join('\n'.join(s[1]) if s[0] == 'text' else '<<%s#%d>>' % s[1]
                     for s in segs)


def merge(parent, commit, head):
    """-> (merged text, notes, conflicted)"""
    p_segs, c_segs, h_segs = parse(parent), parse(commit), parse(head)
    pd, cd, hd = tests(p_segs), tests(c_segs), tests(h_segs)
    notes = []
    for name, ci in cd.items():
        if name not in pd:
            continue  # a test the commit adds comes in whole with the body
        pk = [key(x) for x in pd[name]]
        ck = [key(x) for x in ci]
        if pk == ck:
            continue
        removed = [x for x in pk if x not in ck]
        added = [x for x in ci if key(x) not in pk]
        if name not in hd:
            notes.append('MISSING %s: -%s +%s' % (
                name[0], removed, [key(a) for a in added]))
            continue
        hi = hd[name]
        for r in removed:
            idx = [n for n, x in enumerate(hi) if key(x) == r]
            if idx:
                del hi[idx[0]]
            else:
                notes.append('ALREADY-GONE %s: %s' % (name[0], r))
        for a in added:
            hk = [key(x) for x in hi]
            if key(a) in hk:
                notes.append('ALREADY-THERE %s: %s' % (name[0], key(a)))
                continue
            # Keep the commit's order: after the nearest earlier neighbour
            # HEAD also has, else before the nearest later one.
            pos = ck.index(key(a))
            at = None
            for q in range(pos - 1, -1, -1):
                if ck[q] in hk:
                    at = hk.index(ck[q]) + 1
                    break
            if at is None:
                for q in range(pos + 1, len(ck)):
                    if ck[q] in hk:
                        at = hk.index(ck[q])
                        break
            hi.insert(len(hi) if at is None else at, a)

    with tempfile.TemporaryDirectory() as d:
        paths = {}
        for n, segs in (('head', h_segs), ('base', p_segs), ('commit', c_segs)):
            paths[n] = os.path.join(d, n)
            with open(paths[n], 'w') as f:
                f.write(skeleton(segs))
        r = subprocess.run(
            ['git', 'merge-file', '-p', '-L', 'HEAD', '-L', 'base',
             '-L', 'commit', paths['head'], paths['base'], paths['commit']],
            capture_output=True, text=True)
    out = []
    for line in r.stdout.split('\n'):
        m = PLACEHOLDER.match(line)
        if m:
            k = (m.group(1), int(m.group(2)))
            items = hd.get(k, cd.get(k))
            if items is None:
                notes.append('NO-ITEMS %s' % k[0])
                items = []
            for it in items:
                out.extend(it)
        else:
            out.append(line)
    return '\n'.join(out), notes, r.returncode != 0


def main():
    parent, commit, head = (open(p).read() for p in sys.argv[1:4])
    text, notes, conflicted = merge(parent, commit, head)
    with open(sys.argv[4], 'w') as f:
        f.write(text)
    for n in notes:
        sys.stderr.write(n + '\n')
    if conflicted:
        sys.stderr.write('BODY-CONFLICTS\n')
        sys.exit(2)


if __name__ == '__main__':
    main()
