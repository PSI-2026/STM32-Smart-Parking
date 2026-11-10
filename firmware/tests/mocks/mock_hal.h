#ifndef TEST_MOCK_HAL_H
#define TEST_MOCK_HAL_H
#include "stm32f4xx_hal.h"
void MockHAL_Reset(void);
void MockHAL_SetInput(GPIO_TypeDef *port, uint16_t pin, GPIO_PinState state);
GPIO_PinState MockHAL_GetOutput(GPIO_TypeDef *port, uint16_t pin);
unsigned MockHAL_ReadCount(GPIO_TypeDef *port, uint16_t pin);
unsigned MockHAL_WriteCount(GPIO_TypeDef *port, uint16_t pin);
#endif
