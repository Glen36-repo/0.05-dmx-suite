// 0.05 receiver: AtomS3 Lite + Unit DMX.
// ESP-NOW frames from the node -> wired DMX. Sends a heartbeat every second.
// LED: green = receiving, red = no data, blue = receiving but unnamed, white flashing = identify,
// purple blinking = looking for the node on every radio channel.
// Follows the node to another radio channel (SET_CHANNEL); if it hears nothing for SCAN_AFTER_MS it
// listens on each channel in turn until it finds the node again, and remembers that channel.
// Protocol: docs/PROTOCOL.md §4.

#include <Arduino.h>
#include <Preferences.h>

#include "config.h"
#include "dmx_out.h"
#include "proto.h"
#include "radio.h"

using namespace proto;

static DmxOut dmx;
static Preferences prefs;

static uint8_t my_mac[6];
static char my_name[NAME_LEN] = {0};
static uint8_t my_universe = UNIVERSE_NONE;  // unassigned follows universe 0
static uint32_t net_id;
static uint32_t boot_ms;

// shared with the Wi-Fi task
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static uint8_t frame[DMX_CHANNELS];
static volatile bool frame_dirty = false;
static volatile uint32_t last_data_ms = 0;
static volatile bool have_data = false;
static uint8_t node_mac[6];
static volatile int8_t last_rssi = RSSI_NA;
static volatile uint32_t got_seqs = 0, missed_seqs = 0;
static int last_seq = -1;

static volatile bool assign_pending = false;
static uint8_t assign_universe;
static char assign_name[NAME_LEN];
static volatile uint32_t identify_until_ms = 0;

static uint8_t loss_pct = 0;
static uint32_t next_beat_ms = 0;

static uint8_t channel = RADIO_CHANNEL;
static volatile uint8_t move_to = 0;          // SET_CHANNEL heard: move in loop()
static volatile uint32_t last_valid_ms = 0;   // any packet from our rig, on this channel
static uint32_t scan_next_ms = 0;
static bool scanning = false;

static uint8_t active_universe() { return my_universe == UNIVERSE_NONE ? 0 : my_universe; }

// RSSI: ESP-NOW callbacks on this core don't carry it, so read it from the raw 802.11 frame.
static void on_promisc(void* buf, wifi_promiscuous_pkt_type_t type) {
  if (type != WIFI_PKT_MGMT) return;
  const wifi_promiscuous_pkt_t* pkt = (const wifi_promiscuous_pkt_t*)buf;
  const uint8_t* src = pkt->payload + 10;  // addr2
  if (!memcmp(src, node_mac, 6)) last_rssi = pkt->rx_ctrl.rssi;
}

static void on_radio(const uint8_t* mac, const uint8_t* data, int len) {
  if (!radio::valid(data, len, net_id)) return;
  const radio::Header* h = (const radio::Header*)data;
  uint32_t now = millis();
  last_valid_ms = now ? now : 1;
  switch (h->kind) {
    case radio::SET_CHANNEL: {
      if (len != (int)sizeof(radio::SetChannel)) return;
      uint8_t ch = ((const radio::SetChannel*)data)->channel;
      if (radio_link::valid_channel(ch)) move_to = ch;
      return;
    }
    case radio::DMX_CHUNK: {
      if (len < (int)offsetof(radio::DmxChunk, data)) return;
      const radio::DmxChunk* c = (const radio::DmxChunk*)data;
      if (c->universe != active_universe()) return;
      if (c->len > radio::CHUNK_MAX || len < (int)offsetof(radio::DmxChunk, data) + c->len) return;
      if (c->offset + c->len > DMX_CHANNELS) return;
      portENTER_CRITICAL(&mux);
      memcpy(node_mac, mac, 6);
      memcpy(frame + c->offset, c->data, c->len);
      frame_dirty = true;
      last_data_ms = now;
      have_data = true;
      if (c->seq != last_seq) {
        if (last_seq >= 0) {
          uint8_t gap = (uint8_t)(c->seq - last_seq);
          if (gap > 1 && gap < 64) missed_seqs += gap - 1;
        }
        got_seqs++;
        last_seq = c->seq;
      }
      portEXIT_CRITICAL(&mux);
      return;
    }
    case radio::ASSIGN: {
      if (len != (int)sizeof(radio::Assign)) return;
      const radio::Assign* a = (const radio::Assign*)data;
      if (memcmp(a->mac, my_mac, 6)) return;
      portENTER_CRITICAL(&mux);
      assign_universe = a->universe;
      memcpy(assign_name, a->name, NAME_LEN);
      assign_pending = true;  // flash write happens in loop(), not in the Wi-Fi task
      portEXIT_CRITICAL(&mux);
      return;
    }
    case radio::IDENTIFY: {
      if (len != (int)sizeof(radio::Identify)) return;
      const radio::Identify* m = (const radio::Identify*)data;
      if (!memcmp(m->mac, my_mac, 6)) identify_until_ms = now + m->seconds * 1000UL;
      return;
    }
  }
}

