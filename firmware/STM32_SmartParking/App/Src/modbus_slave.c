#include "modbus_slave.h"
#include <stddef.h>
#include <string.h>
#define COMMS_TTL_MS 5000U

uint16_t ModbusSlave_Crc(const uint8_t *data, size_t length)
{
    uint16_t crc = 0xffffU;
    for (size_t i = 0; i < length; ++i) {
        uint32_t work = (uint32_t)crc ^ data[i];
        for (uint8_t bit = 0; bit < 8U; ++bit)
            work = (work & 1U) != 0U ? (work >> 1U) ^ 0xa001U :
                                        (work >> 1U);
        crc = (uint16_t)work;
    }
    return crc;
}

static uint16_t be16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] * 256U + p[1]);
}
static void put16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)(value >> 8U);
    p[1] = (uint8_t)value;
}
static size_t finish(uint8_t *response, size_t length)
{
    uint16_t crc = ModbusSlave_Crc(response, length);
    response[length] = (uint8_t)crc;
    response[length + 1U] = (uint8_t)(crc >> 8U);
    return length + 2U;
}
/* NOLINTBEGIN(bugprone-easily-swappable-parameters): RTU exception fields. */
/* NOLINTBEGIN(bugprone-easily-swappable-parameters): RTU exception fields. */
static size_t exception(uint8_t *response, uint8_t id, uint8_t function,
                        uint8_t code)
{
    response[0] = id;
    response[1] = (uint8_t)(function | 0x80U);
    response[2] = code;
    return finish(response, 3U);
}
/* NOLINTEND(bugprone-easily-swappable-parameters) */
/* NOLINTEND(bugprone-easily-swappable-parameters) */

void ModbusSlave_Init(ModbusSlave *s, uint8_t id, HybridParking *p, SharedGate *g)
{
    if (s == NULL) return;
    *s = (ModbusSlave){0};
    s->node_id = id;
    s->parking = p;
    s->gate = g;
}

void ModbusSlave_Tick(ModbusSlave *s, uint32_t now)
{
    if (s == NULL || !s->connected ||
        (uint32_t)(now - s->last_rx_ms) < COMMS_TTL_MS) return;
    s->connected = false;
    HybridParking_InvalidateSimulation(s->parking);
    SharedGate_ReportCommunicationFault(s->gate);
}

static bool read_register(const ModbusSlave *s, uint16_t address, uint16_t *value)
{
    const SharedGate *g = s->gate;
    const HybridParking *p = s->parking;
    switch (address) {
    case 0x0000: *value = s->node_id; return true;
    case 0x0001: *value = 0x0100U; return true;
    case 0x0002: *value = g != NULL && g->state == GATE_FAULT ? 2U : 1U; return true;
    case 0x0003: *value = p != NULL ? (uint16_t)(HybridParking_OccupiedMask(p) & 1U) : 0U; return true;
    case 0x0004: *value = p != NULL ? HybridParking_OccupiedMask(p) : 0U; return true;
    case 0x0005: *value = p != NULL ? HybridParking_KnownMask(p) : 0U; return true;
    case 0x0006: *value = p != NULL ? HybridParking_FreeCount(p) : 0U; return true;
    case 0x0007: *value = g != NULL ? g->state : GATE_CLOSED; return true;
    case 0x0008: *value = g != NULL ? g->direction : DIR_NONE; return true;
    case 0x0009: *value = g != NULL ?
        (uint16_t)((g->sensor_fault ? 1U : 0U) |
                   (g->timeout_fault ? 2U : 0U)) : 0U; return true;
    case 0x000a: *value = s->connected ? 1U : 0U; return true;
    case 0x000b: *value = g != NULL ? g->last_command_sequence : 0U; return true;
    case 0x000c: *value = g != NULL ? g->completed_sequence : 0U; return true;
    case 0x000d: *value = g != NULL ? g->event_sequence : 0U; return true;
    case 0x000e: *value = g != NULL ? g->event : EVENT_NONE; return true;
    case 0x000f: *value = s->last_result; return true;
    case 0x0010: *value = g != NULL && g->event_overflow ? 1U : 0U; return true;
    default:
        if (address >= 0x0020U && address < 0x0030U && g != NULL) {
            uint16_t sequence;
            GateEvent event;
            uint8_t age = (uint8_t)((address - 0x0020U) / 2U);
            if (!SharedGate_GetEvent(g, age, &sequence, &event)) {
                *value = 0U;
                return true;
            }
            *value = ((address & 1U) == 0U) ? sequence : (uint16_t)event;
            return true;
        }
        return false;
    }
}

