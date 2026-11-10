#include "barrier_controller.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>

static void test_clearance_and_redetection(void)
{
    BarrierController barrier;
    BarrierController_Init(&barrier);
    assert(!BarrierController_RequestEntranceOpen(&barrier, 0U));
    assert(BarrierController_GetState(&barrier) == BARRIER_STATE_CLOSED);
    assert(BarrierController_RequestEntranceOpen(&barrier, 1U));
    BarrierController_UpdatePassage(&barrier, false, 1000U);
    assert(barrier.cycle_state == BARRIER_CYCLE_WAITING_FOR_PASSAGE);
    BarrierController_UpdatePassage(&barrier, true, 1100U);
    BarrierController_UpdatePassage(&barrier, false, 1200U);
    BarrierController_UpdatePassage(&barrier, false, 1699U);
    assert(barrier.state == BARRIER_STATE_OPEN);
    /* An obstacle takes priority even at the closing deadline. */
    BarrierController_UpdatePassage(&barrier, true, 1700U);
    assert(barrier.cycle_state == BARRIER_CYCLE_PASSAGE_DETECTED);
    BarrierController_UpdatePassage(&barrier, false, 1800U);
    BarrierController_UpdatePassage(&barrier, false, 2299U);
    assert(barrier.state == BARRIER_STATE_OPEN);
    BarrierController_UpdatePassage(&barrier, false, 2300U);
    assert(barrier.state == BARRIER_STATE_CLOSED);
    assert(barrier.cycle_state == BARRIER_CYCLE_IDLE);
}

static void test_repeated_open_preserves_passage(void)
{
    BarrierController barrier;
    BarrierController_Init(&barrier);
    assert(BarrierController_RequestExitOpen(&barrier));
    BarrierController_UpdatePassage(&barrier, true, 10U);
    assert(BarrierController_RequestExitOpen(&barrier));
    assert(barrier.cycle_state == BARRIER_CYCLE_PASSAGE_DETECTED);
    BarrierController_UpdatePassage(&barrier, false, 20U);
    assert(BarrierController_RequestEntranceOpen(&barrier, 1U));
    BarrierController_Open(&barrier);
    assert(barrier.cycle_state == BARRIER_CYCLE_CLEARANCE_PENDING);
    assert(barrier.clearance_started_at_ms == 20U);
    BarrierController_UpdatePassage(&barrier, false, 520U);
    assert(barrier.state == BARRIER_STATE_CLOSED);
}

static void test_fault_blocks_open_and_close(void)
{
    BarrierController barrier;
    BarrierController_Init(&barrier);
    BarrierController_ReportSensorFault(&barrier);
    BarrierController_Open(&barrier);
    assert(barrier.state == BARRIER_STATE_CLOSED);
    assert(barrier.cycle_state == BARRIER_CYCLE_FAULT);
    assert(!BarrierController_RequestEntranceOpen(&barrier, 4U));
    assert(!BarrierController_RequestExitOpen(&barrier));

    BarrierController_Init(&barrier);
    BarrierController_Open(&barrier);
    BarrierController_UpdatePassage(&barrier, true, 10U);
    BarrierController_UpdatePassage(&barrier, false, 20U);
    BarrierController_ReportSensorFault(&barrier);
    BarrierController_Open(&barrier);
    BarrierController_UpdatePassage(&barrier, false, 10000U);
    assert(barrier.state == BARRIER_STATE_OPEN);
    assert(barrier.cycle_state == BARRIER_CYCLE_FAULT);
    assert(barrier.sensor_fault);
}

static void test_tick_wraparound(void)
{
    BarrierController barrier;
    BarrierController_Init(&barrier);
    BarrierController_Open(&barrier);
    BarrierController_UpdatePassage(&barrier, true, UINT32_MAX - 200U);
    BarrierController_UpdatePassage(&barrier, false, UINT32_MAX - 100U);
    BarrierController_UpdatePassage(&barrier, false, 398U);
    assert(barrier.state == BARRIER_STATE_OPEN);
    BarrierController_UpdatePassage(&barrier, false, 399U);
    assert(barrier.state == BARRIER_STATE_CLOSED);
}

int main(void)
{
    test_clearance_and_redetection();
    test_repeated_open_preserves_passage();
    test_fault_blocks_open_and_close();
    test_tick_wraparound();
    BarrierController_Open(NULL);
    BarrierController_ReportSensorFault(NULL);
    BarrierController_UpdatePassage(NULL, false, 0U);
    assert(!BarrierController_RequestEntranceOpen(NULL, 1U));
    assert(!BarrierController_RequestExitOpen(NULL));
    puts("PASS: clearance, redetection, repeated open, faults, tick wraparound, null requests");
    return 0;
}
