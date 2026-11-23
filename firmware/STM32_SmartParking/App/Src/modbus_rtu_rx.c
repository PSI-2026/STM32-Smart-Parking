#include "modbus_rtu_rx.h"
#include <string.h>

void ModbusRtuRx_Init(ModbusRtuRx *rx, uint32_t tick_hz)
{
    *rx = (ModbusRtuRx){0};
    rx->interchar_ticks = (uint32_t)(
        ((uint64_t)tick_hz * MODBUS_RTU_INTERCHAR_US + 999999U) / 1000000U);
    rx->interframe_ticks = (uint32_t)(
        ((uint64_t)tick_hz * MODBUS_RTU_INTERFRAME_US + 999999U) / 1000000U);
}

static void complete(ModbusRtuRx *rx)
{
    if (!rx->invalid && rx->length >= 4U &&
        rx->count < MODBUS_RTU_QUEUE_DEPTH) {
        uint8_t tail = (uint8_t)((rx->head + rx->count) % MODBUS_RTU_QUEUE_DEPTH);
        memcpy(rx->frames[tail], rx->active, rx->length);
        rx->lengths[tail] = rx->length;
        ++rx->count;
    }
    rx->receiving = false;
    rx->invalid = false;
    rx->length = 0U;
}

/* NOLINTNEXTLINE(bugprone-easily-swappable-parameters): byte then counter timestamp. */
void ModbusRtuRx_Push(ModbusRtuRx *rx, uint8_t byte, uint32_t tick)
{
    if (rx->receiving) {
        uint32_t gap = tick - rx->last_tick;
        if (gap >= rx->interframe_ticks) complete(rx);
        else if (gap > rx->interchar_ticks) rx->invalid = true;
    }
    rx->receiving = true;
    rx->last_tick = tick;
    if (rx->length < MODBUS_MAX_ADU && !rx->invalid)
        rx->active[rx->length++] = byte;
    else
        rx->invalid = true;
}

void ModbusRtuRx_Abort(ModbusRtuRx *rx, uint32_t tick)
{
    /* Preserve already completed frames; discard the errored frame until idle. */
    rx->receiving = true;
    rx->invalid = true;
    rx->last_tick = tick;
}

/* NOLINTNEXTLINE(bugprone-easily-swappable-parameters): output bound then timestamp. */
size_t ModbusRtuRx_Pop(ModbusRtuRx *rx, uint8_t *frame, size_t capacity,
                      uint32_t tick)
{
    if (rx->receiving && (uint32_t)(tick - rx->last_tick) >= rx->interframe_ticks)
        complete(rx);
    if (rx->count == 0U || capacity < rx->lengths[rx->head]) return 0U;
    size_t length = rx->lengths[rx->head];
    memcpy(frame, rx->frames[rx->head], length);
    rx->head = (uint8_t)((rx->head + 1U) % MODBUS_RTU_QUEUE_DEPTH);
    --rx->count;
    return length;
}
