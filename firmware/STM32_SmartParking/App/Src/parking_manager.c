
#include "parking_manager.h"

/**
 * @brief Update all parking spots and calculate occupancy.
 */
void ParkingManager_Update(ParkingManager *manager)
{
    uint8_t mask = 0U;

    for (uint8_t i = 0U; i < PARKING_SPOT_COUNT; i++)
    {
        ParkingSpot_Update(&manager->spots[i]);

        if (ParkingSpot_IsOccupied(&manager->spots[i]))
        {
            mask |= (uint8_t)(1U << i);
        }
    }

    manager->occupancy_mask = mask;
}

/**
 * @brief Return the current occupancy bitmask.
 */
uint8_t ParkingManager_GetOccupancyMask(const ParkingManager *manager)
{
    return manager->occupancy_mask;
}

/**
 * @brief Return the number of available parking spots.
 */
uint8_t ParkingManager_GetAvailableCount(const ParkingManager *manager)
{
    uint8_t available = 0U;

    for (uint8_t i = 0U; i < PARKING_SPOT_COUNT; i++)
    {
        if (!ParkingSpot_IsOccupied(&manager->spots[i]))
        {
            available++;
        }
    }

    return available;
}


/**
 * @brief Initialize parking spots with GPIO configuration.
 */
void ParkingManager_Init(ParkingManager *manager)
{
    manager->spots[0] = (ParkingSpot){
        PARK1_SENSOR_GPIO_Port, PARK1_SENSOR_Pin,
        PARK1_GREEN_LED_GPIO_Port, PARK1_GREEN_LED_Pin,
        PARK1_RED_LED_GPIO_Port, PARK1_RED_LED_Pin,
        false
    };

    manager->spots[1] = (ParkingSpot){
        PARK2_SENSOR_GPIO_Port, PARK2_SENSOR_Pin,
        PARK2_GREEN_LED_GPIO_Port, PARK2_GREEN_LED_Pin,
        PARK2_RED_LED_GPIO_Port, PARK2_RED_LED_Pin,
        false
    };

    manager->spots[2] = (ParkingSpot){
        PARK3_SENSOR_GPIO_Port, PARK3_SENSOR_Pin,
        PARK3_GREEN_LED_GPIO_Port, PARK3_GREEN_LED_Pin,
        PARK3_RED_LED_GPIO_Port, PARK3_RED_LED_Pin,
        false
    };

    manager->spots[3] = (ParkingSpot){
        PARK4_SENSOR_GPIO_Port, PARK4_SENSOR_Pin,
        PARK4_GREEN_LED_GPIO_Port, PARK4_GREEN_LED_Pin,
        PARK4_RED_LED_GPIO_Port, PARK4_RED_LED_Pin,
        false
    };

    manager->occupancy_mask = 0U;
}
