// Wired DMX output on the Unit DMX. A changed frame goes out on the very next packet
// (no waiting for the 40 Hz tick); unchanged frames are refreshed every DMX_REFRESH_MS.
#pragma once

#include <Arduino.h>
#include <esp_dmx.h>

#include "config.h"
#include "proto.h"

class DmxOut {
 public:
  bool begin() {
    dmx_config_t cfg = DMX_CONFIG_DEFAULT;
    dmx_personality_t pers[] = {{1, "0.05 relay"}};
    ok_ = dmx_driver_install(port_, &cfg, pers, 1) &&
          dmx_set_pin(port_, DMX_TX_PIN, DMX_RX_PIN, DMX_EN_PIN);
    return ok_;
  }

  void set(const uint8_t* channels /*512*/) {
    memcpy(pkt_ + 1, channels, proto::DMX_CHANNELS);
    dirty_ = true;
    service();  // try to send right now
  }

  void service() {
    if (!ok_) return;
    uint32_t now = millis();
    if (!dirty_ && now - last_ < DMX_REFRESH_MS) return;
    if (!dmx_wait_sent(port_, 0)) return;  // previous packet still on the wire
    dmx_write(port_, pkt_, DMX_PACKET_SIZE);
    dmx_send_num(port_, DMX_PACKET_SIZE);
    dirty_ = false;
    last_ = now;
    packets++;
  }

  const uint8_t* channels() const { return pkt_ + 1; }
  bool ok() const { return ok_; }
  uint32_t packets = 0;

 private:
  dmx_port_t port_ = DMX_NUM_1;
  uint8_t pkt_[DMX_PACKET_SIZE] = {0};  // slot 0 = start code 0
  bool dirty_ = false;
  bool ok_ = false;
  uint32_t last_ = 0;
};
