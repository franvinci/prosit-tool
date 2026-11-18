import assert from 'node:assert/strict';
import { test } from 'node:test';

import { extractXesColumns, guessColumnMapping, parseCsvHeaderLine } from '../../prosit_tool/static/js/features/upload-columns.js';

test('a CSV header is split on commas', () => {
    assert.deepEqual(parseCsvHeaderLine('Case,Task, Done ,Who'), ['Case', 'Task', 'Done', 'Who']);
});

test('a quoted column name may contain commas and doubled quotes', () => {
    assert.deepEqual(parseCsvHeaderLine('id,"Amount, total","say ""hi"""'), ['id', 'Amount, total', 'say "hi"']);
});

test('empty column names are left out', () => {
    assert.deepEqual(parseCsvHeaderLine('a,,b,'), ['a', 'b']);
});

const XES = `<?xml version="1.0" encoding="utf-8" ?>
<log xes.version="1849-2016">
  <string key="creator" value="test" />
  <trace>
    <string key="concept:name" value="case 1" />
    <float key="amount" value="12.5" />
    <event>
      <string key="concept:name" value="A" />
      <string key="org:resource" value="r1" />
      <date key="time:timestamp" value="2024-01-01T08:00:00+00:00" />
    </event>
    <event>
      <string key="concept:name" value="B" />
      <string key="only:later" value="x" />
    </event>
  </trace>
</log>`;

test('the columns of an XES are the keys of the first trace and of its first event', () => {
    assert.deepEqual(extractXesColumns(XES), ['case:concept:name', 'case:amount', 'concept:name', 'org:resource', 'time:timestamp']);
});

test('text that is not an event log has no columns', () => {
    assert.deepEqual(extractXesColumns('this is not an event log'), []);
});

test('the standard names of an event log are recognized', () => {
    const headers = ['case:concept:name', 'concept:name', 'time:timestamp', 'start:timestamp', 'org:resource', 'case:amount'];
    assert.deepEqual(guessColumnMapping(headers), {
        case_id: 'case:concept:name',
        activity: 'concept:name',
        end_ts: 'time:timestamp',
        start_ts: 'start:timestamp',
        resource: 'org:resource',
    });
});

test('common names of a spreadsheet are recognized, whatever their case', () => {
    assert.deepEqual(guessColumnMapping(['Case ID', 'Activity', 'End Time', 'Start Time', 'Resource']), {
        case_id: 'Case ID',
        activity: 'Activity',
        end_ts: 'End Time',
        start_ts: 'Start Time',
        resource: 'Resource',
    });
});

test('a column nothing looks like is left for the user to choose', () => {
    assert.deepEqual(guessColumnMapping(['x', 'y']), { case_id: '', activity: '', end_ts: '', start_ts: '', resource: '' });
});
