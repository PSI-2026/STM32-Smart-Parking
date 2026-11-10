#ifndef TEST_STM32F4XX_HAL_H
#define TEST_STM32F4XX_HAL_H
#include <stdint.h>
typedef struct { unsigned id; } GPIO_TypeDef;
typedef struct TIM_HandleTypeDef TIM_HandleTypeDef;
typedef enum { GPIO_PIN_RESET = 0, GPIO_PIN_SET = 1 } GPIO_PinState;
#define GPIO_PIN_2  ((uint16_t)0x0004U)
#define GPIO_PIN_3  ((uint16_t)0x0008U)
#define GPIO_PIN_4  ((uint16_t)0x0010U)
#define GPIO_PIN_5  ((uint16_t)0x0020U)
#define GPIO_PIN_6  ((uint16_t)0x0040U)
#define GPIO_PIN_7  ((uint16_t)0x0080U)
#define GPIO_PIN_8  ((uint16_t)0x0100U)
#define GPIO_PIN_11 ((uint16_t)0x0800U)
#define GPIO_PIN_12 ((uint16_t)0x1000U)
extern GPIO_TypeDef mock_gpio_c, mock_gpio_e, mock_gpio_f, mock_gpio_g;
#define GPIOC (&mock_gpio_c)
#define GPIOE (&mock_gpio_e)
#define GPIOF (&mock_gpio_f)
#define GPIOG (&mock_gpio_g)
GPIO_PinState HAL_GPIO_ReadPin(GPIO_TypeDef *port, uint16_t pin);
void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint16_t pin, GPIO_PinState state);
#endif
