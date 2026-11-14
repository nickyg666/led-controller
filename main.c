#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "pico/stdlib.h"
#include "pico/time.h"
#include "pico/bootrom.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "hardware/pwm.h"
#include "ws2812.pio.h"

/* ---------- Configuration ---------- */
#define DEFAULT_DATA_PIN   10
#define DEFAULT_NUM_LEDS   81
#define MAX_LEDS           1024
#define PIO_FREQ_HZ        800000.0f

#define PWM_RED_PIN        11
#define PWM_GREEN_PIN      12
#define PWM_BLUE_PIN       13
#define PWM_WHITE_PIN      14
#define DEFAULT_PWM_FREQ   2000
#define PWM_INVERT         1

#define DEFAULT_SPEED      10     /* animation speed 1-255 */
#define TEMP_MIN_C         30     /* cold = blue */
#define TEMP_MAX_C         90     /* hot  = red */

#define LINE_BUF_SIZE      4096

/* ---------- State ---------- */
static uint32_t pixels[MAX_LEDS];
static uint16_t led_count = DEFAULT_NUM_LEDS;
static uint8_t cur_r = 0, cur_g = 0, cur_b = 0;
static uint8_t anim_mode  = 0;  /* 0=static 1=breath 2=rainbow 3=strobe
   4=candle 5=wave 6=police 7=random 8=storm 9=temp 10=chase 11=fire
   12=sparkle 13=comet 14=theater 15=running 16=meteor 17=bounce
   18=confetti 19=sinelon 20=juggle 21=plasma 22=ripple 23=wipe
   24=fade 25=fireworks 26=snake 27=pulse 28=glitter 29=pride 30=ocean
   31=aurora 32=lava 33=matrix 34=k2000 35=heartbeat 36=colorcycle
   37=twinkle 38=sparklewave 39=stroberainbow 40=gradient 41=demo */
static uint pwm_wrap = 65535;
static uint8_t pwm_r = 0, pwm_g = 0, pwm_b = 0, pwm_w = 0;
static uint8_t global_brightness = 255;

/* effect state */
static uint8_t heat[MAX_LEDS];
static int16_t ball_pos[3] = {0,0,0};
static int8_t ball_dir[3] = {1,1,1};
static uint16_t comet_pos = 0;
static uint16_t meteor_pos = 0;
static uint16_t wipe_pos = 0;
static uint8_t fade_hue = 0;
static uint16_t snake_pos = 0;
static uint8_t anim_speed = DEFAULT_SPEED;
static uint32_t anim_tick = 0;
static int8_t  temp_celsius = -1;  /* -1 = no reading */
static uint32_t rng_state = 2463534242u;  /* xorshift32 seed */
static bool strip_dirty = false;
static uint64_t last_anim_time = 0;

static PIO strip_pio;
static uint strip_sm;
static uint strip_offset;

/* ---------- Helpers ---------- */
static inline uint32_t pack_rgb(uint8_t r, uint8_t g, uint8_t b) {
    /* WS2811 expects GRB, MSB first; low 8 bits are ignored by the PIO
       autopull threshold of 24. */
    return ((uint32_t)g << 24) | ((uint32_t)r << 16) | ((uint32_t)b << 8);
}

static void fill_rgb(uint8_t r, uint8_t g, uint8_t b) {
    uint32_t px = pack_rgb(r, g, b);
    for (uint16_t i = 0; i < led_count; i++) pixels[i] = px;
    strip_dirty = true;
}

static void set_pixel(uint16_t idx, uint8_t r, uint8_t g, uint8_t b) {
    if (idx >= MAX_LEDS) return;
    pixels[idx] = pack_rgb(r, g, b);
    strip_dirty = true;
}

static void hsv_to_rgb(uint16_t h, uint8_t s, uint8_t v,
                       uint8_t *r, uint8_t *g, uint8_t *b) {
    uint8_t region = h / 60;
    uint16_t rem = (uint16_t)(h % 60) * 255 / 59;
    uint8_t p = (v * (255 - s)) / 255;
    uint8_t q = (v * (255 - ((s * (uint16_t)rem) / 255))) / 255;
    uint8_t t = (v * (255 - ((s * (uint16_t)(255 - rem)) / 255))) / 255;
    switch (region) {
        case 0: *r = v; *g = t; *b = p; break;
        case 1: *r = q; *g = v; *b = p; break;
        case 2: *r = p; *g = v; *b = t; break;
        case 3: *r = p; *g = q; *b = v; break;
        case 4: *r = t; *g = p; *b = v; break;
        default: *r = v; *g = p; *b = q; break;
    }
}

/* Simple mix of sines for wave effect; avoids FP */
static uint8_t wave8(uint32_t t, uint32_t freq, uint32_t phase) {
    uint32_t x = (t * freq + phase) & 0xFFFF;
    uint8_t s = (x < 0x8000) ? (uint8_t)((x * 2) >> 8) : (uint8_t)((0xFFFF - x) * 2 >> 8);
    return s;
}

/* sin8: 0-255 input, 0-255 output */
static uint8_t sin8(uint8_t x) {
    /* quarter-wave sine approximation */
    static const uint8_t t[64] = {
        0,6,12,19,25,31,37,44,50,56,62,68,74,80,86,91,
        97,102,107,112,117,122,127,131,136,140,144,148,152,155,159,162,
        165,168,171,173,176,178,180,182,184,185,187,188,189,190,191,192,
        192,193,193,193,193,193,192,192,191,190,189,188,187,185,184,182
    };
    uint8_t i = x & 0x3F;
    uint8_t v = t[i];
    if ((x & 0x40) == 0) {
        /* 0-63 and 192-255: rising/falling handled below */
    }
    if (x < 64) return v;
    if (x < 128) return 255 - t[63 - (x-64)];
    if (x < 192) return 255 - t[x-128];
    return t[63 - (x-192)];
}

/* xorshift32 PRNG — good enough for visual randomness */
static uint8_t rand8(void) {
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return (uint8_t)(rng_state >> 24);
}

/* Map temperature (30–90 °C) to a hue (240=blue → 0=red) */
static void temp_to_rgb(int8_t temp, uint8_t *r, uint8_t *g, uint8_t *b) {
    if (temp < TEMP_MIN_C) temp = TEMP_MIN_C;
    if (temp > TEMP_MAX_C) temp = TEMP_MAX_C;
    uint16_t hue = (uint16_t)(240 - ((temp - TEMP_MIN_C) * 240 / (TEMP_MAX_C - TEMP_MIN_C)));
    hsv_to_rgb(hue, 255, 255, r, g, b);
}

/* Speed 1 → ~400 ms/tick (slow); speed 255 → ~1.6 ms/tick (fast) */
static inline uint32_t speed_to_us(uint8_t speed) {
    return 400000u / (uint32_t)speed;
}

