#ifndef MODBUS_RTU_RX_H
#define MODBUS_RTU_RX_H

#include "modbus_slave.h"

#define MODBUS_RTU_QUEUE_DEPTH 4U
/* Fixed high-baud-rate timings from the MODBUS Serial Line Guide v1.02. */
#define MODBUS_RTU_INTERCHAR_US 750U
#define MODBUS_RTU_INTERFRAME_US 1750U

typedef struct {
    uint8_t active[MODBUS_MAX_ADU];
    uint8_t frames[MODBUS_RTU_QUEUE_DEPTH][MODBUS_MAX_ADU];
    uint16_t lengths[MODBUS_RTU_QUEUE_DEPTH];
    uint16_t length;
    uint8_t head;
    uint8_t count;
    uint32_t last_tick;
    uint32_t interchar_ticks;
    uint32_t interframe_ticks;
    bool receiving;
    bool invalid;
} ModbusRtuRx;

/* tick_hz is the frequency of a free-running uint32_t counter. The main
 * consumer must exclude the UART ISR while calling Pop. Supports >19200 baud. */
void ModbusRtuRx_Init(ModbusRtuRx *rx, uint32_t tick_hz);
void ModbusRtuRx_Push(ModbusRtuRx *rx, uint8_t byte, uint32_t tick);
void ModbusRtuRx_Abort(ModbusRtuRx *rx, uint32_t tick);
size_t ModbusRtuRx_Pop(ModbusRtuRx *rx, uint8_t *frame, size_t capacity,
                      uint32_t tick);

#endif
