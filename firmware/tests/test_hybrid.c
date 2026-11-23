#include "hybrid_parking.h"
#include "shared_gate.h"
#include "buzzer.h"
#include "modbus_slave.h"
#include "modbus_rtu_rx.h"
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

static void response_capacity_test(void)
{
    for (size_t capacity = 0U; capacity <= 8U; ++capacity) {
        HybridParking p;
        SharedGate g;
        ModbusSlave s;
        HybridParking_Init(&p, true);
        SharedGate_Init(&g, GATE_SIMULATION);
        ModbusSlave_Init(&s, 1U, &p, &g);
        uint8_t req[8] = {1U, 6U, 1U, 0U, 0U, 10U, 0U, 0U};
        uint8_t guarded[10];
        memset(guarded, 0xa5, sizeof guarded);
        size_t n = ModbusSlave_Process(&s, req, frame(req, 6U),
                                       guarded + 1U, capacity, 1U);
        assert(guarded[0] == 0xa5U && guarded[9] == 0xa5U);
        if (capacity < 8U) {
            assert(n == 0U && s.command_sequence == 0U);
            for (size_t i = 0U; i < sizeof guarded; ++i)
                assert(guarded[i] == 0xa5U);
        } else {
            assert(n == 8U && s.command_sequence == 10U);
            assert(memcmp(guarded + 1U, req, 8U) == 0);
        }
        assert(g.state == GATE_CLOSED);
    }
    /* An undersized acknowledgement must not commit simulated occupancy. */
    HybridParking p;
    SharedGate g;
    ModbusSlave s;
    HybridParking_Init(&p, true);
    SharedGate_Init(&g, GATE_SIMULATION);
    ModbusSlave_Init(&s, 1U, &p, &g);
    s.sim_occupied = 0x0002U;
    uint8_t simulation_req[8] = {1U, 6U, 1U, 2U, 0U, 0x0fU, 0U, 0U};
    for (size_t capacity = 0U; capacity < 8U; ++capacity) {
        uint8_t guarded[10];
        memset(guarded, 0xa5, sizeof guarded);
        assert(ModbusSlave_Process(&s, simulation_req,
            frame(simulation_req, 6U), guarded + 1U, capacity, 1U) == 0U);
        assert(s.sim_occupied == 0x0002U);
        assert(HybridParking_OccupiedMask(&p) == 0U);
        for (size_t i = 0U; i < sizeof guarded; ++i)
            assert(guarded[i] == 0xa5U);
    }
    /* A too-small acknowledgement buffer must not actuate the gate either. */
    HybridParking_Init(&p, true);
    SharedGate_Init(&g, GATE_SIMULATION);
    ModbusSlave_Init(&s, 1U, &p, &g);
    s.command_sequence = 1U;
    uint8_t req[8] = {1U, 6U, 1U, 1U, 0U, DIR_EXIT, 0U, 0U};
    uint8_t tiny[5];
    assert(ModbusSlave_Process(&s, req, frame(req, 6U), tiny, sizeof tiny, 2U) == 0U);
    assert(g.state == GATE_CLOSED && !g.request_seen);
}

static uint32_t receive_frame(ModbusRtuRx *rx, const uint8_t *data,
                               size_t length, uint32_t first_tick)
{
    uint32_t tick = first_tick;
    for (size_t i = 0U; i < length; ++i) {
        ModbusRtuRx_Push(rx, data[i], tick);
        if (i + 1U < length) tick += 100U;
    }
    return tick;
}