static void led(uint8_t r, uint8_t g, uint8_t b) { neopixelWrite(STATUS_LED_PIN, r, g, b); }

static void update_led(uint32_t now, bool receiving) {
  if (scanning) {
    bool on = (now / 300) % 2;
    led(on * 30, 0, on * 40);
  } else if ((int32_t)(identify_until_ms - now) > 0) {
    bool on = (now / 150) % 2;
    led(on * 60, on * 60, on * 60);
  } else if (!receiving) {
    led(40, 0, 0);
  } else if (!my_name[0]) {
    led(0, 0, 40);
  } else {
    led(0, 30, 0);
  }
}

static void send_beat(uint32_t now) {
  radio::Beat b = {};
  radio::header(b.h, radio::HEARTBEAT, net_id);
  Heartbeat& hb = b.hb;
  memcpy(hb.mac, my_mac, 6);
  hb.node_type = DMX_RX;
  hb.fw[0] = FW_MAJOR; hb.fw[1] = FW_MINOR; hb.fw[2] = FW_PATCH;
  hb.uptime_s = (now - boot_ms) / 1000;
  hb.rssi = have_data ? last_rssi : RSSI_NA;
  hb.loss_pct = have_data ? loss_pct : LOSS_NA;
  hb.last_data_age_ms = have_data ? now - last_data_ms : AGE_NEVER;
  hb.universe = my_universe;
  memcpy(hb.name, my_name, NAME_LEN);
  radio_link::send(&b, sizeof(b));
}

void setup() {
  boot_ms = millis();
  led(20, 20, 0);
  prefs.begin("rx", true);
  prefs.getBytes("name", my_name, NAME_LEN);
  my_universe = prefs.getUChar("universe", UNIVERSE_NONE);
  channel = prefs.getUChar("channel", RADIO_CHANNEL);
  if (!radio_link::valid_channel(channel)) channel = RADIO_CHANNEL;
  prefs.end();
  net_id = radio_link::net_id();
  radio_link::begin(on_radio, channel);
  radio_link::own_mac(my_mac);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(on_promisc);
  dmx.begin();
}

void loop() {
  uint32_t now = millis();
  static uint8_t local[DMX_CHANNELS];

  if (frame_dirty) {
    portENTER_CRITICAL(&mux);
    memcpy(local, frame, DMX_CHANNELS);
    frame_dirty = false;
    portEXIT_CRITICAL(&mux);
    dmx.set(local);
  }

  bool receiving = have_data && now - last_data_ms < RECEIVER_SILENCE_MS;
  if (have_data && !receiving) {  // node gone: go dark rather than hold a look forever
    memset(local, 0, sizeof(local));
    portENTER_CRITICAL(&mux);
    memset(frame, 0, sizeof(frame));
    have_data = false;
    portEXIT_CRITICAL(&mux);
    dmx.set(local);
  }
  dmx.service();

  // the node moved channel: follow it, and remember
  if (move_to) {
    channel = move_to;
    move_to = 0;
    radio_link::set_channel(channel);
    prefs.begin("rx", false);
    prefs.putUChar("channel", channel);
    prefs.end();
    last_valid_ms = now;
  }

  // nothing from the rig for a while (missed the move, or the node was re-set): look on every channel
  uint32_t quiet = now - (last_valid_ms ? last_valid_ms : boot_ms);
  if (!scanning && quiet > SCAN_AFTER_MS) {
    scanning = true;
    scan_next_ms = now;
  }
  if (scanning) {
    if (last_valid_ms && now - last_valid_ms < SCAN_DWELL_MS) {  // heard the node on this channel
      scanning = false;
      prefs.begin("rx", false);
      prefs.putUChar("channel", channel);
      prefs.end();
    } else if ((int32_t)(now - scan_next_ms) >= 0) {
      channel = channel >= MAX_CHANNEL ? MIN_CHANNEL : channel + 1;
      radio_link::set_channel(channel);
      scan_next_ms = now + SCAN_DWELL_MS;
    }
  }

  if (assign_pending) {
    portENTER_CRITICAL(&mux);
    my_universe = assign_universe;
    memcpy(my_name, assign_name, NAME_LEN);
    assign_pending = false;
    portEXIT_CRITICAL(&mux);
    prefs.begin("rx", false);
    prefs.putBytes("name", my_name, NAME_LEN);
    prefs.putUChar("universe", my_universe);
    prefs.end();
  }

  if ((int32_t)(now - next_beat_ms) >= 0) {
    next_beat_ms = now + HEARTBEAT_MS;
    portENTER_CRITICAL(&mux);
    uint32_t total = got_seqs + missed_seqs;
    loss_pct = total ? (uint8_t)(missed_seqs * 100 / total) : 0;
    got_seqs = missed_seqs = 0;
    portEXIT_CRITICAL(&mux);
    send_beat(now);
  }
  update_led(now, receiving);
}
