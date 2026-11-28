// ESP-NOW broadcast link shared by node and receivers. Spec: docs/PROTOCOL.md §4.
#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include "config.h"
#include "proto.h"

namespace radio_link {

static const uint8_t BROADCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

inline uint32_t net_id() {
  static const char key[] = PAIRING_KEY;
  return proto::fnv1a32((const uint8_t*)key, sizeof(key) - 1);
}

inline bool valid_channel(uint8_t ch) { return ch >= proto::MIN_CHANNEL && ch <= proto::MAX_CHANNEL; }

inline void set_channel(uint8_t ch) { esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE); }

inline bool begin(esp_now_recv_cb_t on_recv, uint8_t channel = RADIO_CHANNEL) {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_ps(WIFI_PS_NONE);  // lowest latency
  set_channel(valid_channel(channel) ? channel : RADIO_CHANNEL);
  if (esp_now_init() != ESP_OK) return false;
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST, 6);
  peer.channel = 0;  // 0 = whatever channel the radio is on, so a channel change needs no new peer
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) return false;
  return esp_now_register_recv_cb(on_recv) == ESP_OK;
}

inline bool send(const void* data, size_t len) {
  return esp_now_send(BROADCAST, (const uint8_t*)data, len) == ESP_OK;
}

inline void own_mac(uint8_t* mac) { esp_wifi_get_mac(WIFI_IF_STA, mac); }

}  // namespace radio_link
