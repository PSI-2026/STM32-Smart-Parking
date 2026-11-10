#include "parking_spot.h"
#include "mock_hal.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    ParkingSpot s = {GPIOE, GPIO_PIN_2, GPIOC, GPIO_PIN_3,
                     GPIOF, GPIO_PIN_6, false};
    MockHAL_Reset();
    MockHAL_SetInput(s.sensor_port, s.sensor_pin, GPIO_PIN_RESET);
    ParkingSpot_Update(&s);
    assert(!ParkingSpot_IsOccupied(&s));
    assert(MockHAL_GetOutput(s.green_led_port, s.green_led_pin) == GPIO_PIN_SET);
    assert(MockHAL_GetOutput(s.red_led_port, s.red_led_pin) == GPIO_PIN_RESET);
    MockHAL_SetInput(s.sensor_port, s.sensor_pin, GPIO_PIN_SET);
    ParkingSpot_Update(&s);
    assert(ParkingSpot_IsOccupied(&s));
    assert(MockHAL_GetOutput(s.green_led_port, s.green_led_pin) == GPIO_PIN_RESET);
    assert(MockHAL_GetOutput(s.red_led_port, s.red_led_pin) == GPIO_PIN_SET);
    MockHAL_SetInput(s.sensor_port, s.sensor_pin, GPIO_PIN_RESET);
    ParkingSpot_Update(&s);
    assert(!ParkingSpot_IsOccupied(&s));
    assert(MockHAL_GetOutput(s.green_led_port, s.green_led_pin) == GPIO_PIN_SET);
    assert(MockHAL_GetOutput(s.red_led_port, s.red_led_pin) == GPIO_PIN_RESET);
    assert(MockHAL_ReadCount(s.sensor_port, s.sensor_pin) == 3);
    assert(MockHAL_WriteCount(s.green_led_port, s.green_led_pin) == 3);
    assert(MockHAL_WriteCount(s.red_led_port, s.red_led_pin) == 3);
    puts("PASS: parking spot GPIO reads, transitions, red/green LEDs");
    return 0;
}
