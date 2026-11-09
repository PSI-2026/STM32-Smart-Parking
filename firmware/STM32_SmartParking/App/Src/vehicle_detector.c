#include "vehicle_detector.h"
#include <stddef.h>

void VehicleDetector_Init(
    VehicleDetector *detector,
    GPIO_TypeDef *port,
    uint16_t pin,
    GPIO_PinState active_state
)
{
    detector->sensor_port = port;
    detector->sensor_pin = pin;
    detector->active_state = active_state;
    detector->detected = false;
    detector->fault_reported = false;
}

void VehicleDetector_Update(VehicleDetector *detector)
{
    GPIO_PinState pin_state = HAL_GPIO_ReadPin(
        detector->sensor_port,
        detector->sensor_pin
    );

    detector->detected = (pin_state == detector->active_state);
}

bool VehicleDetector_IsDetected(const VehicleDetector *detector)
{
    return detector->detected;
}

void VehicleDetector_ReportFault(VehicleDetector *detector)
{
    if (detector == NULL)
    {
        return;
    }

    detector->fault_reported = true;
}

bool VehicleDetector_HasFault(const VehicleDetector *detector)
{
    if (detector == NULL)
    {
        return true;
    }

    return detector->fault_reported;
}
