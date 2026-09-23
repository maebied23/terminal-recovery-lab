import assert from 'node:assert/strict';
import {bookingChanges,reservationLabel} from '../src/booking.ts';
const row={job_id:'move-a',start:1,end:8,resources:['yard','tractor'],source_id:'A1',target_id:'D4'};
assert.deepEqual(bookingChanges([row],[{...row}])[0].changes,[]);
assert.deepEqual(bookingChanges([row],[{...row,start:2}])[0].changes,['Timing']);
assert.deepEqual(bookingChanges([row],[{...row,resources:['other','tractor']}])[0].changes,['Equipment']);
assert.deepEqual(bookingChanges([row],[{...row,target_id:'D3'}])[0].changes,['Route']);
assert.deepEqual(bookingChanges([],[row])[0].changes,['Added work']);
assert.equal(bookingChanges([row],[]).length,0);
console.log('6 booking comparison assertions passed');

assert.equal(reservationLabel('approved','interrupted','queued',false),'Released');
assert.equal(reservationLabel('approved','interrupted','running',false),'Occupied');
assert.equal(reservationLabel('approved','executing','completed',false),'Completed');
assert.equal(reservationLabel('approved','approved','queued',false),'Booked');
assert.equal(reservationLabel('proposal','interrupted','queued',false),'Proposed');
assert.equal(reservationLabel('proposal',undefined,'running',true),'Frozen at comparison');
console.log('6 reservation state assertions passed');