/* NOLINTBEGIN(bugprone-easily-swappable-parameters): register address/value pair. */
/* NOLINTBEGIN(bugprone-easily-swappable-parameters): register address/value pair. */
static bool write_register(ModbusSlave *s, uint16_t address, uint16_t value,
                           uint32_t now)
{
    SharedGate *g = s->gate;
    switch (address) {
    case 0x0100:
        if (value == 0U) return false;
        s->command_sequence = value;
        return true;
    case 0x0101:
        if (g == NULL || (value != DIR_ENTRY && value != DIR_EXIT)) return false;
        s->last_result = (uint8_t)SharedGate_Request(g, (GateDirection)value,
            s->command_sequence, s->parking != NULL &&
            HybridParking_CapacityKnown(s->parking),
            HybridParking_FreeCount(s->parking), now);
        return s->last_result != REQUEST_REJECTED;
    case 0x0102:
        if ((value & 0xfff0U) != 0U ||
            (s->parking != NULL && s->parking->source[0] == SOURCE_HARDWARE &&
             (value & 1U) != 0U)) return false;
        s->sim_occupied = value;
        return true;
    case 0x0103:
        if ((value & 0xfff0U) != 0U || s->parking == NULL) return false;
        if (s->command_sequence == 0U) return false;
        if (s->sim_seen && s->command_sequence == s->sim_last_sequence)
            return true; /* Retry does not refresh the freshness timer. */
        if (s->sim_seen &&
            (uint16_t)(s->command_sequence - s->sim_last_sequence) >= 0x8000U)
            return false;
        s->sim_known = value;
        if (!HybridParking_SetSimulation(s->parking,
            (uint8_t)s->sim_occupied, (uint8_t)value, now)) return false;
        s->sim_last_sequence = s->command_sequence;
        s->sim_seen = true;
        return true;
    case 0x0104:
        if (value > 1U || g == NULL || g->mode != GATE_SIMULATION) return false;
        s->simulated_passage = value != 0U;
        return true;
    case 0x0105:
        return value == 0xa55aU && g != NULL && g->mode == GATE_SIMULATION &&
            SharedGate_ResetFault(g, true, !s->simulated_passage);
    default: return false;
    }
}
/* NOLINTEND(bugprone-easily-swappable-parameters) */
/* NOLINTEND(bugprone-easily-swappable-parameters) */

/* NOLINTBEGIN(bugprone-easily-swappable-parameters): bounded request/response API. */
/* NOLINTBEGIN(bugprone-easily-swappable-parameters): bounded RTU frame API. */
size_t ModbusSlave_Process(ModbusSlave *s, const uint8_t *req, size_t length,
                           uint8_t *res, size_t capacity, uint32_t now)
{
    if (s == NULL || req == NULL || res == NULL || length < 4U ||
        length > MODBUS_MAX_ADU || capacity < 5U || req[0] != s->node_id ||
        s->node_id == 0U || s->node_id > 247U) return 0U;
    uint16_t crc = ModbusSlave_Crc(req, length - 2U);
    if (req[length - 2U] != (uint8_t)crc ||
        req[length - 1U] != (uint8_t)(crc >> 8U)) return 0U;
    s->connected = true;
    s->last_rx_ms = now;
    uint8_t fn = req[1];
    if (fn == 3U) {
        if (length != 8U) return exception(res, s->node_id, fn, 3U);
        uint16_t start = be16(req + 2U), count = be16(req + 4U);
        if (count == 0U || count > 125U ||
            capacity < (size_t)count * 2U + 5U) return exception(res, s->node_id, fn, 3U);
        for (uint16_t i = 0U; i < count; ++i) {
            uint16_t value;
            if (!read_register(s, (uint16_t)(start + i), &value) ||
                (uint32_t)start + i > UINT16_MAX)
                return exception(res, s->node_id, fn, 2U);
        }
        res[0] = s->node_id; res[1] = fn; res[2] = (uint8_t)(count * 2U);
        for (uint16_t i = 0U; i < count; ++i) {
            uint16_t value = 0U;
            (void)read_register(s, (uint16_t)(start + i), &value);
            put16(res + 3U + (size_t)i * 2U, value);
        }
        return finish(res, 3U + (size_t)count * 2U);
    }
    if (fn == 6U) {
        if (length != 8U) return exception(res, s->node_id, fn, 3U);
        uint16_t address = be16(req + 2U), value = be16(req + 4U);
        if (address < 0x0100U || address > 0x0105U)
            return exception(res, s->node_id, fn, 2U);
        if (!write_register(s, address, value, now))
            return exception(res, s->node_id, fn, 3U);
        memcpy(res, req, 6U);
        return finish(res, 6U);
    }
    return exception(res, s->node_id, fn, 1U);
}
/* NOLINTEND(bugprone-easily-swappable-parameters) */
/* NOLINTEND(bugprone-easily-swappable-parameters) */
