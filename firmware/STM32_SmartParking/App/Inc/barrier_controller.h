#ifndef INC_BARRIER_CONTROLLER_H_
#define INC_BARRIER_CONTROLLER_H_

#include <stdbool.h>
#include <stdint.h>

typedef enum
{
	BARRIER_STATE_CLOSED = 0,
	BARRIER_STATE_OPEN = 1
} BarrierState;

typedef enum
{
    BARRIER_CYCLE_IDLE = 0,
    BARRIER_CYCLE_WAITING_FOR_PASSAGE,
    BARRIER_CYCLE_PASSAGE_DETECTED,
    BARRIER_CYCLE_CLEARANCE_PENDING,
    BARRIER_CYCLE_FAULT
} BarrierCycleState;

typedef struct
{
	BarrierState state;
	BarrierCycleState cycle_state;
	uint32_t clearance_started_at_ms;
	bool sensor_fault;
} BarrierController;

void BarrierController_Init(BarrierController *barrier);
void BarrierController_Open(BarrierController *barrier);
void BarrierController_ReportSensorFault(BarrierController *barrier);

void BarrierController_UpdatePassage(
    BarrierController *barrier,
    bool passage_detected,
	uint32_t now_ms
);

BarrierState BarrierController_GetState(const BarrierController *barrier);

bool BarrierController_RequestEntranceOpen(
		BarrierController *barrier,
		uint8_t available_spaces
);

bool BarrierController_RequestExitOpen(BarrierController *barrier);

#endif /* INC_BARRIER_CONTROLLER_H_ */
