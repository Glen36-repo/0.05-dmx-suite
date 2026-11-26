// 0.05 node: CoreS3 SE + Unit DMX.
// USB serial frames from the laptop -> wired DMX + ESP-NOW to AtomS3 receivers.
// Relays receiver heartbeats to the laptop. Runs the stored fallback look when the laptop is away.
// Protocol: docs/PROTOCOL.md.

#include <Arduino.h>
#include <Preferences.h>

#include "config.h"
#include "dmx_out.h"
#include "proto.h"
#include "radio.h"

using namespace proto;

static Parser parser;
static DmxOut dmx;
static Preferences prefs;
static Fallback fallback;

static uint8_t my_mac[6];
static char my_name[NAME_LEN] = {0};
static uint8_t my_universe = 0;
static uint32_t net_id;

static uint8_t live[DMX_CHANNELS];
static uint8_t out_frame[DMX_CHANNELS];
static Mode mode = FALLBACK;  // boot straight into the safe default
static uint32_t boot_ms, last_frame_ms = 0, fallback_start_ms = 0;
static bool have_frame = false;

static uint32_t frames_rx = 0, other_errors = 0;
static uint32_t rate_count = 0, rate_window_start = 0;
static uint16_t frame_rate_x10 = 0;
static uint32_t next_beat_ms = 0;

static uint8_t radio_seq = 0;
static uint32_t radio_last_ms = 0;
static uint8_t radio_universe = 0;

// ------------------------------------------------------------------ receivers (filled from the Wi-Fi task)

struct Receiver {
  uint8_t mac[6];
  uint32_t last_seen_ms;
  bool announced;
};
static Receiver receivers[MAX_RECEIVERS];
static int n_receivers = 0;

static constexpr int BEAT_QUEUE = 16;
static Heartbeat beat_queue[BEAT_QUEUE];
static volatile int beat_head = 0, beat_tail = 0;
static portMUX_TYPE beat_mux = portMUX_INITIALIZER_UNLOCKED;

static void on_radio(const uint8_t* mac, const uint8_t* data, int len) {
  if (!radio::valid(data, len, net_id)) return;
  const radio::Header* h = (const radio::Header*)data;
  if (h->kind != radio::HEARTBEAT || len != (int)sizeof(radio::Beat)) return;
  portENTER_CRITICAL(&beat_mux);
  int next = (beat_head + 1) % BEAT_QUEUE;
  if (next != beat_tail) {  // drop if full
    beat_queue[beat_head] = ((const radio::Beat*)data)->hb;
    beat_head = next;
  }
  portEXIT_CRITICAL(&beat_mux);
}

static Receiver* find_receiver(const uint8_t* mac) {
  for (int i = 0; i < n_receivers; i++)
    if (!memcmp(receivers[i].mac, mac, 6)) return &receivers[i];
  return nullptr;
}

// ------------------------------------------------------------------ USB out

static void usb_send(uint8_t type, const void* payload, uint16_t len) {
  static uint8_t buf[MAX_PAYLOAD + 6];
  size_t n = encode(buf, type, (const uint8_t*)payload, len);
  if (Serial.availableForWrite() >= (int)n) Serial.write(buf, n);  // never block DMX on a dead USB link
}

static void send_ack(uint8_t type, uint8_t code) {
  if (code != ACK_OK) other_errors++;
  uint8_t p[2] = {type, code};
  usb_send(MSG_ACK, p, 2);
}

static void usb_log(const char* msg) { usb_send(MSG_LOG, msg, strlen(msg)); }

static uint8_t receivers_online() {
  uint8_t n = 0;
  uint32_t now = millis();
  for (int i = 0; i < n_receivers; i++)
    if (now - receivers[i].last_seen_ms < RECEIVER_ONLINE_MS) n++;
  return n;
}

static void send_status() {
  Status s;
  s.uptime_ms = millis() - boot_ms;
  s.frames_rx = frames_rx;
  s.frame_rate_x10 = frame_rate_x10;
  s.crc_errors = parser.crc_errors;
  s.other_errors = other_errors;
  s.mode = mode;
  s.receivers_online = receivers_online();
  usb_send(MSG_STATUS, &s, sizeof(s));
}

