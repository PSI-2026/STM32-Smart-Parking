#ifndef MODBUS_SLAVE_H
#define MODBUS_SLAVE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "hybrid_parking.h"
#include "shared_gate.h"
#define MODBUS_MAX_ADU 256U
typedef struct {
    uint8_t node_id;
    HybridParking *parking;
    SharedGate *gate;
    uint16_t command_sequence;
    uint16_t sim_occupied;
    uint16_t sim_known;
    uint16_t sim_last_sequence;
    bool sim_seen;
    uint32_t last_rx_ms;
    bool connected;
    bool simulated_passage;
    uint8_t last_result;
} ModbusSlave;
void ModbusSlave_Init(ModbusSlave *slave, uint8_t node_id,
                      HybridParking *parking, SharedGate *gate);
size_t ModbusSlave_Process(ModbusSlave *slave, const uint8_t *request,
                           size_t length, uint8_t *response,
                           size_t capacity, uint32_t now_ms);
void ModbusSlave_Tick(ModbusSlave *slave, uint32_t now_ms);
uint16_t ModbusSlave_Crc(const uint8_t *data, size_t length);
#endif
