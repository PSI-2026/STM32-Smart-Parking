#include "buzzer.h"
#include <stddef.h>
#define BEEP_MS 100U
#define GAP_MS 100U
void Buzzer_Init(Buzzer *b, bool enabled)
{
    if (b == NULL) return;
    *b = (Buzzer){0};
    b->enabled = enabled;
}
/* NOLINTBEGIN(bugprone-easily-swappable-parameters): event tuple has fixed API. */
void Buzzer_OnEvent(Buzzer *b, GateEvent event, uint16_t sequence, uint32_t now)
{
    if (b == NULL || !b->enabled || sequence == b->last_event_sequence) return;
    uint8_t count = event == EVENT_OPENED ? 1U :
        (event == EVENT_CLOSED ? 2U :
         (event == EVENT_SENSOR_FAULT || event == EVENT_COMM_FAULT ||
          event == EVENT_TIMEOUT_FAULT ? 3U : 0U));
    if (count == 0U) return;
    b->last_event_sequence = sequence;
    b->remaining = count;
    b->output = true;
    b->phase_started_ms = now;
}
/* NOLINTEND(bugprone-easily-swappable-parameters) */
void Buzzer_Tick(Buzzer *b, uint32_t now)
{
    if (b == NULL || !b->enabled || b->remaining == 0U) return;
    uint32_t elapsed = (uint32_t)(now - b->phase_started_ms);
    if (b->output && elapsed >= BEEP_MS) {
        b->output = false;
        b->phase_started_ms = now;
        --b->remaining;
    } else if (!b->output && b->remaining > 0U && elapsed >= GAP_MS) {
        b->output = true;
        b->phase_started_ms = now;
    }
}
