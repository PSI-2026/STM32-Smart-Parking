#ifndef BUZZER_H
#define BUZZER_H
#include <stdbool.h>
#include <stdint.h>
#include "shared_gate.h"
typedef struct {
    bool enabled;
    bool output;
    uint8_t remaining;
    uint32_t phase_started_ms;
    uint16_t last_event_sequence;
} Buzzer;
void Buzzer_Init(Buzzer *buzzer, bool enabled);
void Buzzer_OnEvent(Buzzer *buzzer, GateEvent event, uint16_t sequence,
                    uint32_t now_ms);
void Buzzer_Tick(Buzzer *buzzer, uint32_t now_ms);
#endif
