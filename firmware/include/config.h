// Build-time settings for the node and receiver firmware.
#pragma once

#define FW_MAJOR 0
#define FW_MINOR 1
#define FW_PATCH 0

// Band pairing key: every board in the rig must be built with the same one.
//   PLATFORMIO_BUILD_FLAGS='-DPAIRING_KEY=\"your-band-key\"' pio run
#ifndef PAIRING_KEY
#define PAIRING_KEY "0.05-dev-key-change-me"
#endif

// ESP-NOW Wi-Fi channel; node and receivers must match.
#ifndef RADIO_CHANNEL
#define RADIO_CHANNEL 1
#endif

// Unit DMX (U183) on the Grove port.
// CoreS3 SE PORT.C: G17 = TX, G18 = RX. AtomS3 Lite Grove: G2 = TX, G1 = RX.
// TODO(hardware): confirm against the U183 schematic before the first flash. The RX/TX labels
// differ between M5Stack pages, and whether the transceiver needs a direction (DE/RE) pin is
// not confirmed. If it does, set DMX_EN_PIN to that GPIO.
#if defined(NODE_BUILD)
#ifndef DMX_TX_PIN
#define DMX_TX_PIN 17
#endif
#ifndef DMX_RX_PIN
#define DMX_RX_PIN 18
#endif
#else
#ifndef DMX_TX_PIN
#define DMX_TX_PIN 2
#endif
#ifndef DMX_RX_PIN
#define DMX_RX_PIN 1
#endif
#endif
#ifndef DMX_EN_PIN
#define DMX_EN_PIN -1
#endif

// AtomS3 Lite RGB LED
#ifndef STATUS_LED_PIN
#define STATUS_LED_PIN 35
#endif

// Timing (ms)
#define DMX_REFRESH_MS 25          // resend the DMX packet at least this often (40 Hz)
#define RADIO_KEEPALIVE_MS 100     // resend unchanged frames over the air this often
#define HEARTBEAT_MS 1000
#define RECEIVER_ONLINE_MS 3500    // 3 missed heartbeats
#define RECEIVER_SILENCE_MS 5000   // receiver outputs black after this long with no data
#define MAX_RECEIVERS 16