static void send_own_beat(bool announce) {
  Heartbeat hb = {};
  memcpy(hb.mac, my_mac, 6);
  hb.node_type = DMX_TX;
  hb.fw[0] = FW_MAJOR; hb.fw[1] = FW_MINOR; hb.fw[2] = FW_PATCH;
  hb.uptime_s = (millis() - boot_ms) / 1000;
  hb.rssi = RSSI_NA;
  hb.loss_pct = LOSS_NA;
  hb.last_data_age_ms = have_frame ? millis() - last_frame_ms : AGE_NEVER;
  hb.universe = my_universe;
  memcpy(hb.name, my_name, NAME_LEN);
  usb_send(announce ? MSG_ANNOUNCE : MSG_HEARTBEAT, &hb, sizeof(hb));
}

// ------------------------------------------------------------------ radio out

static void radio_frame(uint8_t universe, const uint8_t* ch) {
  radio::DmxChunk c;
  radio::header(c.h, radio::DMX_CHUNK, net_id);
  c.universe = universe;
  c.seq = radio_seq++;
  for (uint16_t off = 0; off < DMX_CHANNELS; off += radio::CHUNK_SIZE) {
    uint16_t len = min<uint16_t>(radio::CHUNK_SIZE, DMX_CHANNELS - off);
    c.offset = off;
    c.len = len;
    memcpy(c.data, ch + off, len);
    if (!radio_link::send(&c, offsetof(radio::DmxChunk, data) + len)) other_errors++;
  }
  radio_last_ms = millis();
  radio_universe = universe;
}

// ------------------------------------------------------------------ storage

static void load_prefs() {
  prefs.begin("node", true);
  prefs.getBytes("name", my_name, NAME_LEN);
  my_universe = prefs.getUChar("universe", 0);
  size_t len = prefs.getBytesLength("fallback");
  if (len && len <= MAX_PAYLOAD) {
    static uint8_t buf[MAX_PAYLOAD];
    prefs.getBytes("fallback", buf, len);
    fallback.parse(buf, len);
  }
  prefs.end();
}

static bool save_bytes(const char* key, const void* data, size_t len) {
  prefs.begin("node", false);
  bool ok = prefs.putBytes(key, data, len) == len;
  prefs.end();
  return ok;
}

// ------------------------------------------------------------------ USB in

static void handle(uint8_t type, const uint8_t* p, uint16_t len) {
  uint32_t now = millis();
  switch (type) {
    case MSG_DMX_FRAME: {
      if (len < 2 || len > 1 + DMX_CHANNELS) return send_ack(type, ACK_BAD_LENGTH);
      uint8_t universe = p[0];
      static uint8_t frame[DMX_CHANNELS];
      memset(frame, 0, sizeof(frame));
      memcpy(frame, p + 1, len - 1);
      frames_rx++;
      rate_count++;
      if (universe == my_universe) {
        memcpy(live, frame, DMX_CHANNELS);
        have_frame = true;
        last_frame_ms = now;
        mode = LIVE;
        dmx.set(live);  // immediate: drum hits don't wait for the tick
      }
      radio_frame(universe, frame);  // other universes go to their receivers
      return;
    }
    case MSG_BLACKOUT: {
      if (len != 1) return send_ack(type, ACK_BAD_LENGTH);
      static uint8_t black[DMX_CHANNELS] = {0};
      memset(live, 0, sizeof(live));
      mode = BLACKOUT_MODE;
      have_frame = true;
      last_frame_ms = now;
      if (p[0] == UNIVERSE_ALL || p[0] == my_universe) dmx.set(live);
      if (p[0] == UNIVERSE_ALL) {
        radio_frame(my_universe, black);
        // other universes: receivers go dark on their own after RECEIVER_SILENCE_MS
      } else {
        radio_frame(p[0], black);
      }
      return;
    }
    case MSG_PING:
      if (len != 4) return send_ack(type, ACK_BAD_LENGTH);
      usb_send(MSG_PONG, p, 4);
      return;
    case MSG_STATUS_REQ:
      send_status();
      return;
    case MSG_SET_FALLBACK: {
      Fallback fb;
      uint8_t code = fb.parse(p, len);
      if (code != ACK_OK) return send_ack(type, code);
      if (!save_bytes("fallback", p, len)) return send_ack(type, ACK_STORAGE_ERROR);
      fallback = fb;
      return send_ack(type, ACK_OK);
    }
    case MSG_ASSIGN: {
      if (len != 6 + 1 + NAME_LEN) return send_ack(type, ACK_BAD_LENGTH);
      if (!memcmp(p, my_mac, 6)) {
        memcpy(my_name, p + 7, NAME_LEN);
        my_universe = p[6] == UNIVERSE_NONE ? 0 : p[6];
        prefs.begin("node", false);
        bool ok = prefs.putBytes("name", my_name, NAME_LEN) == NAME_LEN && prefs.putUChar("universe", my_universe);
        prefs.end();
        return send_ack(type, ok ? ACK_OK : ACK_STORAGE_ERROR);
      }
      if (!find_receiver(p)) return send_ack(type, ACK_UNKNOWN_TARGET);
      radio::Assign a;
      radio::header(a.h, radio::ASSIGN, net_id);
      memcpy(a.mac, p, 6);
      a.universe = p[6];
      memcpy(a.name, p + 7, NAME_LEN);
      for (int i = 0; i < 3; i++) radio_link::send(&a, sizeof(a));  // broadcast is unacknowledged: repeat
      return send_ack(type, ACK_OK);
    }
    case MSG_IDENTIFY: {
      if (len != 7) return send_ack(type, ACK_BAD_LENGTH);
      if (!memcmp(p, my_mac, 6)) {
        usb_log("identify: node has no status LED yet");
        return send_ack(type, ACK_OK);
      }
      if (!find_receiver(p)) return send_ack(type, ACK_UNKNOWN_TARGET);
      radio::Identify m;
      radio::header(m.h, radio::IDENTIFY, net_id);
      memcpy(m.mac, p, 6);
      m.seconds = p[6];
      for (int i = 0; i < 3; i++) radio_link::send(&m, sizeof(m));
      return send_ack(type, ACK_OK);
    }
    default:
      return send_ack(type, ACK_UNKNOWN_TYPE);
  }
}

