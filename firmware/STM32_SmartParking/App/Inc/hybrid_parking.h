#ifndef HYBRID_PARKING_H
#define HYBRID_PARKING_H
#include <stdbool.h>
#include <stdint.h>

#define HYBRID_SPACE_COUNT 4U
#define HYBRID_SIM_TTL_MS 5000U
typedef enum { SPACE_UNKNOWN = 0, SPACE_FREE = 1, SPACE_OCCUPIED = 2 } SpaceState;
typedef enum { SOURCE_HARDWARE = 1, SOURCE_BACKEND = 2 } SpaceSource;
typedef struct {
    SpaceState state[HYBRID_SPACE_COUNT];
    SpaceSource source[HYBRID_SPACE_COUNT];
    uint32_t sim_updated_ms;
    bool sim_valid;
} HybridParking;

void HybridParking_Init(HybridParking *parking, bool has_p01);
void HybridParking_SetPhysical(HybridParking *parking, bool occupied);
bool HybridParking_SetSimulation(HybridParking *parking, uint8_t occupied_mask,
                                 uint8_t known_mask, uint32_t now_ms);
void HybridParking_Tick(HybridParking *parking, uint32_t now_ms);
void HybridParking_InvalidateSimulation(HybridParking *parking);
uint8_t HybridParking_OccupiedMask(const HybridParking *parking);
uint8_t HybridParking_KnownMask(const HybridParking *parking);
uint8_t HybridParking_FreeCount(const HybridParking *parking);
bool HybridParking_CapacityKnown(const HybridParking *parking);
#endif
