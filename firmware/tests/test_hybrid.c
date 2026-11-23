#include "hybrid_parking.h"
#include "shared_gate.h"
#include "buzzer.h"
#include "modbus_slave.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static size_t frame(uint8_t *p, size_t length)
{
    uint16_t crc = ModbusSlave_Crc(p, length);
    p[length] = (uint8_t)crc;
    p[length + 1U] = (uint8_t)(crc >> 8U);
    return length + 2U;
}
static size_t write6(ModbusSlave *s, uint16_t address, uint16_t value,
                     uint32_t now)
{
    uint8_t request[8] = {s->node_id, 6U, (uint8_t)(address >> 8U),
        (uint8_t)address, (uint8_t)(value >> 8U), (uint8_t)value, 0U, 0U};
    uint8_t reply[MODBUS_MAX_ADU];
    return ModbusSlave_Process(s, request, frame(request, 6U),
                               reply, sizeof reply, now);
}
static void parking_test(void)
{
    HybridParking p;
    HybridParking_Init(&p, true);
    assert(HybridParking_KnownMask(&p) == 0U);
    HybridParking_SetPhysical(&p, true);
    assert(HybridParking_OccupiedMask(&p) == 1U);
    assert(!HybridParking_CapacityKnown(&p));
    assert(!HybridParking_SetSimulation(&p, 3U, 0xeU, 10U));
    assert(HybridParking_SetSimulation(&p, 0xaU, 0xeU, 10U));
    assert(HybridParking_CapacityKnown(&p));
    assert(HybridParking_FreeCount(&p) == 1U);
    HybridParking_Tick(&p, 5009U);
    assert(HybridParking_CapacityKnown(&p));
    HybridParking_Tick(&p, 5010U);
    assert(HybridParking_KnownMask(&p) == 1U);
}
static void gate_test(void)
{
    SharedGate g;
    SharedGate_Init(&g, GATE_SIMULATION);
    assert(SharedGate_Request(&g, DIR_ENTRY, 1U, false, 1U, 0U) == REQUEST_REJECTED);
    assert(SharedGate_Request(&g, DIR_ENTRY, 1U, true, 1U, 0U) == REQUEST_REJECTED);
    assert(SharedGate_Request(&g, DIR_ENTRY, 2U, true, 1U, 0U) == REQUEST_ACCEPTED);
    assert(SharedGate_Request(&g, DIR_ENTRY, 2U, true, 1U, 1U) == REQUEST_DUPLICATE);
    assert(SharedGate_Request(&g, DIR_EXIT, 3U, true, 0U, 1U) == REQUEST_REJECTED);
    SharedGate_Update(&g, true, true, true, 100U);
    SharedGate_Update(&g, false, true, true, 200U);
    SharedGate_Update(&g, true, true, true, 700U);
    assert(g.state == GATE_OBSTRUCTED);
    SharedGate_Update(&g, false, true, true, 800U);
    SharedGate_Update(&g, false, true, true, 1300U);
    assert(g.state == GATE_CLOSED && g.completed_sequence == 1U);
    uint16_t event_sequence;
    GateEvent event;
    assert(SharedGate_GetEvent(&g, 0U, &event_sequence, &event));
    assert(event == EVENT_ENTRY_COMPLETED && event_sequence == g.event_sequence);
    assert(SharedGate_Request(&g, DIR_EXIT, 4U, false, 0U, UINT32_MAX - 50U) == REQUEST_ACCEPTED);
    SharedGate_Update(&g, true, true, true, UINT32_MAX - 40U);
    SharedGate_Update(&g, false, true, true, UINT32_MAX - 30U);
    SharedGate_Update(&g, false, true, true, 469U);
    assert(g.state == GATE_CLOSED && g.completed_sequence == 2U);
    assert(SharedGate_Request(&g, DIR_EXIT, 5U, false, 0U, 500U) == REQUEST_ACCEPTED);
    SharedGate_Update(&g, false, true, true, 30500U);
    assert(g.state == GATE_FAULT && g.timeout_fault && g.event == EVENT_TIMEOUT_FAULT);
    assert(SharedGate_ResetFault(&g, true, true));
    assert(!g.timeout_fault);
    SharedGate_Init(&g, GATE_HARDWARE);
    assert(SharedGate_Request(&g, DIR_EXIT, 1U, false, 0U, 0U) == REQUEST_ACCEPTED);
    SharedGate_Update(&g, true, true, true, 1U);
    assert(g.state == GATE_FAULT);
}
static void buzzer_test(void)
{
    Buzzer b;
    Buzzer_Init(&b, true);
    Buzzer_OnEvent(&b, EVENT_OPENED, 1U, 0U);
    assert(b.output && b.remaining == 1U);
    Buzzer_OnEvent(&b, EVENT_OPENED, 1U, 1U);
    assert(b.remaining == 1U);
    Buzzer_Tick(&b, 100U);
    assert(!b.output && b.remaining == 0U);
    Buzzer_OnEvent(&b, EVENT_CLOSED, 2U, 200U);
    Buzzer_Tick(&b, 300U);
    Buzzer_Tick(&b, 400U);
    assert(b.output && b.remaining == 1U);
    Buzzer_Tick(&b, 500U);
    assert(!b.output && b.remaining == 0U);
    Buzzer_OnEvent(&b, EVENT_SENSOR_FAULT, 3U, 600U);
    assert(b.remaining == 3U);
}
static void modbus_test(void)
{
    assert(ModbusSlave_Crc((const uint8_t *)"123456789", 9U) == 0x4b37U);
    HybridParking p;
    SharedGate g;
    ModbusSlave s;
    HybridParking_Init(&p, true);
    SharedGate_Init(&g, GATE_SIMULATION);
    ModbusSlave_Init(&s, 1U, &p, &g);
    uint8_t req[8] = {1U, 3U, 0U, 0U, 0U, 2U, 0U, 0U};
    uint8_t res[MODBUS_MAX_ADU];
    size_t n = frame(req, 6U);
    assert(ModbusSlave_Process(&s, req, n, res, sizeof res, 1U) == 9U);
    assert(res[2] == 4U && res[4] == 1U);
    req[0] = 2U; frame(req, 6U);
    assert(ModbusSlave_Process(&s, req, n, res, sizeof res, 2U) == 0U);
    req[0] = 1U; req[7] ^= 1U;
    assert(ModbusSlave_Process(&s, req, n, res, sizeof res, 2U) == 0U);
    req[1] = 4U; frame(req, 6U);
    assert(ModbusSlave_Process(&s, req, n, res, sizeof res, 2U) == 5U);
    assert(res[1] == 0x84U && res[2] == 1U);
    assert(write6(&s, 0x0100U, 10U, 3U) == 8U);
    assert(write6(&s, 0x0102U, 0U, 3U) == 8U);
    assert(write6(&s, 0x0103U, 0xeU, 3U) == 8U);
    assert(write6(&s, 0x0103U, 0xeU, 100U) == 8U);
    assert(p.sim_updated_ms == 3U);
    assert(write6(&s, 0x0100U, 9U, 101U) == 8U);
    assert(write6(&s, 0x0103U, 0xeU, 101U) == 5U);
    HybridParking_SetPhysical(&p, false);
    assert(write6(&s, 0x0100U, 11U, 4U) == 8U);
    assert(write6(&s, 0x0101U, 1U, 4U) == 8U);
    assert(write6(&s, 0x0101U, 1U, 5U) == 8U);
    assert(g.event_sequence > 1U && g.last_command_sequence == 11U);
    assert(write6(&s, 0x0104U, 2U, 6U) == 5U);
    assert(write6(&s, 0x0200U, 1U, 6U) == 5U);
    ModbusSlave_Tick(&s, 5006U);
    assert(!s.connected);
    ModbusSlave_Init(&s, 2U, &p, NULL);
    assert(s.node_id == 2U);
    assert(write6(&s, 0x0101U, 1U, 0U) == 5U);
    HybridParking_Init(&p, false);
    assert(write6(&s, 0x0100U, 1U, 1U) == 8U);
    assert(write6(&s, 0x0102U, 0x000fU, 1U) == 8U);
    assert(write6(&s, 0x0103U, 0x000fU, 1U) == 8U);
    assert(HybridParking_OccupiedMask(&p) == 0x0fU);
    ModbusSlave_Tick(&s, 5002U);
    assert(HybridParking_KnownMask(&p) == 0U);
}
int main(void)
{
    parking_test(); gate_test(); buzzer_test(); modbus_test();
    puts("PASS: hybrid parking, shared gate, buzzer, MODBUS, node isolation");
    return 0;
}