/* ---------- WS2811 strip ---------- */
static void strip_init(void) {
    strip_pio = pio0;
    strip_sm = 0;
    strip_offset = pio_add_program(strip_pio, &ws2812_program);
    ws2812_program_init(strip_pio, strip_sm, strip_offset,
                        DEFAULT_DATA_PIN, PIO_FREQ_HZ, false);
    for (uint16_t i = 0; i < MAX_LEDS; i++) pixels[i] = 0;
}

static void pwm_init_pins(void) {
    uint pins[4] = { PWM_RED_PIN, PWM_GREEN_PIN, PWM_BLUE_PIN, PWM_WHITE_PIN };
    for (int i = 0; i < 4; i++) {
        gpio_set_function(pins[i], GPIO_FUNC_PWM);
        uint slice = pwm_gpio_to_slice_num(pins[i]);
        pwm_set_wrap(slice, pwm_wrap);
        pwm_set_enabled(slice, true);
    }
    /* set freq */
    uint32_t sys_clk = clock_get_hz(clk_sys);
    uint32_t wrap = sys_clk / DEFAULT_PWM_FREQ - 1;
    if (wrap > 65535) wrap = 65535;
    if (wrap < 1) wrap = 1;
    pwm_wrap = wrap;
    for (int i = 0; i < 4; i++) {
        uint slice = pwm_gpio_to_slice_num(pins[i]);
        pwm_set_wrap(slice, wrap);
    }
}

static void apply_white(uint8_t w) {
    pwm_w = w;
    w = (uint8_t)((uint16_t)w * global_brightness / 255);
    uint16_t wl = ((uint16_t)w * pwm_wrap) / 255;
    if (PWM_INVERT) pwm_set_gpio_level(PWM_WHITE_PIN, pwm_wrap - wl);
    else pwm_set_gpio_level(PWM_WHITE_PIN, wl);
}

static void apply_pwm(uint8_t r, uint8_t g, uint8_t b) {
    pwm_r = r; pwm_g = g; pwm_b = b;
    uint8_t br = global_brightness;
    r = (uint8_t)((uint16_t)r * br / 255);
    g = (uint8_t)((uint16_t)g * br / 255);
    b = (uint8_t)((uint16_t)b * br / 255);
    uint16_t rl = ((uint16_t)r * pwm_wrap) / 255;
    uint16_t gl = ((uint16_t)g * pwm_wrap) / 255;
    uint16_t bl = ((uint16_t)b * pwm_wrap) / 255;
    if (PWM_INVERT) {
        pwm_set_gpio_level(PWM_RED_PIN,   pwm_wrap - rl);
        pwm_set_gpio_level(PWM_GREEN_PIN, pwm_wrap - gl);
        pwm_set_gpio_level(PWM_BLUE_PIN,  pwm_wrap - bl);
    } else {
        pwm_set_gpio_level(PWM_RED_PIN,   rl);
        pwm_set_gpio_level(PWM_GREEN_PIN, gl);
        pwm_set_gpio_level(PWM_BLUE_PIN,  bl);
    }
    /* blend white = min(r,g,b) */
    uint8_t w = r < g ? (r < b ? r : b) : (g < b ? g : b);
    apply_white(w);
}

static void strip_show(void) {
    if (led_count == 0) { strip_dirty = false; return; }

    /* Wait for the previous frame to drain, then hold the line low for the
       WS2811 reset period (>50 µs) before starting the next frame. */
    while (!pio_sm_is_tx_fifo_empty(strip_pio, strip_sm)) tight_loop_contents();
    busy_wait_us(100);

    uint8_t br = global_brightness;
    for (uint16_t i = 0; i < led_count; i++) {
        uint32_t p = pixels[i];
        uint8_t gg = ((p >> 24) & 0xFF) * br / 255;
        uint8_t rr = ((p >> 16) & 0xFF) * br / 255;
        uint8_t bb = ((p >> 8) & 0xFF) * br / 255;
        pio_sm_put_blocking(strip_pio, strip_sm, pack_rgb(rr, gg, bb));
    }
    strip_dirty = false;
}

