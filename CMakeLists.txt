cmake_minimum_required(VERSION 3.13)
include(pico_sdk_import.cmake)

project(rp2040_rgb_controller C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(rp2040_rgb_controller main.c)

pico_generate_pio_header(rp2040_rgb_controller ${CMAKE_CURRENT_SOURCE_DIR}/ws2812.pio)

target_link_libraries(rp2040_rgb_controller pico_stdlib hardware_pio hardware_pwm)

target_compile_definitions(rp2040_rgb_controller PRIVATE
    CFG_TUD_CDC_RX_BUFSIZE=512
    CFG_TUD_CDC_TX_BUFSIZE=512
    CFG_TUD_CDC_EP_BUFSIZE=512
)

pico_enable_stdio_usb(rp2040_rgb_controller 1)
pico_enable_stdio_uart(rp2040_rgb_controller 0)

pico_add_extra_outputs(rp2040_rgb_controller)
