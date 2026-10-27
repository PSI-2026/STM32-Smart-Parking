#include "barrier_controller.h"
#include <stddef.h>

void BarrierController_Init(BarrierController *barrier)
{
	barrier->state = BARRIER_STATE_CLOSED;
}

void BarrierController_Open(BarrierController *barrier)
{
	barrier->state = BARRIER_STATE_OPEN;
}

void BarrierController_Close(BarrierController *barrier)
{
	barrier->state = BARRIER_STATE_CLOSED;
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
	if (barrier == NULL || available_spaces == 0U)
	{
		return false;
	}

	BarrierController_Open(barrier);
	return true;
}
