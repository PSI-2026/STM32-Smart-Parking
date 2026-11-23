#ifndef SHARED_GATE_H
#define SHARED_GATE_H
#include <stdbool.h>
#include <stdint.h>
typedef enum { GATE_SIMULATION = 0, GATE_HARDWARE = 1 } GateMode;
typedef enum { GATE_CLOSED = 0, GATE_WAIT_PASSAGE, GATE_OBSTRUCTED,
               GATE_CLEARANCE, GATE_FAULT } GateState;
typedef enum { DIR_NONE = 0, DIR_ENTRY = 1, DIR_EXIT = 2 } GateDirection;
typedef enum { EVENT_NONE = 0, EVENT_OPEN_REQUESTED, EVENT_OPENED,
               EVENT_PASSAGE, EVENT_CLOSED, EVENT_ENTRY_COMPLETED,
               EVENT_EXIT_COMPLETED, EVENT_ENTRY_REJECTED, EVENT_SENSOR_FAULT,
               EVENT_COMM_FAULT, EVENT_RESTART, EVENT_TIMEOUT_FAULT } GateEvent;
typedef enum { REQUEST_REJECTED = 0, REQUEST_ACCEPTED = 1,
               REQUEST_DUPLICATE = 2 } RequestResult;
typedef struct {
    GateMode mode;
    GateState state;
    GateDirection direction;
    GateEvent event;
    uint32_t opened_at_ms;
    uint32_t clear_at_ms;
    uint16_t last_command_sequence;
    uint16_t last_request_sequence;
    RequestResult last_request_result;
    bool request_seen;
    uint16_t event_sequence;
    uint16_t completed_sequence;
    bool sensor_fault;
    bool timeout_fault;
    bool obstruction;
    GateEvent events[8];
    uint16_t event_numbers[8];
    uint8_t event_head;
    uint8_t event_count;
    bool event_overflow;
} SharedGate;

void SharedGate_Init(SharedGate *gate, GateMode mode);
RequestResult SharedGate_Request(SharedGate *gate, GateDirection direction,
                                 uint16_t sequence, bool capacity_known,
                                 uint8_t free_count, uint32_t now_ms);
void SharedGate_Update(SharedGate *gate, bool obstruction, bool sensor_valid,
                       bool simulated_input, uint32_t now_ms);
bool SharedGate_ResetFault(SharedGate *gate, bool sensor_valid, bool clear);
bool SharedGate_GetEvent(const SharedGate *gate, uint8_t age,
                         uint16_t *sequence, GateEvent *event);
void SharedGate_ReportCommunicationFault(SharedGate *gate);
#endif
