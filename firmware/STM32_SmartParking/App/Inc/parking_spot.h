#ifndef PARKING_SPOT_H
#define PARKING_SPOT_H

#include "main.h"
#include <stdbool.h>
#include <stdint.h>

/* Represents a single parking spot */
typedef struct
{
    GPIO_TypeDef *sensor_port;
    uint16_t sensor_pin;

    GPIO_TypeDef *green_led_port;
    uint16_t green_led_pin;

    GPIO_TypeDef *red_led_port;
    uint16_t red_led_pin;

    bool occupied;

} ParkingSpot;

/* Read sensor and update LED states */
void ParkingSpot_Update(ParkingSpot *spot);

/* Return the current occupancy state */
bool ParkingSpot_IsOccupied(const ParkingSpot *spot);

#endif /* PARKING_SPOT_H */