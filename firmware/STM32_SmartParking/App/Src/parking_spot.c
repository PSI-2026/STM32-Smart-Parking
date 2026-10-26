#include "parking_spot.h"

/**
 * @brief Read the sensor and update parking spot LEDs.
 * @param spot Pointer to the parking spot.
 */
void ParkingSpot_Update(ParkingSpot *spot)
{
    GPIO_PinState sensor_state = HAL_GPIO_ReadPin(
        spot->sensor_port,
        spot->sensor_pin
    );

    spot->occupied = (sensor_state == GPIO_PIN_SET);

    HAL_GPIO_WritePin(
        spot->green_led_port,
        spot->green_led_pin,
        spot->occupied ? GPIO_PIN_RESET : GPIO_PIN_SET
    );

    HAL_GPIO_WritePin(
        spot->red_led_port,
        spot->red_led_pin,
        spot->occupied ? GPIO_PIN_SET : GPIO_PIN_RESET
    );
}

/**
 * @brief Return the current occupancy state.
 * @param spot Pointer to the parking spot.
 * @return true if occupied, false otherwise.
 */
bool ParkingSpot_IsOccupied(const ParkingSpot *spot)
{
    return spot->occupied;
}