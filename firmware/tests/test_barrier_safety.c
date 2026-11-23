#include "barrier_controller.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    BarrierController b;
    BarrierController_Init(&b);
    assert(b.state == BARRIER_STATE_CLOSED && b.cycle_state == BARRIER_CYCLE_IDLE);
    assert(b.clearance_started_at_ms == 0 && !b.sensor_fault);
    assert(!BarrierController_RequestEntranceOpen(&b, 0));
    assert(BarrierController_RequestExitOpen(&b)); /* Exit remains available when full. */
    assert(b.state == BARRIER_STATE_OPEN && b.cycle_state == BARRIER_CYCLE_WAITING_FOR_PASSAGE);
    BarrierController_UpdatePassage(&b, false, 100);
    BarrierController_UpdatePassage(&b, false, 1000);
    assert(b.state == BARRIER_STATE_OPEN); /* No passage, no automatic close. */
    BarrierController_UpdatePassage(&b, true, 1100);
    assert(b.cycle_state == BARRIER_CYCLE_PASSAGE_DETECTED);
    BarrierController_UpdatePassage(&b, true, 1200);
    assert(b.state == BARRIER_STATE_OPEN);
    BarrierController_UpdatePassage(&b, false, 1300);
    assert(b.cycle_state == BARRIER_CYCLE_CLEARANCE_PENDING);
    BarrierController_UpdatePassage(&b, false, 1799);
    assert(b.state == BARRIER_STATE_OPEN);
    BarrierController_UpdatePassage(&b, false, 1800);
    assert(b.state == BARRIER_STATE_CLOSED);
    assert(!BarrierController_RequestEntranceOpen(&b, 0));
    assert(BarrierController_RequestEntranceOpen(&b, 1));
    BarrierController_UpdatePassage(&b, true, 2000);
    BarrierController_UpdatePassage(&b, false, 2100);
    BarrierController_UpdatePassage(&b, true, 2600); /* Obstacle at deadline wins. */
    assert(b.state == BARRIER_STATE_OPEN && b.cycle_state == BARRIER_CYCLE_PASSAGE_DETECTED);
    BarrierController_UpdatePassage(&b, false, 2700);
    assert(BarrierController_RequestExitOpen(&b));
    assert(b.clearance_started_at_ms == 2700);
    BarrierController_UpdatePassage(&b, false, 3200);
    assert(b.state == BARRIER_STATE_CLOSED);
    BarrierController_Open(&b);
    BarrierController_ReportSensorFault(&b);
    assert(b.sensor_fault && b.state == BARRIER_STATE_OPEN && b.cycle_state == BARRIER_CYCLE_FAULT);
    BarrierController_UpdatePassage(&b, false, UINT32_MAX);
    assert(b.state == BARRIER_STATE_OPEN);
    assert(!BarrierController_RequestExitOpen(&b));
    BarrierController_Init(&b);
    BarrierController_Open(&b);
    BarrierController_UpdatePassage(&b, true, UINT32_MAX - 50U);
    BarrierController_UpdatePassage(&b, false, UINT32_MAX - 10U);
    BarrierController_UpdatePassage(&b, false, 488U);
    assert(b.state == BARRIER_STATE_OPEN);
    BarrierController_UpdatePassage(&b, false, 489U);
    assert(b.state == BARRIER_STATE_CLOSED);
    puts("PASS: barrier capacity, exit, passage, clearance, obstacle, fault, wraparound");
    return 0;
}
