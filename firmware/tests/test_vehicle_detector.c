#include "vehicle_detector.h"
#include "mock_hal.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    VehicleDetector d = {0};
    MockHAL_Reset();
    MockHAL_SetInput(GPIOE, GPIO_PIN_7, GPIO_PIN_RESET);
    VehicleDetector_Init(&d, GPIOE, GPIO_PIN_7, GPIO_PIN_SET);
    assert(d.sensor_port == GPIOE && d.sensor_pin == GPIO_PIN_7);
    assert(d.active_state == GPIO_PIN_SET && !VehicleDetector_IsDetected(&d));
    assert(!VehicleDetector_HasFault(&d));
    assert(MockHAL_ReadCount(GPIOE, GPIO_PIN_7) == 0);
    VehicleDetector_Update(&d);
    assert(!VehicleDetector_IsDetected(&d));
    MockHAL_SetInput(GPIOE, GPIO_PIN_7, GPIO_PIN_SET);
    VehicleDetector_Update(&d);
    assert(VehicleDetector_IsDetected(&d));
    MockHAL_SetInput(GPIOE, GPIO_PIN_7, GPIO_PIN_RESET);
    VehicleDetector_Update(&d);
    assert(!VehicleDetector_IsDetected(&d));
    assert(MockHAL_ReadCount(GPIOE, GPIO_PIN_7) == 3);

    VehicleDetector_Init(&d, GPIOE, GPIO_PIN_7, GPIO_PIN_RESET);
    assert(!VehicleDetector_IsDetected(&d) && !VehicleDetector_HasFault(&d));
    VehicleDetector_Update(&d);
    assert(VehicleDetector_IsDetected(&d));
    MockHAL_SetInput(GPIOE, GPIO_PIN_7, GPIO_PIN_SET);
    VehicleDetector_Update(&d);
    assert(!VehicleDetector_IsDetected(&d));
    VehicleDetector_ReportFault(&d);
    assert(VehicleDetector_HasFault(&d));
    MockHAL_SetInput(GPIOE, GPIO_PIN_7, GPIO_PIN_RESET);
    VehicleDetector_Update(&d);
    assert(VehicleDetector_IsDetected(&d) && VehicleDetector_HasFault(&d));
    VehicleDetector_ReportFault(NULL);
    assert(VehicleDetector_HasFault(NULL));
    VehicleDetector_Init(&d, GPIOE, GPIO_PIN_7, GPIO_PIN_SET);
    assert(!VehicleDetector_IsDetected(&d) && !VehicleDetector_HasFault(&d));
    puts("PASS: vehicle detector polarity, transitions, initialization, fault latch");
    return 0;
}