static void rtu_framing_test(void)
{
    ModbusRtuRx rx;
    uint8_t output[MODBUS_MAX_ADU];
    uint8_t other[8] = {2U, 3U, 0U, 0U, 0U, 1U, 0U, 0U};
    uint8_t ours[8] = {1U, 3U, 0U, 0U, 0U, 1U, 0U, 0U};
    frame(other, 6U); frame(ours, 6U);
    ModbusRtuRx_Init(&rx, 1000000U);
    uint32_t last = receive_frame(&rx, other, sizeof other, 0U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1749U) == 0U);
    /* Deliberately do not poll between frames: e.g. TX busy or main delayed. */
    last = receive_frame(&rx, ours, sizeof ours, last + 1750U);
    assert(ModbusRtuRx_Pop(&rx, output, 7U, last) == 0U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last) == 8U);
    assert(memcmp(output, other, 8U) == 0);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1749U) == 0U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 8U);
    assert(memcmp(output, ours, 8U) == 0);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 0U);

    /* The exact t1.5 boundary is accepted; only a longer sub-t3.5 gap
     * invalidates the frame. */
    const uint8_t boundary_frame[4] = {1U, 3U, 0U, 0U};
    ModbusRtuRx_Init(&rx, 1000000U);
    for (uint32_t i = 0U; i < sizeof boundary_frame; ++i)
        ModbusRtuRx_Push(&rx, boundary_frame[i], i * 750U);
    last = (uint32_t)(sizeof boundary_frame - 1U) * 750U;
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1749U) == 0U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 4U);
    assert(memcmp(output, boundary_frame, sizeof boundary_frame) == 0);

    /* Empty and undersized inputs are not publishable MODBUS RTU frames. */
    ModbusRtuRx_Init(&rx, 1000000U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, 1750U) == 0U);
    const uint8_t undersized_frame[3] = {1U, 3U, 0U};
    last = receive_frame(&rx, undersized_frame, sizeof undersized_frame, 0U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 0U);

    ModbusRtuRx_Init(&rx, 1000000U);
    last = receive_frame(&rx, other, sizeof other, 0U);
    last = receive_frame(&rx, ours, sizeof ours, last + 1750U);
    ModbusRtuRx_Abort(&rx, last);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 8U);
    assert(memcmp(output, other, 8U) == 0);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 0U);

    /* Incomplete, errored or oversized frames are discarded until idle. */
    ModbusRtuRx_Init(&rx, 1000000U);
    ModbusRtuRx_Push(&rx, 1U, 0U);
    ModbusRtuRx_Push(&rx, 3U, 751U);
    last = receive_frame(&rx, ours, sizeof ours, 851U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 0U);
    last = receive_frame(&rx, ours, sizeof ours, last + 3500U);
    ModbusRtuRx_Abort(&rx, last);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 0U);
    ModbusRtuRx_Init(&rx, 1000000U);
    for (uint32_t i = 0U; i <= MODBUS_MAX_ADU; ++i)
        ModbusRtuRx_Push(&rx, 0U, i * 100U);
    last = receive_frame(&rx, ours, sizeof ours, MODBUS_MAX_ADU * 100U + 1750U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 8U);
    assert(memcmp(output, ours, 8U) == 0);

    ModbusRtuRx_Init(&rx, 1000000U);
    last = receive_frame(&rx, ours, sizeof ours, UINT32_MAX - 500U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1749U) == 0U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 8U);
    ModbusRtuRx_Init(&rx, 25000000U);
    assert(rx.interchar_ticks == 18750U && rx.interframe_ticks == 43750U);
    for (uint32_t i = 0U; i < sizeof ours; ++i)
        ModbusRtuRx_Push(&rx, ours[i], i * 2500U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, 17500U + 43749U) == 0U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, 17500U + 43750U) == 8U);

    /* A maximum-size MODBUS ADU fits exactly; overflow recovery is tested
     * below with one byte beyond this boundary. */
    uint8_t maximum_frame[MODBUS_MAX_ADU];
    for (size_t i = 0U; i < sizeof maximum_frame; ++i)
        maximum_frame[i] = (uint8_t)i;
    ModbusRtuRx_Init(&rx, 1000000U);
    last = receive_frame(&rx, maximum_frame, sizeof maximum_frame, 0U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) ==
           sizeof maximum_frame);
    assert(memcmp(output, maximum_frame, sizeof maximum_frame) == 0);

    /* Queue saturation drops whole frames, never concatenates their bytes. */
    ModbusRtuRx_Init(&rx, 1000000U);
    last = 0U;
    for (uint8_t i = 1U; i <= MODBUS_RTU_QUEUE_DEPTH + 2U; ++i) {
        ours[0] = i;
        last = receive_frame(&rx, ours, sizeof ours, last + 1750U);
    }
    for (uint8_t i = 1U; i <= MODBUS_RTU_QUEUE_DEPTH; ++i) {
        assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last) == 8U);
        assert(output[0] == i);
    }
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 8U);
    assert(output[0] == MODBUS_RTU_QUEUE_DEPTH + 2U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1750U) == 0U);

    /* Destination capacity is checked against the queued frame, not the
     * shorter frame currently being collected. The queued frame must remain
     * available after a rejected pop. */
    ModbusRtuRx_Init(&rx, 1000000U);
    last = receive_frame(&rx, ours, sizeof ours, 0U);
    ModbusRtuRx_Push(&rx, 0xAAU, last + 1750U);
    ModbusRtuRx_Push(&rx, 0xBBU, last + 1850U);
    uint8_t guarded[10];
    memset(guarded, 0xA5, sizeof guarded);
    assert(ModbusRtuRx_Pop(&rx, guarded + 1U, 2U, last + 1850U) == 0U);
    assert(guarded[0] == 0xA5U && guarded[3] == 0xA5U);
    assert(ModbusRtuRx_Pop(&rx, output, sizeof output, last + 1850U) == 8U);
    assert(memcmp(output, ours, 8U) == 0);
}
int main(void)
{
    parking_test(); gate_test(); buzzer_test(); modbus_test();
    response_capacity_test(); rtu_framing_test();
    puts("PASS: hybrid parking, shared gate, buzzer, MODBUS bounds, RTU framing, node isolation");
    return 0;
}
