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

inline bool begin(esp_now_recv_cb_t on_recv) {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_ps(WIFI_PS_NONE);  // lowest latency
  esp_wifi_set_channel(RADIO_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) return false;
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST, 6);
  peer.channel = RADIO_CHANNEL;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) return false;
  return esp_now_register_recv_cb(on_recv) == ESP_OK;
}

inline bool send(const void* data, size_t len) {
  return esp_now_send(BROADCAST, (const uint8_t*)data, len) == ESP_OK;
}

inline void own_mac(uint8_t* mac) { esp_wifi_get_mac(WIFI_IF_STA, mac); }

}  // namespace radio_link