/* ---------- Animations ---------- */
static void update_animation(void) {
    anim_tick++;
    uint8_t r, g, b;

    switch (anim_mode) {
        case 1: {  /* breathing */
            uint8_t phase = anim_tick & 0xFF;
            uint8_t brightness = (phase < 128) ? (phase << 1) : (255 - ((phase - 128) << 1));
            r = (cur_r * brightness) / 255;
            g = (cur_g * brightness) / 255;
            b = (cur_b * brightness) / 255;
            uint32_t px = pack_rgb(r, g, b);
            for (uint16_t i = 0; i < led_count; i++) pixels[i] = px;
            apply_pwm(r, g, b);
            break;
        }
        case 2: {  /* rainbow across the strip */
            uint16_t denom = led_count ? led_count : 1;
            for (uint16_t i = 0; i < led_count; i++) {
                uint16_t hue = (uint16_t)((anim_tick * 2 + (uint32_t)i * 360 / denom) % 360);
                hsv_to_rgb(hue, 255, 255, &r, &g, &b);
                pixels[i] = pack_rgb(r, g, b);
            }
            { uint8_t rr, gg, bb; hsv_to_rgb(anim_tick % 360, 255, 255, &rr, &gg, &bb); apply_pwm(rr, gg, bb); }
            break;
        }
        case 3: {  /* strobe */
            uint8_t on = (anim_tick & 0x1F) < 8;
            uint32_t px = on ? pack_rgb(cur_r, cur_g, cur_b) : 0;
            for (uint16_t i = 0; i < led_count; i++) pixels[i] = px;
            apply_pwm(on ? cur_r : 0, on ? cur_g : 0, on ? cur_b : 0);
            break;
        }
        case 4: {  /* candle */
            uint8_t flicker = 200 + ((anim_tick * 7) ^ (anim_tick >> 3)) % 56;
            r = flicker;
            g = (flicker * 180) / 255;
            b = (flicker * 120) / 255;
            uint32_t px = pack_rgb(r, g, b);
            for (uint16_t i = 0; i < led_count; i++) pixels[i] = px;
            apply_pwm(r, g, b);
            break;
        }
        case 5: {  /* wave */
            for (uint16_t i = 0; i < led_count; i++) {
                r = wave8(anim_tick, 91, i * 91);
                g = wave8(anim_tick, 73, i * 91 + 21845);
                b = wave8(anim_tick, 57, i * 91 + 43691);
                pixels[i] = pack_rgb(r, g, b);
            }
            apply_pwm(wave8(anim_tick, 91, 0), wave8(anim_tick, 73, 21845), wave8(anim_tick, 57, 43691));
            break;
        }
        case 6: {  /* police */
            uint8_t phase = (anim_tick >> 3) & 0xFF;
            uint8_t on = (anim_tick & 0x0F) < 10;
            uint32_t px = (phase < 128) ? (on ? pack_rgb(255, 0, 0) : 0)
                                        : (on ? pack_rgb(0, 0, 255) : 0);
            for (uint16_t i = 0; i < led_count; i++) pixels[i] = px;
            if (phase < 128) apply_pwm(on ? 255 : 0, 0, 0);
            else apply_pwm(0, 0, on ? 255 : 0);
            break;
        }
        case 7: {  /* random */
            if ((anim_tick & 0xFF) == 0) {
                uint8_t rr = rand8(), gg = rand8(), bb = rand8();
                for (uint16_t i = 0; i < led_count; i++) {
                    pixels[i] = pack_rgb(rr, gg, bb);
                }
                apply_pwm(rr, gg, bb);
            }
            break;
        }
        case 8: {  /* storm */
            uint8_t flash = (rand8() < (anim_speed >> 2)) ? 255 : 20;
            r = (flash * 200) / 255;
            g = (flash * 210) / 255;
            b = (flash * 255) / 255;
            uint32_t px = pack_rgb(r, g, b);
            for (uint16_t i = 0; i < led_count; i++) pixels[i] = px;
            apply_pwm(r, g, b);
            break;
        }
        case 9: {  /* temp */
            if (temp_celsius >= 0) {
                temp_to_rgb(temp_celsius, &r, &g, &b);
                uint32_t px = pack_rgb(r, g, b);
                for (uint16_t i = 0; i < led_count; i++) pixels[i] = px;
                apply_pwm(r, g, b);
            }
            break;
        }
        case 10: {  /* chase */
            if (led_count == 0) break;
            for (uint16_t i = 0; i < led_count; i++) {
                uint32_t p = pixels[i];
                uint8_t rr = ((p >> 16) & 0xFF) * 3 / 4;
                uint8_t gg = ((p >> 24) & 0xFF) * 3 / 4;
                uint8_t bb = ((p >> 8) & 0xFF) * 3 / 4;
                pixels[i] = pack_rgb(rr, gg, bb);
            }
            {
                uint8_t br = cur_r ? cur_r : 255;
                uint8_t bg = cur_g ? cur_g : 255;
                uint8_t bb = cur_b ? cur_b : 255;
                if (cur_r == 0 && cur_g == 0 && cur_b == 0) { br = bg = bb = 255; }
                static uint16_t chase_pos = 0;
                pixels[chase_pos] = pack_rgb(br, bg, bb);
                chase_pos = (chase_pos + 1) % led_count;
                apply_pwm(br, bg, bb);
            }
            break;
        }
        case 11: {  /* fire */
            if (led_count == 0) break;
            /* initialize heat */
            if (anim_tick == 1) for (uint16_t i=0;i<led_count;i++) heat[i]=0;
            for (uint16_t i=0;i<led_count;i++) {
                /* cool */
                uint8_t c = heat[i];
                uint8_t cooling = (rand8() % 10) + 2;
                c = (c > cooling) ? c - cooling : 0;
                heat[i] = c;
            }
            for (uint16_t k=led_count-1;k>=2;k--) {
                heat[k] = (heat[k-1] + heat[k-2] + heat[k-2]) / 3;
            }
            /* spark */
            if (rand8() < 120) {
                uint16_t y = rand8() % (led_count/4 + 1);
                uint8_t spark = (rand8() % 60) + 200;
                if (y < led_count) heat[y] = (heat[y] + spark) > 255 ? 255 : heat[y]+spark;
            }
            for (uint16_t i=0;i<led_count;i++) {
                uint8_t h = heat[i];
                uint8_t r=0,g=0,b=0;
                /* map heat to color */
                if (h > 160) { r=255; g = (h-160)*8; b = 0; }
                else if (h > 80) { r = (h-80)*3; g = 0; b = 0; }
                else { r = h; g = 0; b = 0; }
                pixels[i] = pack_rgb(r,g,b);
            }
            apply_pwm(200, 80, 0);
            break;
        }
        case 12: {  /* sparkle */
            if (led_count == 0) break;
            /* dim all slightly */
            for (uint16_t i=0;i<led_count;i++) {
                uint32_t p = pixels[i];
                uint8_t rr = ((p>>16)&0xFF)*9/10;
                uint8_t gg = ((p>>24)&0xFF)*9/10;
                uint8_t bb = ((p>>8)&0xFF)*9/10;
                pixels[i] = pack_rgb(rr,gg,bb);
            }
            if (rand8() < 80) {
                uint16_t idx = rand8() % led_count;
                uint8_t r = rand8(), g = rand8(), b = rand8();
                pixels[idx] = pack_rgb(r,g,b);
                apply_pwm(r,g,b);
            }
            break;
        }
        case 13: {  /* comet */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint32_t p = pixels[i];
                uint8_t rr = ((p>>16)&0xFF)*7/8;
                uint8_t gg = ((p>>24)&0xFF)*7/8;
                uint8_t bb = ((p>>8)&0xFF)*7/8;
                pixels[i] = pack_rgb(rr,gg,bb);
            }
            comet_pos = (comet_pos + 1) % led_count;
            pixels[comet_pos] = pack_rgb(255,255,255);
            apply_pwm(255,255,255);
            break;
        }
        case 14: {  /* theater chase */
            if (led_count == 0) break;
            uint8_t q = anim_tick % 3;
            for (uint16_t i=0;i<led_count;i++) {
                if ((i % 3) == q) pixels[i] = pack_rgb(cur_r?cur_r:255, cur_g?cur_g:0, cur_b?cur_b:0);
                else pixels[i] = 0;
            }
            apply_pwm(cur_r?cur_r:255, cur_g?cur_g:0, cur_b?cur_b:0);
            break;
        }
        case 15: {  /* running lights */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint8_t r = (sin8((i*4 + anim_tick*2) & 255) * (cur_r?cur_r:255)) / 255;
                uint8_t g = (sin8((i*4 + anim_tick*2) & 255) * (cur_g?cur_g:255)) / 255;
                uint8_t b = (sin8((i*4 + anim_tick*2) & 255) * (cur_b?cur_b:255)) / 255;
                pixels[i] = pack_rgb(r,g,b);
            }
            apply_pwm(cur_r?cur_r:255, cur_g?cur_g:255, cur_b?cur_b:255);
            break;
        }
        case 16: {  /* meteor rain */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint32_t p = pixels[i];
                uint8_t rr = ((p>>16)&0xFF)*8/10;
                uint8_t gg = ((p>>24)&0xFF)*8/10;
                uint8_t bb = ((p>>8)&0xFF)*8/10;
                pixels[i] = pack_rgb(rr,gg,bb);
            }
            meteor_pos = (meteor_pos + 1) % led_count;
            for (uint8_t t=0;t<8 && (meteor_pos+t)<led_count;t++) {
                uint8_t v = 255 - t*30;
                pixels[meteor_pos+t] = pack_rgb(v,v,v);
            }
            apply_pwm(255,255,255);
            break;
        }
        case 17: {  /* bounce */
            if (led_count == 0) break;
            /* init */
            if (anim_tick == 1) { ball_pos[0]=0; ball_pos[1]=led_count/3; ball_pos[2]=2*led_count/3; ball_dir[0]=1; ball_dir[1]=1; ball_dir[2]=1; }
            for (uint16_t i=0;i<led_count;i++) pixels[i]=0;
            for (int b=0;b<3;b++) {
                if (ball_pos[b] < led_count) pixels[ball_pos[b]] = pack_rgb(255,0,255);
                ball_pos[b] += ball_dir[b];
                if (ball_pos[b] >= led_count-1) ball_dir[b] = -1;
                if (ball_pos[b] <= 0) ball_dir[b] = 1;
            }
            apply_pwm(255,0,255);
            break;
        }
        case 18: {  /* confetti */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint32_t p = pixels[i];
                uint8_t rr = ((p>>16)&0xFF)*9/10;
                uint8_t gg = ((p>>24)&0xFF)*9/10;
                uint8_t bb = ((p>>8)&0xFF)*9/10;
                pixels[i] = pack_rgb(rr,gg,bb);
            }
            if (rand8() < 60) {
                uint16_t idx = rand8() % led_count;
                pixels[idx] = pack_rgb(rand8(), rand8(), rand8());
            }
            apply_pwm(rand8(), rand8(), rand8());
            break;
        }
        case 19: {  /* sinelon */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint32_t p = pixels[i];
                uint8_t rr = ((p>>16)&0xFF)*9/10;
                uint8_t gg = ((p>>24)&0xFF)*9/10;
                uint8_t bb = ((p>>8)&0xFF)*9/10;
                pixels[i] = pack_rgb(rr,gg,bb);
            }
            {
                uint16_t idx = (sin8(anim_tick*3) * led_count) / 255;
                pixels[idx] = pack_rgb(255,255,255);
                apply_pwm(255,255,255);
            }
            break;
        }
        case 20: {  /* juggle */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) pixels[i]=0;
            for (uint8_t j=0;j<4;j++) {
                uint16_t idx = (sin8(anim_tick*4 + j*64) * (led_count-1)) / 255;
                uint8_t r=0,g=0,b=0;
                switch(j){case 0:r=255;break;case 1:g=255;break;case 2:b=255;break;default:r=255;g=255;b=255;break;}
                if (idx < led_count) pixels[idx] = pack_rgb(r,g,b);
            }
            apply_pwm(255,255,255);
            break;
        }
        case 21: {  /* plasma */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint8_t v1 = sin8((i*8 + anim_tick*2) & 255);
                uint8_t v2 = sin8((i*4 - anim_tick*3) & 255);
                uint8_t v = (v1 + v2) / 2;
                uint8_t r = sin8(v + 0);
                uint8_t g = sin8(v + 85);
                uint8_t b = sin8(v + 170);
                pixels[i] = pack_rgb(r,g,b);
            }
            apply_pwm(128,128,128);
            break;
        }
        case 22: {  /* ripple */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint32_t p = pixels[i];
                uint8_t rr = ((p>>16)&0xFF)*9/10;
                uint8_t gg = ((p>>24)&0xFF)*9/10;
                uint8_t bb = ((p>>8)&0xFF)*9/10;
                pixels[i] = pack_rgb(rr,gg,bb);
            }
            {
                uint16_t center = led_count/2;
                uint16_t r = (anim_tick * 2) % (led_count+20);
                for (int d=-2;d<=2;d++) {
                    int idx = center + r - 10 + d;
                    if (idx >= 0 && idx < led_count) {
                        uint8_t v = 255 - (abs(d)*60);
                        pixels[idx] = pack_rgb(0, v, v);
                    }
                }
            }
            apply_pwm(0,128,128);
            break;
        }
        case 23: {  /* wipe */
            if (led_count == 0) break;
            if (wipe_pos == 0 && anim_tick % 60 == 0) {
                /* new color */
                cur_r = rand8(); cur_g = rand8(); cur_b = rand8();
            }
            if (wipe_pos < led_count) {
                pixels[wipe_pos] = pack_rgb(cur_r,cur_g,cur_b);
                wipe_pos++;
            } else {
                wipe_pos = 0;
            }
            apply_pwm(cur_r,cur_g,cur_b);
            break;
        }
        case 24: {  /* fade */
            if (led_count == 0) break;
            fade_hue = (fade_hue + 1) % 256;
            uint8_t r,g,b;
            hsv_to_rgb((uint16_t)(fade_hue*360/255), 255, 255, &r,&g,&b);
            uint32_t px = pack_rgb(r,g,b);
            for (uint16_t i=0;i<led_count;i++) pixels[i] = px;
            apply_pwm(r,g,b);
            break;
        }
        case 25: {  /* fireworks */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint32_t p = pixels[i];
                uint8_t rr = ((p>>16)&0xFF)*9/10;
                uint8_t gg = ((p>>24)&0xFF)*9/10;
                uint8_t bb = ((p>>8)&0xFF)*9/10;
                pixels[i] = pack_rgb(rr,gg,bb);
            }
            if (rand8() < 40) {
                uint16_t idx = rand8() % led_count;
                uint8_t r = rand8(), g = rand8(), b = rand8();
                pixels[idx] = pack_rgb(r,g,b);
                /* burst */
                for (int d=1;d<=4;d++) {
                    if (idx+d < led_count) pixels[idx+d] = pack_rgb(r/ (d+1), g/(d+1), b/(d+1));
                    if (idx>=d) pixels[idx-d] = pack_rgb(r/(d+1), g/(d+1), b/(d+1));
                }
            }
            apply_pwm(rand8(), rand8(), rand8());
            break;
        }
        case 26: {  /* snake */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) pixels[i]=0;
            for (uint8_t s=0;s<5;s++) {
                uint16_t idx = (snake_pos + s) % led_count;
                uint8_t v = 255 - s*40;
                pixels[idx] = pack_rgb(v, v/2, 0);
            }
            snake_pos = (snake_pos + 1) % led_count;
            apply_pwm(255,128,0);
            break;
        }
        case 27: {  /* pulse */
            if (led_count == 0) break;
            uint8_t phase = anim_tick & 0xFF;
            uint8_t brightness = (phase < 128) ? (phase*2) : (255 - (phase-128)*2);
            uint8_t r = (cur_r * brightness) / 255;
            uint8_t g = (cur_g * brightness) / 255;
            uint8_t b = (cur_b * brightness) / 255;
            uint32_t px = pack_rgb(r,g,b);
            for (uint16_t i=0;i<led_count;i++) pixels[i] = px;
            apply_pwm(r,g,b);
            break;
        }
        case 28: {  /* glitter */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) pixels[i] = pack_rgb(cur_r,cur_g,cur_b);
            if (rand8() < 50) {
                uint16_t idx = rand8() % led_count;
                pixels[idx] = pack_rgb(255,255,255);
            }
            apply_pwm(cur_r,cur_g,cur_b);
            break;
        }
        case 29: {  /* pride */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint8_t r,g,b;
                hsv_to_rgb((uint16_t)((i*360/led_count + anim_tick*2) % 360), 255, 255, &r,&g,&b);
                /* add noise */
                uint8_t n = rand8() % 40;
                r = r > n ? r-n : 0;
                pixels[i] = pack_rgb(r,g,b);
            }
            apply_pwm(128,128,128);
            break;
        }
        case 30: {  /* ocean */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint8_t v1 = sin8((i*3 + anim_tick) & 255);
                uint8_t v2 = sin8((i*5 - anim_tick*2) & 255);
                uint8_t v = (v1 + v2) / 2;
                uint8_t r = 0;
                uint8_t g = v / 2;
                uint8_t b = v;
                pixels[i] = pack_rgb(r,g,b);
            }
            apply_pwm(0,64,128);
            break;
        }
        case 31: {  /* aurora */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint8_t v1 = sin8((i*2 + anim_tick) & 255);
                uint8_t v2 = sin8((i*7 - anim_tick*2) & 255);
                uint8_t v = (v1 + v2) / 2;
                uint8_t r = v / 4;
                uint8_t g = v;
                uint8_t b = v / 2 + 40;
                pixels[i] = pack_rgb(r,g,b);
            }
            apply_pwm(0,128,64);
            break;
        }
        case 32: {  /* lava */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint8_t v = sin8((i*4 + anim_tick*2) & 255);
                uint8_t r = v;
                uint8_t g = v / 4;
                uint8_t b = 0;
                pixels[i] = pack_rgb(r,g,b);
            }
            apply_pwm(200,50,0);
            break;
        }
        case 33: {  /* matrix */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint32_t p = pixels[i];
                uint8_t rr = ((p>>16)&0xFF)*9/10;
                uint8_t gg = ((p>>24)&0xFF)*9/10;
                uint8_t bb = ((p>>8)&0xFF)*9/10;
                pixels[i] = pack_rgb(rr,gg,bb);
            }
            if (rand8() < 40) {
                uint16_t idx = rand8() % led_count;
                pixels[idx] = pack_rgb(0,255,0);
            }
            apply_pwm(0,255,0);
            break;
        }
        case 34: {  /* k2000 */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) pixels[i]=0;
            {
                static int16_t kpos = 0;
                static int8_t kdir = 1;
                for (int d=0;d<4;d++) {
                    int idx = kpos - d;
                    if (idx >= 0 && idx < led_count) {
                        uint8_t v = 255 - d*60;
                        pixels[idx] = pack_rgb(v,0,0);
                    }
                }
                kpos += kdir;
                if (kpos >= led_count-1) kdir = -1;
                if (kpos <= 0) kdir = 1;
            }
            apply_pwm(255,0,0);
            break;
        }
        case 35: {  /* heartbeat */
            if (led_count == 0) break;
            {
                uint8_t phase = anim_tick & 0x3F;
                uint8_t brightness;
                if (phase < 8) brightness = phase * 32;
                else if (phase < 16) brightness = 255 - (phase-8)*32;
                else if (phase < 24) brightness = (phase-16)*32;
                else if (phase < 32) brightness = 255 - (phase-24)*32;
                else brightness = 0;
                uint8_t r = (255 * brightness) / 255;
                uint32_t px = pack_rgb(r,0,0);
                for (uint16_t i=0;i<led_count;i++) pixels[i] = px;
                apply_pwm(r,0,0);
            }
            break;
        }
        case 36: {  /* colorcycle */
            if (led_count == 0) break;
            {
                uint8_t hue = (anim_tick * 2) & 0xFF;
                uint8_t r,g,b;
                hsv_to_rgb((uint16_t)(hue*360/255), 255, 255, &r,&g,&b);
                uint32_t px = pack_rgb(r,g,b);
                for (uint16_t i=0;i<led_count;i++) pixels[i] = px;
                apply_pwm(r,g,b);
            }
            break;
        }
        case 37: {  /* twinkle */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint32_t p = pixels[i];
                uint8_t rr = ((p>>16)&0xFF)*95/100;
                uint8_t gg = ((p>>24)&0xFF)*95/100;
                uint8_t bb = ((p>>8)&0xFF)*95/100;
                pixels[i] = pack_rgb(rr,gg,bb);
            }
            if (rand8() < 50) {
                uint16_t idx = rand8() % led_count;
                pixels[idx] = pack_rgb(255,255,255);
            }
            apply_pwm(128,128,128);
            break;
        }
        case 38: {  /* sparklewave */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint8_t v = sin8((i*4 + anim_tick*2) & 255);
                uint8_t r = (v * (cur_r?cur_r:255)) / 255;
                uint8_t g = (v * (cur_g?cur_g:128)) / 255;
                uint8_t b = (v * (cur_b?cur_b:0)) / 255;
                pixels[i] = pack_rgb(r,g,b);
                if (rand8() < 10) pixels[i] = pack_rgb(255,255,255);
            }
            apply_pwm(cur_r?cur_r:255, cur_g?cur_g:128, cur_b?cur_b:0);
            break;
        }
        case 39: {  /* stroberainbow */
            if (led_count == 0) break;
            if ((anim_tick & 0x0F) < 4) {
                uint8_t hue = (anim_tick * 4) & 0xFF;
                uint8_t r,g,b;
                hsv_to_rgb((uint16_t)(hue*360/255), 255, 255, &r,&g,&b);
                uint32_t px = pack_rgb(r,g,b);
                for (uint16_t i=0;i<led_count;i++) pixels[i] = px;
                apply_pwm(r,g,b);
            } else {
                for (uint16_t i=0;i<led_count;i++) pixels[i] = 0;
                apply_pwm(0,0,0);
            }
            break;
        }
        case 40: {  /* gradient */
            if (led_count == 0) break;
            for (uint16_t i=0;i<led_count;i++) {
                uint16_t hue = (uint16_t)((anim_tick + i*360/led_count) % 360);
                uint8_t r,g,b;
                hsv_to_rgb(hue, 255, 255, &r,&g,&b);
                pixels[i] = pack_rgb(r,g,b);
            }
            apply_pwm(128,128,128);
            break;
        }
        case 41: {  /* demo */
            if (led_count == 0) break;
            {
                uint8_t phase = (anim_tick / 60) % 6;
                if (phase == 0) { /* rainbow */
                    for (uint16_t i=0;i<led_count;i++) {
                        uint16_t hue = (uint16_t)((anim_tick*2 + i*360/led_count) % 360);
                        uint8_t r,g,b; hsv_to_rgb(hue,255,255,&r,&g,&b);
                        pixels[i]=pack_rgb(r,g,b);
                    }
                    apply_pwm(255,0,0);
                } else if (phase == 1) { /* chase */
                    for (uint16_t i=0;i<led_count;i++) pixels[i]=0;
                    uint16_t pos = anim_tick % led_count;
                    pixels[pos] = pack_rgb(255,255,255);
                    apply_pwm(255,255,255);
                } else if (phase == 2) { /* fire-ish */
                    for (uint16_t i=0;i<led_count;i++) {
                        uint8_t v = (i*7 + anim_tick*3) & 255;
                        pixels[i] = pack_rgb(v, v/4, 0);
                    }
                    apply_pwm(200,50,0);
                } else if (phase == 3) { /* sparkle */
                    for (uint16_t i=0;i<led_count;i++) pixels[i]=pack_rgb(cur_r,cur_g,cur_b);
                    if (rand8() < 80) pixels[rand8()%led_count]=pack_rgb(255,255,255);
                    apply_pwm(cur_r,cur_g,cur_b);
                } else if (phase == 4) { /* theater */
                    uint8_t q = anim_tick % 3;
                    for (uint16_t i=0;i<led_count;i++) {
                        if ((i%3)==q) pixels[i]=pack_rgb(0,0,255);
                        else pixels[i]=0;
                    }
                    apply_pwm(0,0,255);
                } else { /* fade */
                    uint8_t hue = (anim_tick) & 0xFF;
                    uint8_t r,g,b; hsv_to_rgb((uint16_t)(hue*360/255),255,255,&r,&g,&b);
                    uint32_t px = pack_rgb(r,g,b);
                    for (uint16_t i=0;i<led_count;i++) pixels[i]=px;
                    apply_pwm(r,g,b);
                }
            }
            break;
        }
        default:
            return;
    }
    strip_dirty = true;
}