// ------------------------------------------------------------------ main

void setup() {
  boot_ms = millis();
  Serial.setTxTimeoutMs(0);
  Serial.setRxBufferSize(4096);
  Serial.begin(115200);
  net_id = radio_link::net_id();
  load_prefs();
  if (!radio_link::begin(on_radio)) other_errors++;
  radio_link::own_mac(my_mac);
  if (!dmx.begin()) other_errors++;
  fallback_start_ms = millis();
  send_own_beat(true);
  if (!dmx.ok()) usb_log("DMX driver failed to start: check DMX_TX_PIN / DMX_RX_PIN");
}

void loop() {
  uint32_t now = millis();

  // USB in: drain everything available, handle each complete message immediately
  int n = Serial.available();
  while (n-- > 0) {
    parser.push(Serial.read());
    while (parser.next()) handle(parser.type, parser.payload, parser.len);
  }

  // live -> fallback when the laptop goes quiet (blackout stays black: it's the panic button)
  uint16_t hold = fallback.valid ? fallback.hold_ms : 2000;
  if (mode == LIVE && have_frame && now - last_frame_ms > hold) {
    mode = FALLBACK;
    fallback_start_ms = now;
    usb_log("no frames: fallback look running");
  }
  if (mode == FALLBACK && now - radio_last_ms >= DMX_REFRESH_MS) {
    render_fallback(fallback, now - fallback_start_ms, out_frame);
    dmx.set(out_frame);
    radio_frame(my_universe, out_frame);
  }
  dmx.service();

  // keep receivers fed when the laptop's frames are unchanged / slow
  if (mode != FALLBACK && now - radio_last_ms >= RADIO_KEEPALIVE_MS) radio_frame(my_universe, live);

  // receiver heartbeats -> USB
  while (beat_tail != beat_head) {
    Heartbeat hb;
    portENTER_CRITICAL(&beat_mux);
    hb = beat_queue[beat_tail];
    beat_tail = (beat_tail + 1) % BEAT_QUEUE;
    portEXIT_CRITICAL(&beat_mux);
    Receiver* r = find_receiver(hb.mac);
    if (!r && n_receivers < MAX_RECEIVERS) {
      r = &receivers[n_receivers++];
      memcpy(r->mac, hb.mac, 6);
      r->announced = false;
    }
    bool announce = r && !r->announced;
    if (r) {
      r->last_seen_ms = now;
      r->announced = true;
    }
    usb_send(announce ? MSG_ANNOUNCE : MSG_HEARTBEAT, &hb, sizeof(hb));
  }

  // own heartbeat + status every second
  if ((int32_t)(now - next_beat_ms) >= 0) {
    next_beat_ms = now + HEARTBEAT_MS;
    uint32_t span = now - rate_window_start;
    frame_rate_x10 = span ? (uint16_t)min<uint32_t>(rate_count * 10000 / span, 65535) : 0;
    rate_count = 0;
    rate_window_start = now;
    send_own_beat(false);
    send_status();
  }
}
