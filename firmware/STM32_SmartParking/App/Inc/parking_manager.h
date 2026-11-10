
#ifndef PARKING_MANAGER_H
#define PARKING_MANAGER_H

#include "parking_spot.h"
#include <stdint.h>

#define PARKING_SPOT_COUNT 4U

typedef struct
{
    ParkingSpot spots[PARKING_SPOT_COUNT];
    uint8_t occupancy_mask;

} ParkingManager;

/* Initialize all parking spots */
void ParkingManager_Init(ParkingManager *manager);

/* Update all parking spots and calculate occupancy */
void ParkingManager_Update(ParkingManager *manager);

/* Return the occupancy bitmask */
uint8_t ParkingManager_GetOccupancyMask(const ParkingManager *manager);

/* Return the number of available parking spots */
uint8_t ParkingManager_GetAvailableCount(const ParkingManager *manager);

#endif /* PARKING_MANAGER_H */
