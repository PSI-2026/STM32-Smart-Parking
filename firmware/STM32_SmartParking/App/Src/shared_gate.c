#include "shared_gate.h"
#include <stddef.h>
#define GATE_CLEAR_MS 500U
#define GATE_ABANDON_MS 30000U

static void emit(SharedGate *g, GateEvent event)
{
    g->event = event;
    ++g->event_sequence;
    g->events[g->event_head] = event;
    g->event_numbers[g->event_head] = g->event_sequence;
    g->event_head = (uint8_t)((g->event_head + 1U) % 8U);
    if (g->event_count < 8U) ++g->event_count;
    else g->event_overflow = true;
}

void SharedGate_Init(SharedGate *g, GateMode mode)
{
    if (g == NULL) return;
    *g = (SharedGate){0};
    g->mode = mode;
    g->state = GATE_CLOSED;
    emit(g, EVENT_RESTART);
}

/* NOLINTBEGIN(bugprone-easily-swappable-parameters): public command API order. */
RequestResult SharedGate_Request(SharedGate *g, GateDirection dir,
                                 uint16_t sequence, bool known,
                                 uint8_t free_count, uint32_t now)
{
    if (g == NULL || dir == DIR_NONE || dir > DIR_EXIT || sequence == 0U)
        return REQUEST_REJECTED;
    if (g->request_seen && g->last_request_sequence == sequence)
        return g->last_request_result == REQUEST_ACCEPTED ?
            REQUEST_DUPLICATE : REQUEST_REJECTED;
    if (g->request_seen &&
        (uint16_t)(sequence - g->last_request_sequence) >= 0x8000U)
        return REQUEST_REJECTED;
    g->request_seen = true;
    g->last_request_sequence = sequence;
    if (g->state != GATE_CLOSED || g->sensor_fault || g->obstruction ||
        (dir == DIR_ENTRY && (!known || free_count == 0U))) {
        g->last_request_result = REQUEST_REJECTED;
        if (dir == DIR_ENTRY) emit(g, EVENT_ENTRY_REJECTED);
        return REQUEST_REJECTED;
    }
    g->last_request_result = REQUEST_ACCEPTED;
    g->last_command_sequence = sequence;
    g->direction = dir;
    g->opened_at_ms = now;
    g->state = GATE_WAIT_PASSAGE;
    emit(g, EVENT_OPEN_REQUESTED);
    emit(g, EVENT_OPENED);
    return REQUEST_ACCEPTED;
}
/* NOLINTEND(bugprone-easily-swappable-parameters) */

void SharedGate_Update(SharedGate *g, bool obstruction, bool sensor_valid,
                       bool simulated_input, uint32_t now)
{
    if (g == NULL) return;
    if (!sensor_valid || (g->mode == GATE_HARDWARE && simulated_input)) {
        if (g->state == GATE_FAULT) return;
        g->sensor_fault = true;
        g->state = GATE_FAULT;
        emit(g, EVENT_SENSOR_FAULT);
        return;
    }
    g->obstruction = obstruction;
    if (g->state == GATE_WAIT_PASSAGE &&
        (uint32_t)(now - g->opened_at_ms) >= GATE_ABANDON_MS) {
        g->timeout_fault = true;
        g->state = GATE_FAULT;
        emit(g, EVENT_TIMEOUT_FAULT);
        return;
    }
    if (g->state == GATE_WAIT_PASSAGE && obstruction) {
        g->state = GATE_OBSTRUCTED;
        emit(g, EVENT_PASSAGE);
    } else if (g->state == GATE_OBSTRUCTED && !obstruction) {
        g->state = GATE_CLEARANCE;
        g->clear_at_ms = now;
    } else if (g->state == GATE_CLEARANCE) {
        if (obstruction) g->state = GATE_OBSTRUCTED;
        else if ((uint32_t)(now - g->clear_at_ms) >= GATE_CLEAR_MS) {
            g->state = GATE_CLOSED;
            emit(g, EVENT_CLOSED);
            ++g->completed_sequence;
            emit(g, g->direction == DIR_ENTRY ? EVENT_ENTRY_COMPLETED : EVENT_EXIT_COMPLETED);
            g->direction = DIR_NONE;
        }
    }
}

bool SharedGate_GetEvent(const SharedGate *g, uint8_t age,
                         uint16_t *sequence, GateEvent *event)
{
    if (g == NULL || sequence == NULL || event == NULL || age >= g->event_count)
        return false;
    uint8_t index = (uint8_t)((g->event_head + 7U - age) % 8U);
    *sequence = g->event_numbers[index];
    *event = g->events[index];
    return true;
}

void SharedGate_ReportCommunicationFault(SharedGate *g)
{
    if (g != NULL) emit(g, EVENT_COMM_FAULT);
}

bool SharedGate_ResetFault(SharedGate *g, bool sensor_valid, bool clear)
{
    if (g == NULL || g->state != GATE_FAULT || !sensor_valid || !clear)
        return false;
    g->sensor_fault = false;
    g->timeout_fault = false;
    g->obstruction = false;
    g->direction = DIR_NONE;
    g->state = GATE_CLOSED;
    emit(g, EVENT_CLOSED);
    return true;
}
