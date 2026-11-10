#ifndef VEHICLE_DETECTOR_H
#define VEHICLE_DETECTOR_H

#include "stm32f4xx_hal.h"
#include <stdbool.h>
#include <stdint.h>

typedef struct
{
    GPIO_TypeDef *sensor_port;
    uint16_t sensor_pin;
    GPIO_PinState active_state;
    bool detected;
    bool fault_reported;
} VehicleDetector;

void VehicleDetector_Init(
    VehicleDetector *detector,
    GPIO_TypeDef *port,
    uint16_t pin,
    GPIO_PinState active_state
);

void VehicleDetector_Update(VehicleDetector *detector);

bool VehicleDetector_IsDetected(const VehicleDetector *detector);

void VehicleDetector_ReportFault(VehicleDetector *detector);

bool VehicleDetector_HasFault(const VehicleDetector *detector);

#endif /* VEHICLE_DETECTOR_H */