/* ---------- Input processing ---------- */
typedef enum { ST_TEXT, ST_ADA_HDR, ST_ADA_DATA } input_state_t;

static input_state_t input_state = ST_TEXT;
static char line_buf[LINE_BUF_SIZE];
static int line_idx = 0;
static uint8_t win[3] = {0, 0, 0};

static uint8_t ada_hdr[6];
static uint8_t ada_hdr_len = 0;
static uint16_t ada_led_count = 0;
static uint32_t ada_byte_idx = 0;
static uint32_t ada_byte_target = 0;
static uint16_t ada_pixel_idx = 0;
static uint8_t ada_comp = 0;
static uint8_t ada_r = 0, ada_g = 0, ada_b = 0;

static void process_command(const char *cmd);

static void process_byte(uint8_t c) {
    if (input_state == ST_TEXT) {
        win[0] = win[1]; win[1] = win[2]; win[2] = c;
        if (win[0] == 'A' && win[1] == 'd' && win[2] == 'a') {
            input_state = ST_ADA_HDR;
            ada_hdr_len = 3;
            ada_hdr[0] = 'A'; ada_hdr[1] = 'd'; ada_hdr[2] = 'a';
            line_idx = 0;
            return;
        }
        if (c == '\n') {
            if (line_idx > 0) {
                line_buf[line_idx] = '\0';
                process_command(line_buf);
            }
            line_idx = 0;
        } else if (c == '\r') {
            /* ignore, handled by \n */
        } else if (c >= 32 && c < 127 && line_idx < LINE_BUF_SIZE - 1) {
            line_buf[line_idx++] = (char)c;
        }
    } else if (input_state == ST_ADA_HDR) {
        ada_hdr[ada_hdr_len++] = c;
        if (ada_hdr_len == 6) {
            uint8_t hi = ada_hdr[3], lo = ada_hdr[4], chk = ada_hdr[5];
            if ((uint8_t)(hi ^ lo ^ 0x55) == chk) {
                ada_led_count = ((uint16_t)hi << 8) | lo;
                ada_byte_idx = 0;
                ada_byte_target = (uint32_t)ada_led_count * 3;
                ada_pixel_idx = 0;
                ada_comp = 0;
                if (ada_byte_target > 0) {
                    input_state = ST_ADA_DATA;
                } else {
                    input_state = ST_TEXT;
                    strip_dirty = true;
                }
            } else {
                input_state = ST_TEXT;
            }
            win[0] = win[1] = win[2] = 0;
        }
    } else if (input_state == ST_ADA_DATA) {
        switch (ada_comp) {
            case 0: ada_r = c; ada_comp = 1; break;
            case 1: ada_g = c; ada_comp = 2; break;
            default:
                ada_b = c;
                ada_comp = 0;
                if (ada_pixel_idx < MAX_LEDS) {
                    pixels[ada_pixel_idx] = pack_rgb(ada_r, ada_g, ada_b);
                }
                ada_pixel_idx++;
                break;
        }
        ada_byte_idx++;
        if (ada_byte_idx >= ada_byte_target) {
            input_state = ST_TEXT;
            win[0] = win[1] = win[2] = 0;
            strip_dirty = true;
        }
    }
}

