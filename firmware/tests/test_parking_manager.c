#include "parking_manager.h"
#include "mock_hal.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    ParkingManager m;
    GPIO_TypeDef *sensors[] = {PARK1_SENSOR_GPIO_Port, PARK2_SENSOR_GPIO_Port,
                               PARK3_SENSOR_GPIO_Port, PARK4_SENSOR_GPIO_Port};
    uint16_t sensor_pins[] = {PARK1_SENSOR_Pin, PARK2_SENSOR_Pin,
                              PARK3_SENSOR_Pin, PARK4_SENSOR_Pin};
    GPIO_TypeDef *greens[] = {PARK1_GREEN_LED_GPIO_Port, PARK2_GREEN_LED_GPIO_Port,
                              PARK3_GREEN_LED_GPIO_Port, PARK4_GREEN_LED_GPIO_Port};
    uint16_t green_pins[] = {PARK1_GREEN_LED_Pin, PARK2_GREEN_LED_Pin,
                             PARK3_GREEN_LED_Pin, PARK4_GREEN_LED_Pin};
    GPIO_TypeDef *reds[] = {PARK1_RED_LED_GPIO_Port, PARK2_RED_LED_GPIO_Port,
                            PARK3_RED_LED_GPIO_Port, PARK4_RED_LED_GPIO_Port};
    uint16_t red_pins[] = {PARK1_RED_LED_Pin, PARK2_RED_LED_Pin,
                           PARK3_RED_LED_Pin, PARK4_RED_LED_Pin};
    MockHAL_Reset();
    ParkingManager_Init(&m);
    assert(PARKING_SPOT_COUNT == 4 && ParkingManager_GetOccupancyMask(&m) == 0);
    assert(ParkingManager_GetAvailableCount(&m) == 4);
    for (unsigned i = 0; i < PARKING_SPOT_COUNT; ++i) {
        assert(m.spots[i].sensor_port == sensors[i] && m.spots[i].sensor_pin == sensor_pins[i]);
        assert(m.spots[i].green_led_port == greens[i] && m.spots[i].green_led_pin == green_pins[i]);
        assert(m.spots[i].red_led_port == reds[i] && m.spots[i].red_led_pin == red_pins[i]);
        assert(!m.spots[i].occupied);
        MockHAL_SetInput(sensors[i], sensor_pins[i], GPIO_PIN_RESET);
    }
    ParkingManager_Update(&m);
    assert(ParkingManager_GetOccupancyMask(&m) == 0 && ParkingManager_GetAvailableCount(&m) == 4);
    MockHAL_SetInput(sensors[0], sensor_pins[0], GPIO_PIN_SET);
    MockHAL_SetInput(sensors[2], sensor_pins[2], GPIO_PIN_SET);
    ParkingManager_Update(&m);
    assert(ParkingManager_GetOccupancyMask(&m) == 0x05 && ParkingManager_GetAvailableCount(&m) == 2);
    for (unsigned i = 0; i < PARKING_SPOT_COUNT; ++i) {
        bool occupied = (i == 0 || i == 2);
        assert(ParkingSpot_IsOccupied(&m.spots[i]) == occupied);
        assert(MockHAL_GetOutput(greens[i], green_pins[i]) == (occupied ? GPIO_PIN_RESET : GPIO_PIN_SET));
        assert(MockHAL_GetOutput(reds[i], red_pins[i]) == (occupied ? GPIO_PIN_SET : GPIO_PIN_RESET));
        MockHAL_SetInput(sensors[i], sensor_pins[i], GPIO_PIN_SET);
    }
    ParkingManager_Update(&m);
    assert(ParkingManager_GetOccupancyMask(&m) == 0x0f && ParkingManager_GetAvailableCount(&m) == 0);
    MockHAL_SetInput(sensors[0], sensor_pins[0], GPIO_PIN_RESET);
    ParkingManager_Update(&m);
    assert(ParkingManager_GetOccupancyMask(&m) == 0x0e && ParkingManager_GetAvailableCount(&m) == 1);
    for (unsigned i = 0; i < PARKING_SPOT_COUNT; ++i)
        assert(MockHAL_ReadCount(sensors[i], sensor_pins[i]) == 4);
    puts("PASS: four parking spaces, pin mapping, masks, free/partial/full transitions");
    return 0;
}
