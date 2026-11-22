"""Suggest the marker each failing test needs, from every lane's results.

usage: triage.py RESULTS_DIR [--json OUT]

RESULTS_DIR holds one JUnit file per lane, named LANE.xml, as runlane.sh
writes them.  For each test that fails somewhere, prints the lanes it fails
and passes on, the first failure message, and the markers that would
describe it: fails_on_s3proxy when it fails on every lane that ran it,
otherwise one per backend, folding the two nio2 lanes into
fails_on_s3proxy_nio2 and the two Azurite lanes into
fails_on_s3proxy_azureblob when both fail.  A test whose parameters
disagree on a lane is flagged MIXED-PARAMS, since one marker cannot say
that.  Tests that passed although marked are listed as XPASS.

--json writes the suggestions as {"file::test": [markers]} for addmarks.py.
A suggestion starting with ?? needs a decision by hand.
"""

import json
import os
import sys
import xml.etree.ElementTree as ElementTree

LANES = ['transient', 'filesystem', 'azurite', 'azurite-versioning',
         'fake-gcs-server', 'localstack', 'ministack', 'swift']
SINGLE = (('fake-gcs-server', 'gcs'), ('localstack', 'localstack'),
          ('ministack', 'ministack'), ('swift', 'swift'))


def outcome(case):
    for child in case:
        if child.tag in ('failure', 'error'):
            message = child.get('message') or ''
            if 'XPASS(strict)' in message + (child.text or '')[:200]:
                return 'xpass', message
            return 'fail', message.replace('\n', ' ')[:110]
        if child.tag == 'skipped':
            return ('xfail' if child.get('type') == 'pytest.xfail'
                    else 'skip'), ''
    return 'pass', ''


def main():
    results_dir = sys.argv[1]
    results = {}  # (file, test) -> lane -> {parametrized name: (outcome, msg)}
    lanes_run = []
    for lane in LANES:
        path = os.path.join(results_dir, lane + '.xml')
        if not os.path.exists(path):
            continue
        lanes_run.append(lane)
        for case in ElementTree.parse(path).getroot().iter('testcase'):
            name = case.get('name')
            test = (case.get('classname').split('.')[-1], name.split('[')[0])
            results.setdefault(test, {}).setdefault(lane, {})[name] = (
                outcome(case))
    print('lanes:', lanes_run)

    plan = {}
    for (module, test), by_lane in sorted(results.items()):
        ran = [lane for lane in lanes_run if lane in by_lane]

        def has(lane, wanted):
            return any(o == wanted for o, _ in by_lane[lane].values())

        failed = [lane for lane in ran if has(lane, 'fail')]
        xpassed = [lane for lane in ran if has(lane, 'xpass')]
        if xpassed:
            print('XPASS', module, test, xpassed)
        if not failed:
            continue
        marks = []
        if set(failed) == set(ran):
            marks = ['fails_on_s3proxy']
        else:
            def pair(a, b, both, only_b, only_a):
                fa, fb = a in failed, b in failed
                if (fa or a not in ran) and (fb or b not in ran) and (fa or fb):
                    marks.append(both)
                elif fb:
                    marks.append(only_b)
                elif fa:
                    marks.append(only_a)
            pair('transient', 'filesystem', 'fails_on_s3proxy_nio2',
                 'fails_on_s3proxy_filesystem', '??only-transient')
            pair('azurite', 'azurite-versioning', 'fails_on_s3proxy_azureblob',
                 'fails_on_s3proxy_azureblob_versioning', '??only-azurite')
            for lane, backend in SINGLE:
                if lane in failed:
                    marks.append('fails_on_s3proxy_' + backend)
        mixed = [lane for lane in failed if has(lane, 'pass')]
        note = ''
        if mixed:
            lane = mixed[0]
            note = ' MIXED-PARAMS %s %s' % (lane, {
                n: o for n, (o, _) in by_lane[lane].items()})
        message = next(m for lane in failed
                       for o, m in by_lane[lane].values() if o == 'fail')
        print('%-14s %-62s %s%s\n      fail=%s pass=%s | %s' % (
            module, test, ' '.join(marks), note, ','.join(failed),
            ','.join(lane for lane in ran if lane not in failed), message))
        plan[module + '::' + test] = marks
    if '--json' in sys.argv:
        with open(sys.argv[sys.argv.index('--json') + 1], 'w') as f:
            json.dump(plan, f, indent=1)


if __name__ == '__main__':
    main()