/* ---------- Command parser ---------- */
static void process_command(const char *cmd) {
    while (*cmd && isspace((unsigned char)*cmd)) cmd++;

    if (strncmp(cmd, "RGB", 3) == 0 && isspace((unsigned char)cmd[3])) {
        int r, g, b, w = -1;
        int n = sscanf(cmd + 3, "%d %d %d %d", &r, &g, &b, &w);
        if (n >= 3 &&
            r >= 0 && r <= 255 && g >= 0 && g <= 255 && b >= 0 && b <= 255 &&
            (n == 3 || (w >= 0 && w <= 255))) {
            anim_mode = 0;
            cur_r = (uint8_t)r; cur_g = (uint8_t)g; cur_b = (uint8_t)b;
            fill_rgb((uint8_t)r, (uint8_t)g, (uint8_t)b);
            apply_pwm((uint8_t)r, (uint8_t)g, (uint8_t)b);
            if (n == 4) apply_white((uint8_t)w);
            printf("OK RGB=%d,%d,%d W=%d\n", r, g, b, (n == 4 ? w : (r<g?(r<b?r:b):(g<b?g:b))));
        } else {
            printf("ERR: RGB needs 3 or 4 values 0-255\n");
        }
    } else if (cmd[0] == '#') {
        unsigned int r, g, b;
        if (strlen(cmd) >= 7 && sscanf(cmd, "#%02x%02x%02x", &r, &g, &b) == 3) {
            anim_mode = 0;
            cur_r = (uint8_t)r; cur_g = (uint8_t)g; cur_b = (uint8_t)b;
            fill_rgb((uint8_t)r, (uint8_t)g, (uint8_t)b);
            apply_pwm((uint8_t)r, (uint8_t)g, (uint8_t)b);
            printf("OK #%02X%02X%02X\n", r, g, b);
        } else {
            printf("ERR: hex format #RRGGBB\n");
        }
    } else if (strncmp(cmd, "HSV", 3) == 0 && isspace((unsigned char)cmd[3])) {
        int h, s, v;
        if (sscanf(cmd + 3, "%d %d %d", &h, &s, &v) == 3 &&
            h >= 0 && h <= 360 && s >= 0 && s <= 255 && v >= 0 && v <= 255) {
            uint8_t r, g, b;
            hsv_to_rgb((uint16_t)h % 360, (uint8_t)s, (uint8_t)v, &r, &g, &b);
            anim_mode = 0;
            cur_r = r; cur_g = g; cur_b = b;
            fill_rgb(r, g, b);
            apply_pwm(r, g, b);
            printf("OK HSV->RGB=%d,%d,%d\n", r, g, b);
        } else {
            printf("ERR: HSV needs 3 values: h 0-360 s 0-255 v 0-255\n");
        }
    } else if (strncmp(cmd, "PIX", 3) == 0 && isspace((unsigned char)cmd[3])) {
        int i, r, g, b;
        if (sscanf(cmd + 3, "%d %d %d %d", &i, &r, &g, &b) == 4 &&
            i >= 0 && i < MAX_LEDS &&
            r >= 0 && r <= 255 && g >= 0 && g <= 255 && b >= 0 && b <= 255) {
            set_pixel((uint16_t)i, (uint8_t)r, (uint8_t)g, (uint8_t)b);
            printf("OK PIX %d=%d,%d,%d\n", i, r, g, b);
        } else {
            printf("ERR: PIX <i> <r> <g> <b> (i 0-%d, rgb 0-255)\n", MAX_LEDS - 1);
        }
    } else if (strncmp(cmd, "FILL", 4) == 0 && isspace((unsigned char)cmd[4])) {
        int r, g, b;
        if (sscanf(cmd + 4, "%d %d %d", &r, &g, &b) == 3 &&
            r >= 0 && r <= 255 && g >= 0 && g <= 255 && b >= 0 && b <= 255) {
            anim_mode = 0;
            cur_r = (uint8_t)r; cur_g = (uint8_t)g; cur_b = (uint8_t)b;
            fill_rgb((uint8_t)r, (uint8_t)g, (uint8_t)b);
            apply_pwm((uint8_t)r, (uint8_t)g, (uint8_t)b);
            printf("OK FILL=%d,%d,%d\n", r, g, b);
        } else {
            printf("ERR: FILL needs 3 values 0-255\n");
        }
      } else if (strncmp(cmd, "PWMRGB", 6) == 0 && isspace((unsigned char)cmd[6])) {
        int r, g, b, w = -1;
        int n = sscanf(cmd + 6, "%d %d %d %d", &r, &g, &b, &w);
        if (n >= 3 && r >= 0 && r <= 255 && g >= 0 && g <= 255 && b >= 0 && b <= 255 &&
            (n == 3 || (w >= 0 && w <= 255))) {
            apply_pwm((uint8_t)r, (uint8_t)g, (uint8_t)b);
            if (n == 4) apply_white((uint8_t)w);
            printf("OK PWMRGB=%d,%d,%d W=%d\n", r, g, b, (n == 4 ? w : (r<g?(r<b?r:b):(g<b?g:b))));
        } else {
            printf("ERR: PWMRGB needs 3 or 4 values 0-255\n");
        }
     } else if (strncmp(cmd, "WHITE", 5) == 0 && isspace((unsigned char)cmd[5])) {
        int w;
        if (sscanf(cmd + 5, "%d", &w) == 1 && w >= 0 && w <= 255) {
            apply_white((uint8_t)w);
            printf("OK WHITE=%d\n", w);
        } else {
            printf("ERR: WHITE 0-255\n");
        }
    } else if (strncmp(cmd, "BRIGHTNESS", 10) == 0 && isspace((unsigned char)cmd[10])) {
        int b;
        if (sscanf(cmd + 10, "%d", &b) == 1 && b >= 0 && b <= 255) {
            global_brightness = (uint8_t)b;
            strip_dirty = true;
            /* re-apply PWM with current colors */
            apply_pwm(pwm_r, pwm_g, pwm_b);
            apply_white(pwm_w);
            printf("OK BRIGHTNESS=%d\n", b);
        } else {
            printf("ERR: BRIGHTNESS 0-255\n");
        }
    } else if (strncmp(cmd, "LEN", 3) == 0 && isspace((unsigned char)cmd[3])) {
        int n;
        if (sscanf(cmd + 3, "%d", &n) == 1 && n >= 0 && n <= MAX_LEDS) {
            led_count = (uint16_t)n;
            strip_dirty = true;
            printf("OK len=%d\n", n);
        } else {
            printf("ERR: LEN 0-%d\n", MAX_LEDS);
        }
    } else if (strncmp(cmd, "FRAME", 5) == 0 && isspace((unsigned char)cmd[5])) {
        const char *p = cmd + 5;
        uint16_t idx = 0;
        while (*p && idx < MAX_LEDS) {
            while (*p && (isspace((unsigned char)*p) || *p == ',' || *p == '#')) p++;
            if (!isxdigit((unsigned char)*p)) break;
            unsigned int v = 0;
            int n = 0;
            while (n < 6 && isxdigit((unsigned char)*p)) {
                char ch = *p++;
                unsigned int d = (ch >= '0' && ch <= '9') ? (unsigned int)(ch - '0') :
                                 (ch >= 'a' && ch <= 'f') ? (unsigned int)(ch - 'a' + 10) :
                                 (unsigned int)(ch - 'A' + 10);
                v = (v << 4) | d;
                n++;
            }
            if (n != 6) break;
            pixels[idx++] = pack_rgb((uint8_t)((v >> 16) & 0xFF),
                                     (uint8_t)((v >> 8) & 0xFF),
                                     (uint8_t)(v & 0xFF));
        }
        if (idx > 0) led_count = idx;
        strip_dirty = true;
        printf("OK frame=%d\n", idx);
    } else if (strcmp(cmd, "SHOW") == 0) {
        strip_dirty = true;
        printf("OK show\n");
    } else if (strcmp(cmd, "CLEAR") == 0) {
        for (uint16_t i = 0; i < led_count; i++) pixels[i] = 0;
        strip_dirty = true;
        printf("OK clear\n");
    } else if (strncmp(cmd, "ANIM", 4) == 0 && isspace((unsigned char)cmd[4])) {
        const char *mode = cmd + 4;
        while (*mode && isspace((unsigned char)*mode)) mode++;
        int m = -1;
        if (strcmp(mode, "static") == 0) m = 0;
        else if (strcmp(mode, "breath") == 0) m = 1;
        else if (strcmp(mode, "rainbow") == 0) m = 2;
        else if (strcmp(mode, "strobe") == 0) m = 3;
        else if (strcmp(mode, "candle") == 0) m = 4;
        else if (strcmp(mode, "wave") == 0) m = 5;
        else if (strcmp(mode, "police") == 0) m = 6;
        else if (strcmp(mode, "random") == 0) m = 7;
        else if (strcmp(mode, "storm") == 0) m = 8;
        else if (strcmp(mode, "temp") == 0) m = 9;
        else if (strcmp(mode, "chase") == 0) m = 10;
        else if (strcmp(mode, "fire") == 0) m = 11;
        else if (strcmp(mode, "sparkle") == 0) m = 12;
        else if (strcmp(mode, "comet") == 0) m = 13;
        else if (strcmp(mode, "theater") == 0) m = 14;
        else if (strcmp(mode, "running") == 0) m = 15;
        else if (strcmp(mode, "meteor") == 0) m = 16;
        else if (strcmp(mode, "bounce") == 0) m = 17;
        else if (strcmp(mode, "confetti") == 0) m = 18;
        else if (strcmp(mode, "sinelon") == 0) m = 19;
        else if (strcmp(mode, "juggle") == 0) m = 20;
        else if (strcmp(mode, "plasma") == 0) m = 21;
        else if (strcmp(mode, "ripple") == 0) m = 22;
        else if (strcmp(mode, "wipe") == 0) m = 23;
        else if (strcmp(mode, "fade") == 0) m = 24;
        else if (strcmp(mode, "fireworks") == 0) m = 25;
        else if (strcmp(mode, "snake") == 0) m = 26;
        else if (strcmp(mode, "pulse") == 0) m = 27;
        else if (strcmp(mode, "glitter") == 0) m = 28;
        else if (strcmp(mode, "pride") == 0) m = 29;
        else if (strcmp(mode, "ocean") == 0) m = 30;
        else if (strcmp(mode, "aurora") == 0) m = 31;
        else if (strcmp(mode, "lava") == 0) m = 32;
        else if (strcmp(mode, "matrix") == 0) m = 33;
        else if (strcmp(mode, "k2000") == 0) m = 34;
        else if (strcmp(mode, "heartbeat") == 0) m = 35;
        else if (strcmp(mode, "colorcycle") == 0) m = 36;
        else if (strcmp(mode, "twinkle") == 0) m = 37;
        else if (strcmp(mode, "sparklewave") == 0) m = 38;
        else if (strcmp(mode, "stroberainbow") == 0) m = 39;
        else if (strcmp(mode, "gradient") == 0) m = 40;
        else if (strcmp(mode, "demo") == 0) m = 41;
        if (m >= 0) {
            anim_mode = (uint8_t)m;
            anim_tick = 0;
            last_anim_time = time_us_64();
            if (m == 0) fill_rgb(cur_r, cur_g, cur_b);
            printf("OK anim=%s\n", mode);
        } else {
            printf("ERR: anim modes: ... (see HELP)\n");
        }
    } else if (strncmp(cmd, "SPEED", 5) == 0 && isspace((unsigned char)cmd[5])) {
        int spd;
        if (sscanf(cmd + 5, "%d", &spd) == 1 && spd >= 1 && spd <= 255) {
            anim_speed = (uint8_t)spd;
            printf("OK speed=%d\n", spd);
        } else {
            printf("ERR: SPEED 1-255\n");
        }
    } else if (strncmp(cmd, "TEMP", 4) == 0 && isspace((unsigned char)cmd[4])) {
        int t;
        if (sscanf(cmd + 4, "%d", &t) == 1 && t >= -40 && t <= 125) {
            temp_celsius = (int8_t)t;
            anim_mode = 9;
            uint8_t r, g, b;
            temp_to_rgb(temp_celsius, &r, &g, &b);
            cur_r = r; cur_g = g; cur_b = b;
            fill_rgb(r, g, b);
            printf("OK temp=%dC RGB=%d,%d,%d\n", temp_celsius, r, g, b);
        } else {
            printf("ERR: TEMP needs int -40..125 (Celsius)\n");
        }
    } else if (strcmp(cmd, "RANDOM") == 0) {
        uint8_t r = rand8(), g = rand8(), b = rand8();
        cur_r = r; cur_g = g; cur_b = b;
        anim_mode = 0;
        fill_rgb(r, g, b);
        printf("OK random=%d,%d,%d\n", r, g, b);
    } else if (strcmp(cmd, "STATE") == 0) {
        printf("STATE leds=%d anim=%d speed=%d rgb=%d,%d,%d",
               led_count, anim_mode, anim_speed, cur_r, cur_g, cur_b);
        if (temp_celsius >= 0) printf(" temp=%dC", temp_celsius);
        printf("\n");
    } else if (strcmp(cmd, "OFF") == 0) {
        anim_mode = 0;
        for (uint16_t i = 0; i < led_count; i++) pixels[i] = 0;
        strip_dirty = true;
        printf("OK off\n");
    } else if (strcmp(cmd, "PING") == 0) {
        printf("PONG\n");
    } else if (strcmp(cmd, "BOOT") == 0) {
        printf("OK rebooting to BOOTSEL\n");
        fflush(stdout);
        sleep_ms(50);
        reset_usb_boot(0, 0);
    } else if (strcmp(cmd, "HELP") == 0) {
        printf("HELP Commands:\n");
        printf("  RGB <r> <g> <b> [w]  Fill WS2811 + PWM (optional white)\n");
        printf("  PWMRGB <r> <g> <b> [w]  PWM strip only (optional white)\n");
        printf("  WHITE <w>            Set white LED (pin 14) 0-255\n");
        printf("  BRIGHTNESS <0-255>   Global brightness (dims effects too)\n");
        printf("  #RRGGBB              Fill all LEDs (hex)\n");
        printf("  HSV <h> <s> <v>      Fill all LEDs (h 0-360 s/v 0-255)\n");
        printf("  PIX <i> <r> <g> <b>  Set LED i (0-%d)\n", MAX_LEDS - 1);
        printf("  FILL <r> <g> <b>     Fill all LEDs\n");
        printf("  LEN <n>              Set LED count (0-%d)\n", MAX_LEDS);
        printf("  FRAME #RRGGBB,...    Set all LEDs from hex colors\n");
        printf("  SHOW                 Latch pixels to strip\n");
        printf("  CLEAR                Turn off all LEDs\n");
        printf("  ANIM static breath rainbow strobe candle wave police random storm temp chase fire sparkle comet theater running meteor bounce confetti sinelon juggle plasma ripple wipe fade fireworks snake pulse glitter pride ocean aurora lava matrix k2000 heartbeat colorcycle twinkle sparklewave stroberainbow gradient demo\n");
        printf("  SPEED <1-255>        Anim speed\n");
        printf("  TEMP <celsius>       Set temp (-40..125); auto-switches to anim=temp\n");
        printf("  RANDOM               Random color\n");
        printf("  STATE                Current values\n");
        printf("  OFF                  Turn off\n");
        printf("  PING                 Heartbeat\n");
        printf("  BOOT                 Reboot to BOOTSEL\n");
    } else if (cmd[0]) {
        printf("ERR: unknown. Try HELP\n");
    }
}

int main() {
    stdio_init_all();
    sleep_ms(800);

    strip_init();
    pwm_init_pins();
    last_anim_time = time_us_64();

    printf("RP2040 WS2811 Addressable Controller ready\n");
    fflush(stdout);
    sleep_ms(200);

    while (true) {
        int c = getchar_timeout_us(200);
        if (c != PICO_ERROR_TIMEOUT) {
            process_byte((uint8_t)c);
            while ((c = getchar_timeout_us(0)) != PICO_ERROR_TIMEOUT) {
                process_byte((uint8_t)c);
            }
        }

        uint64_t now = time_us_64();
        if (anim_mode != 0 && (now - last_anim_time) >= speed_to_us(anim_speed)) {
            last_anim_time = now;
            update_animation();
        }

        if (strip_dirty) {
            strip_show();
        }
    }
    return 0;
}
