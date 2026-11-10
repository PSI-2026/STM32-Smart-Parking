#include "mock_hal.h"
#include <assert.h>
#include <string.h>

GPIO_TypeDef mock_gpio_c = {0}, mock_gpio_e = {1};
GPIO_TypeDef mock_gpio_f = {2}, mock_gpio_g = {3};
typedef struct {
    GPIO_PinState input, output;
    unsigned reads, writes;
    int configured;
} Pin;
static Pin pins[4][16];

static Pin *get_pin(GPIO_TypeDef *port, uint16_t pin)
{
    assert(port == GPIOC || port == GPIOE || port == GPIOF || port == GPIOG);
    assert(pin != 0 && (pin & (pin - 1U)) == 0);
    unsigned bit = 0;
    while (pin > 1U) { pin >>= 1; bit++; }
    assert(bit < 16);
    return &pins[port->id][bit];
}

void MockHAL_Reset(void) { memset(pins, 0, sizeof pins); }
void MockHAL_SetInput(GPIO_TypeDef *port, uint16_t pin, GPIO_PinState state)
{
    Pin *p = get_pin(port, pin);
    p->input = state;
    p->configured = 1;
}
GPIO_PinState HAL_GPIO_ReadPin(GPIO_TypeDef *port, uint16_t pin)
{
    Pin *p = get_pin(port, pin);
    assert(p->configured);
    p->reads++;
    return p->input;
}
void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint16_t pin, GPIO_PinState state)
{
    Pin *p = get_pin(port, pin);
    p->output = state;
    p->writes++;
}
GPIO_PinState MockHAL_GetOutput(GPIO_TypeDef *port, uint16_t pin)
{
    Pin *p = get_pin(port, pin);
    assert(p->writes > 0);
    return p->output;
}
unsigned MockHAL_ReadCount(GPIO_TypeDef *port, uint16_t pin)
{ return get_pin(port, pin)->reads; }
unsigned MockHAL_WriteCount(GPIO_TypeDef *port, uint16_t pin)
{ return get_pin(port, pin)->writes; }
