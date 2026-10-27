#ifndef INC_BARRIER_CONTROLLER_H_
#define INC_BARRIER_CONTROLLER_H_

#include <stdbool.h>
#include <stdint.h>

typedef enum
{
	BARRIER_STATE_CLOSED = 0,
	BARRIER_STATE_OPEN = 1
} BarrierState;

typedef struct
{
	BarrierState state;
} BarrierController;

void BarrierController_Init(BarrierController *barrier);
void BarrierController_Open(BarrierController *barrier);
void BarrierController_Close(BarrierController *barrier);

BarrierState BarrierController_GetState(const BarrierController *barrier);

bool BarrierController_RequestEntranceOpen(
		BarrierController *barrier,
		uint8_t available_spaces
);

#endif /* INC_BARRIER_CONTROLLER_H_ */
