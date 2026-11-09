#include "barrier_controller.h"
#include <stddef.h>

static void BarrierController_Close(BarrierController *barrier);

static bool BarrierController_RequestClose(
    BarrierController *barrier,
    bool passage_clear
);

#define BARRIER_CLEARANCE_DELAY_MS 500U

void BarrierController_Init(BarrierController *barrier)
{
	barrier->state = BARRIER_STATE_CLOSED;
	barrier->cycle_state = BARRIER_CYCLE_IDLE;
	barrier->clearance_started_at_ms = 0U;
	barrier->sensor_fault = false;
}

void BarrierController_Open(BarrierController *barrier)
{
	barrier->state = BARRIER_STATE_OPEN;
	barrier->cycle_state = BARRIER_CYCLE_WAITING_FOR_PASSAGE;
}

void BarrierController_ReportSensorFault(BarrierController *barrier)
{
    if (barrier == NULL)
    {
        return;
    }

    barrier->sensor_fault = true;
    barrier->cycle_state = BARRIER_CYCLE_FAULT;
}

static void BarrierController_Close(BarrierController *barrier)
{
	barrier->state = BARRIER_STATE_CLOSED;
	barrier->cycle_state = BARRIER_CYCLE_IDLE;
}

void BarrierController_UpdatePassage(
    BarrierController *barrier,
    bool passage_detected,
    uint32_t now_ms
)
{
    if (barrier == NULL ||
        barrier->sensor_fault ||
        barrier->state != BARRIER_STATE_OPEN)
    {
        return;
    }

    switch (barrier->cycle_state)
    {
        case BARRIER_CYCLE_WAITING_FOR_PASSAGE:
            if (passage_detected)
            {
                barrier->cycle_state =
                    BARRIER_CYCLE_PASSAGE_DETECTED;
            }
            break;

        case BARRIER_CYCLE_PASSAGE_DETECTED:
            if (!passage_detected)
            {
                barrier->clearance_started_at_ms = now_ms;
                barrier->cycle_state =
                    BARRIER_CYCLE_CLEARANCE_PENDING;
            }
            break;

        case BARRIER_CYCLE_CLEARANCE_PENDING:
            if (passage_detected)
            {
                barrier->cycle_state =
                    BARRIER_CYCLE_PASSAGE_DETECTED;
            }
            else if ((uint32_t)(now_ms - barrier->clearance_started_at_ms)
                     >= BARRIER_CLEARANCE_DELAY_MS)
            {
                (void)BarrierController_RequestClose(barrier, true);
            }
            break;

        default:
            break;
    }
}

BarrierState BarrierController_GetState(const BarrierController *barrier)
{
	return barrier->state;
}

bool BarrierController_RequestEntranceOpen(
		BarrierController *barrier,
		uint8_t available_spaces
)
{
	if (barrier == NULL ||
	    barrier->sensor_fault ||
	    available_spaces == 0U)
	{
		return false;
	}

	BarrierController_Open(barrier);
	return true;
}

bool BarrierController_RequestExitOpen(BarrierController *barrier)
{
    if (barrier == NULL || barrier->sensor_fault)
    {
        return false;
    }

    BarrierController_Open(barrier);
    return true;
}

static bool BarrierController_RequestClose(
    BarrierController *barrier,
    bool passage_clear
)
{
    if (barrier == NULL || barrier->sensor_fault || !passage_clear)
    {
        return false;
    }

    BarrierController_Close(barrier);
    return true;
}
