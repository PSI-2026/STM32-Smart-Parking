#include "hybrid_parking.h"
#include <stddef.h>

void HybridParking_Init(HybridParking *p, bool has_p01)
{
    if (p == NULL) return;
    for (uint8_t i = 0; i < HYBRID_SPACE_COUNT; ++i) {
        p->state[i] = SPACE_UNKNOWN;
        p->source[i] = (i == 0U && has_p01) ? SOURCE_HARDWARE : SOURCE_BACKEND;
    }
    p->sim_updated_ms = 0U;
    p->sim_valid = false;
}

void HybridParking_SetPhysical(HybridParking *p, bool occupied)
{
    if (p != NULL && p->source[0] == SOURCE_HARDWARE)
        p->state[0] = occupied ? SPACE_OCCUPIED : SPACE_FREE;
}

/* NOLINTBEGIN(bugprone-easily-swappable-parameters): API groups masks then tick. */
/* NOLINTBEGIN(bugprone-easily-swappable-parameters): mask inputs precede tick. */
bool HybridParking_SetSimulation(HybridParking *p, uint8_t occupied,
                                 uint8_t known, uint32_t now)
{
    if (p == NULL || (occupied & (uint8_t)~known) != 0U ||
        (occupied & 0xf0U) != 0U || (known & 0xf0U) != 0U ||
        (p->source[0] == SOURCE_HARDWARE && (known & 1U) != 0U)) return false;
    for (uint8_t i = 0; i < HYBRID_SPACE_COUNT; ++i) {
        if (p->source[i] == SOURCE_BACKEND) {
            uint8_t bit = (uint8_t)(1U << i);
            p->state[i] = (known & bit) == 0U ? SPACE_UNKNOWN :
                ((occupied & bit) != 0U ? SPACE_OCCUPIED : SPACE_FREE);
        }
    }
    p->sim_updated_ms = now;
    p->sim_valid = true;
    return true;
}
/* NOLINTEND(bugprone-easily-swappable-parameters) */
/* NOLINTEND(bugprone-easily-swappable-parameters) */

void HybridParking_Tick(HybridParking *p, uint32_t now)
{
    if (p == NULL || !p->sim_valid ||
        (uint32_t)(now - p->sim_updated_ms) < HYBRID_SIM_TTL_MS) return;
    HybridParking_InvalidateSimulation(p);
}

void HybridParking_InvalidateSimulation(HybridParking *p)
{
    if (p == NULL) return;
    for (uint8_t i = 0; i < HYBRID_SPACE_COUNT; ++i)
        if (p->source[i] == SOURCE_BACKEND) p->state[i] = SPACE_UNKNOWN;
    p->sim_valid = false;
}

uint8_t HybridParking_OccupiedMask(const HybridParking *p)
{
    uint8_t mask = 0U;
    if (p != NULL) for (uint8_t i = 0; i < HYBRID_SPACE_COUNT; ++i)
        if (p->state[i] == SPACE_OCCUPIED) mask |= (uint8_t)(1U << i);
    return mask;
}

uint8_t HybridParking_KnownMask(const HybridParking *p)
{
    uint8_t mask = 0U;
    if (p != NULL) for (uint8_t i = 0; i < HYBRID_SPACE_COUNT; ++i)
        if (p->state[i] != SPACE_UNKNOWN) mask |= (uint8_t)(1U << i);
    return mask;
}

uint8_t HybridParking_FreeCount(const HybridParking *p)
{
    uint8_t count = 0U;
    if (p != NULL) for (uint8_t i = 0; i < HYBRID_SPACE_COUNT; ++i)
        if (p->state[i] == SPACE_FREE) ++count;
    return count;
}

bool HybridParking_CapacityKnown(const HybridParking *p)
{
    return HybridParking_KnownMask(p) == 0x0fU;
}
